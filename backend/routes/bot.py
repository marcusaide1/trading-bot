"""Bot lifecycle control, status, and runtime configuration endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from database.models import BotState, get_session_factory

router = APIRouter()


class BotConfigUpdate(BaseModel):
    strategy: Literal["trend_following", "moving_average", "composite"] | None = None
    timeframe: str | None = None
    symbols: list[str] | None = None
    risk_per_trade_pct: float | None = Field(default=None, gt=0.0, le=0.10)


@router.get("/status")
def get_bot_status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    runtime = request.app.state.runtime
    session_factory = get_session_factory(settings.database_url)

    with session_factory() as db:
        state = db.get(BotState, 1)

    if state is None:
        return {
            "is_running": runtime.is_running,
            "is_halted": False,
            "halt_reason": "",
            "mode": settings.trading_mode,
            "market_type": settings.market_type,
            "exchange": settings.exchange_name,
            "strategy": settings.strategy_name,
            "symbols": settings.symbols_list,
            "timeframe": settings.timeframe,
            "equity": settings.initial_capital,
            "cash": settings.initial_capital,
            "peak_equity": settings.initial_capital,
            "drawdown_pct": 0.0,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_drawdown_pct": settings.max_drawdown_pct,
            "updated_at": None,
        }

    dd = (
        max(0.0, (state.peak_equity - state.equity) / state.peak_equity) * 100.0
        if state.peak_equity > 0
        else 0.0
    )
    return {
        "is_running": runtime.is_running or state.is_running,
        "is_halted": state.is_halted,
        "halt_reason": state.halt_reason,
        "mode": state.mode,
        "market_type": settings.market_type,
        "exchange": settings.exchange_name,
        "strategy": state.strategy,
        "symbols": [s for s in state.symbols.split(",") if s],
        "timeframe": state.timeframe,
        "equity": round(state.equity, 2),
        "cash": round(state.cash, 2),
        "peak_equity": round(state.peak_equity, 2),
        "drawdown_pct": round(dd, 2),
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "max_drawdown_pct": settings.max_drawdown_pct,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


@router.post("/start")
def start_bot(request: Request) -> dict[str, Any]:
    return request.app.state.runtime.start()


@router.post("/stop")
def stop_bot(request: Request) -> dict[str, Any]:
    return request.app.state.runtime.stop()


@router.post("/cycle")
def run_bot_cycle(request: Request) -> dict[str, Any]:
    """Execute one immediate market evaluation cycle (useful in paper/testing)."""
    return request.app.state.runtime.run_single_cycle()


@router.post("/reset-halt")
def reset_risk_halt(request: Request) -> dict[str, Any]:
    """Clear a risk circuit breaker halt after operator review."""
    return request.app.state.runtime.reset_halt()


@router.patch("/config")
def update_bot_config(payload: BotConfigUpdate, request: Request) -> dict[str, Any]:
    return request.app.state.runtime.update_config(
        strategy=payload.strategy,
        timeframe=payload.timeframe,
        symbols=payload.symbols,
        risk_per_trade_pct=payload.risk_per_trade_pct,
    )
