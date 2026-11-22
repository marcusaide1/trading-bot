"""Portfolio summary, open positions, trade history, equity curve, and signals endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from database.models import (
    BotState,
    EquitySnapshot,
    PositionRecord,
    SignalRecord,
    TradeRecord,
    get_session_factory,
)

router = APIRouter()


@router.get("/portfolio")
def get_portfolio_summary(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings.database_url)

    with session_factory() as db:
        state = db.get(BotState, 1)
        positions = db.query(PositionRecord).all()
        exit_trades = db.query(TradeRecord).filter(TradeRecord.action == "exit").all()
        all_trades = db.query(TradeRecord).all()

    initial = settings.initial_capital
    equity = state.equity if state else initial
    cash = state.cash if state else initial
    peak = state.peak_equity if state else initial
    unrealized = sum(p.unrealized_pnl for p in positions)
    realized = sum(t.realized_pnl for t in exit_trades)
    total_fees = sum(t.fee for t in all_trades)
    wins = [t for t in exit_trades if t.realized_pnl > 0]
    losses = [t for t in exit_trades if t.realized_pnl < 0]
    gross_profit = sum(t.realized_pnl for t in wins)
    gross_loss = abs(sum(t.realized_pnl for t in losses))
    profit_factor = (
        round(gross_profit / gross_loss, 2)
        if gross_loss > 0
        else (99.99 if gross_profit > 0 else 0.0)
    )
    win_rate = (len(wins) / len(exit_trades) * 100.0) if exit_trades else 0.0
    total_return_pct = ((equity - initial) / initial * 100.0) if initial > 0 else 0.0
    drawdown_pct = max(0.0, (peak - equity) / peak * 100.0) if peak > 0 else 0.0

    return {
        "initial_capital": round(initial, 2),
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "total_return_pct": round(total_return_pct, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": profit_factor,
        "total_trades": len(exit_trades),
        "open_positions_count": len(positions),
        "total_fees_paid": round(total_fees, 4),
    }


@router.get("/positions")
def list_positions(request: Request) -> list[dict[str, Any]]:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as db:
        rows = db.query(PositionRecord).order_by(PositionRecord.opened_at.desc()).all()

    return [
        {
            "symbol": p.symbol,
            "side": p.side,
            "quantity": round(p.quantity, 6),
            "entry_price": round(p.entry_price, 4),
            "current_price": round(p.current_price, 4),
            "stop_loss": round(p.stop_loss, 4),
            "take_profit": round(p.take_profit, 4),
            "trailing_stop": round(p.trailing_stop, 4) if p.trailing_stop else None,
            "unrealized_pnl": round(p.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(
                (p.unrealized_pnl / (p.entry_price * p.quantity) * 100.0)
                if p.entry_price * p.quantity > 0
                else 0.0,
                2,
            ),
            "strategy": p.strategy,
            "opened_at": p.opened_at.isoformat(),
        }
        for p in rows
    ]


@router.get("/trades")
def list_trades(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as db:
        query = db.query(TradeRecord)
        if symbol:
            query = query.filter(TradeRecord.symbol == symbol.upper())
        rows = query.order_by(TradeRecord.created_at.desc()).limit(limit).all()

    return [
        {
            "id": t.id,
            "order_id": t.order_id,
            "symbol": t.symbol,
            "side": t.side,
            "action": t.action,
            "quantity": round(t.quantity, 6),
            "price": round(t.price, 4),
            "fee": round(t.fee, 4),
            "realized_pnl": round(t.realized_pnl, 2),
            "pnl_pct": round(t.pnl_pct, 2),
            "strategy": t.strategy,
            "mode": t.mode,
            "reason": t.reason,
            "timestamp": t.created_at.isoformat(),
        }
        for t in rows
    ]


@router.get("/equity-curve")
def get_equity_curve(
    request: Request, limit: int = Query(default=200, ge=10, le=1000)
) -> list[dict[str, Any]]:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as db:
        rows = (
            db.query(EquitySnapshot)
            .order_by(EquitySnapshot.timestamp.desc())
            .limit(limit)
            .all()
        )
    rows.reverse()
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "equity": round(r.equity, 2),
            "cash": round(r.cash, 2),
            "unrealized_pnl": round(r.unrealized_pnl, 2),
            "drawdown_pct": round(r.drawdown_pct, 2),
            "open_positions": r.open_positions,
        }
        for r in rows
    ]


@router.get("/signals")
def list_signals(
    request: Request,
    limit: int = Query(default=40, ge=1, le=200),
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as db:
        query = db.query(SignalRecord)
        if symbol:
            query = query.filter(SignalRecord.symbol == symbol.upper())
        rows = query.order_by(SignalRecord.created_at.desc()).limit(limit).all()

    return [
        {
            "id": s.id,
            "symbol": s.symbol,
            "strategy": s.strategy,
            "action": s.action,
            "confidence": round(s.confidence, 3),
            "price": round(s.price, 4),
            "stop_loss": round(s.stop_loss, 4) if s.stop_loss else None,
            "take_profit": round(s.take_profit, 4) if s.take_profit else None,
            "reason": s.reason,
            "metadata": s.metadata_json or {},
            "timestamp": s.created_at.isoformat(),
        }
        for s in rows
    ]
