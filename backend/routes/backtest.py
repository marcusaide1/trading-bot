"""On-demand historical backtest execution and run history endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from bot.backtesting.engine import BacktestEngine
from bot.exchange.client import BinanceExchangeClient
from bot.exchange.market_data import MarketDataProvider, generate_synthetic_ohlcv
from database.models import BacktestRun, get_session_factory

router = APIRouter()


class BacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    strategy: Literal["trend_following", "moving_average", "composite"] = "composite"
    bars: int = Field(default=500, ge=100, le=2000)
    initial_capital: float = Field(default=10000.0, gt=100.0)
    stop_loss_pct: float = Field(default=0.02, gt=0.002, le=0.25)
    take_profit_pct: float = Field(default=0.04, gt=0.004, le=1.0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0.001, le=0.10)
    use_synthetic: bool = False


@router.post("/run")
def run_backtest(payload: BacktestRequest, request: Request) -> dict[str, Any]:
    base_settings = request.app.state.settings
    sim_settings = base_settings.model_copy(
        update={
            "trading_mode": "paper",
            "strategy_name": payload.strategy,
            "initial_capital": payload.initial_capital,
            "stop_loss_pct": payload.stop_loss_pct,
            "take_profit_pct": payload.take_profit_pct,
            "risk_per_trade_pct": payload.risk_per_trade_pct,
        }
    )

    if payload.use_synthetic:
        df = generate_synthetic_ohlcv(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            bars=payload.bars,
        )
    else:
        client = BinanceExchangeClient(sim_settings)
        md = MarketDataProvider(exchange_client=client, redis_url=sim_settings.redis_url)
        df = md.get_ohlcv(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            limit=payload.bars,
            allow_synthetic_fallback=True,
        )

    try:
        engine = BacktestEngine(settings=sim_settings)
        result = engine.run(
            df=df,
            symbol=payload.symbol.upper(),
            timeframe=payload.timeframe,
            initial_capital=payload.initial_capital,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_factory = get_session_factory(base_settings.database_url)
    with session_factory() as db:
        record = BacktestRun(
            symbol=result.symbol,
            timeframe=result.timeframe,
            strategy=result.strategy,
            initial_capital=result.metrics.initial_capital,
            final_equity=result.metrics.final_equity,
            total_return_pct=result.metrics.total_return_pct,
            sharpe_ratio=result.metrics.sharpe_ratio,
            max_drawdown_pct=result.metrics.max_drawdown_pct,
            win_rate_pct=result.metrics.win_rate_pct,
            profit_factor=result.metrics.profit_factor,
            total_trades=result.metrics.total_trades,
            metrics_json=result.metrics.to_dict(),
            equity_curve_json=result.equity_curve,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        run_id = record.id

    response = result.to_dict()
    response["id"] = run_id
    return response


@router.get("/history")
def list_backtest_runs(
    request: Request, limit: int = Query(default=20, ge=1, le=100)
) -> list[dict[str, Any]]:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as db:
        rows = (
            db.query(BacktestRun)
            .order_by(BacktestRun.created_at.desc())
            .limit(limit)
            .all()
        )

    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "strategy": r.strategy,
            "initial_capital": r.initial_capital,
            "final_equity": r.final_equity,
            "total_return_pct": r.total_return_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown_pct": r.max_drawdown_pct,
            "win_rate_pct": r.win_rate_pct,
            "profit_factor": r.profit_factor,
            "total_trades": r.total_trades,
            "metrics": r.metrics_json or {},
            "equity_curve": r.equity_curve_json or [],
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
