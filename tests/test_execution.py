"""Tests for portfolio accounting, order execution, backtesting engine, and FastAPI routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from bot.backtesting.engine import BacktestEngine
from bot.config import Settings
from bot.exchange.market_data import generate_synthetic_ohlcv
from bot.execution.orders import OrderExecutor
from bot.execution.portfolio import Portfolio
from bot.risk.stop_loss import StopLevels


def test_portfolio_long_and_short_accounting_exact() -> None:
    # Long round-trip
    pf = Portfolio(initial_capital=10000.0)
    pf.open_position(
        order_id="o1",
        symbol="BTC/USDT",
        side="long",
        quantity=1.0,
        fill_price=1000.0,
        fee=1.0,
        stop_loss=950.0,
        take_profit=1100.0,
    )
    assert pytest.approx(pf.cash) == 8999.0
    assert pytest.approx(pf.equity) == 9999.0

    fill = pf.close_position(order_id="o2", symbol="BTC/USDT", fill_price=1100.0, fee=1.1)
    assert pytest.approx(fill.realized_pnl) == 97.9
    assert pytest.approx(pf.equity) == 10097.9
    assert pytest.approx(pf.cash) == 10097.9

    # Short round-trip
    pf_short = Portfolio(initial_capital=10000.0)
    pf_short.open_position(
        order_id="s1",
        symbol="ETH/USDT",
        side="short",
        quantity=1.0,
        fill_price=1000.0,
        fee=1.0,
        stop_loss=1050.0,
        take_profit=900.0,
    )
    pf_short.update_price("ETH/USDT", 900.0)
    assert pytest.approx(pf_short.unrealized_pnl) == 100.0
    assert pytest.approx(pf_short.equity) == 10099.0

    close_short = pf_short.close_position(
        order_id="s2", symbol="ETH/USDT", fill_price=900.0, fee=0.9
    )
    assert pytest.approx(close_short.realized_pnl) == 98.1
    assert pytest.approx(pf_short.equity) == 10098.1


def test_paper_order_executor_applies_slippage_and_fees() -> None:
    settings = Settings(trading_mode="paper", fee_rate=0.001, slippage_pct=0.001)
    portfolio = Portfolio(initial_capital=10000.0)
    executor = OrderExecutor(settings=settings, portfolio=portfolio)

    stops = StopLevels(stop_loss=98.0, take_profit=104.0, trailing_stop=98.0)
    entry = executor.execute_entry(
        symbol="SOL/USDT",
        side="long",
        quantity=10.0,
        reference_price=100.0,
        stops=stops,
    )
    assert entry.success and entry.fill is not None
    assert pytest.approx(entry.fill.price) == 100.1  # adverse buy slippage
    assert portfolio.has_position("SOL/USDT")

    exit_res = executor.execute_exit(symbol="SOL/USDT", reference_price=105.0, reason="take_profit")
    assert exit_res.success and exit_res.fill is not None
    assert pytest.approx(exit_res.fill.price) == 105.0 * 0.999  # adverse sell slippage
    assert exit_res.fill.realized_pnl > 0
    assert not portfolio.has_position("SOL/USDT")


def test_backtest_engine_end_to_end() -> None:
    settings = Settings(trading_mode="paper", strategy_name="composite", initial_capital=10000.0)
    df = generate_synthetic_ohlcv(symbol="BTC/USDT", timeframe="15m", bars=400, seed=42)
    engine = BacktestEngine(settings=settings)
    result = engine.run(df=df, symbol="BTC/USDT", timeframe="15m")

    assert result.symbol == "BTC/USDT"
    assert len(result.equity_curve) > 10
    assert result.metrics.final_equity > 0
    assert result.metrics.max_drawdown_pct >= 0.0


def test_fastapi_endpoints(tmp_path) -> None:
    db_file = tmp_path / "api_test.db"
    settings = Settings(
        trading_mode="paper",
        database_url=f"sqlite:///{db_file.as_posix()}",
        initial_capital=10000.0,
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    status = client.get("/api/bot/status").json()
    assert status["mode"] == "paper"
    assert status["equity"] == 10000.0

    bt = client.post(
        "/api/backtest/run",
        json={
            "symbol": "BTC/USDT",
            "timeframe": "15m",
            "strategy": "composite",
            "bars": 250,
            "initial_capital": 10000.0,
            "use_synthetic": True,
        },
    )
    assert bt.status_code == 200
    body = bt.json()
    assert "metrics" in body
    assert "equity_curve" in body

    history = client.get("/api/backtest/history")
    assert history.status_code == 200
    assert len(history.json()) >= 1
