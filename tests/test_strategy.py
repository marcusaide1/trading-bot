"""Tests for technical indicators and trading strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bot.exchange.market_data import generate_synthetic_ohlcv
from bot.indicators.ema import calculate_atr, calculate_ema, calculate_sma
from bot.indicators.macd import calculate_macd
from bot.indicators.rsi import calculate_rsi
from bot.strategies.moving_average import MovingAverageStrategy
from bot.strategies.signals import SignalAction, create_strategy
from bot.strategies.trend_following import TrendFollowingStrategy


def _make_trend_df(direction: str = "up", bars: int = 120) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=bars, freq="15min", tz="UTC")
    if direction == "up":
        # Mild pull-down then accelerating uptrend to trigger crossover + MACD expansion
        base = np.concatenate(
            [
                np.linspace(110.0, 95.0, 40),
                np.linspace(95.0, 130.0, bars - 40),
            ]
        )
    elif direction == "down":
        base = np.concatenate(
            [
                np.linspace(90.0, 115.0, 40),
                np.linspace(115.0, 80.0, bars - 40),
            ]
        )
    else:
        base = np.full(bars, 100.0)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": base * 0.999,
            "high": base * 1.005,
            "low": base * 0.995,
            "close": base,
            "volume": np.full(bars, 250.0),
        }
    )


def test_ema_and_sma_values() -> None:
    series = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    ema = calculate_ema(series, 3)
    sma = calculate_sma(series, 3)
    assert pd.isna(ema.iloc[0])
    assert pytest.approx(sma.iloc[-1], rel=1e-6) == 14.0
    assert ema.iloc[-1] > sma.iloc[-2]


def test_rsi_bounds_and_monotonicity() -> None:
    up = pd.Series(np.linspace(100, 150, 40))
    down = pd.Series(np.linspace(150, 100, 40))
    flat = pd.Series(np.full(40, 100.0))

    assert calculate_rsi(up, 14).iloc[-1] == 100.0
    assert calculate_rsi(down, 14).iloc[-1] == 0.0
    assert calculate_rsi(flat, 14).iloc[-1] == 50.0


def test_macd_and_atr_shapes() -> None:
    df = generate_synthetic_ohlcv(bars=100, seed=7)
    macd_df = calculate_macd(df["close"])
    atr = calculate_atr(df, period=14)

    assert set(macd_df.columns) == {"macd", "signal", "histogram"}
    assert len(macd_df) == len(df)
    assert (atr.dropna() > 0).all()


def test_moving_average_crossover_triggers_buy() -> None:
    # Construct a crisp crossover on the final candle
    prices = [100.0] * 35 + [98.0, 97.5, 97.0, 96.5, 96.0, 96.5, 97.5, 99.0, 101.5, 104.5]
    timestamps = pd.date_range("2026-01-01", periods=len(prices), freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices,
            "high": [p * 1.004 for p in prices],
            "low": [p * 0.996 for p in prices],
            "close": prices,
            "volume": [100.0] * (len(prices) - 1) + [220.0],
        }
    )
    strat = MovingAverageStrategy(fast_period=5, slow_period=12, rsi_overbought=85.0)
    actions = [
        strat.generate_signal(df.iloc[:i], "BTC/USDT").action
        for i in range(strat.min_bars, len(df) + 1)
    ]
    assert SignalAction.BUY in actions


def test_trend_following_detects_uptrend_and_downtrend() -> None:
    strat = TrendFollowingStrategy(
        fast_period=8, slow_period=21, trend_period=50, rsi_overbought=95.0
    )
    up_df = _make_trend_df("up", bars=100)
    down_df = _make_trend_df("down", bars=100)

    up_sig = strat.generate_signal(up_df, "BTC/USDT")
    down_sig = strat.generate_signal(down_df, "BTC/USDT")

    assert up_sig.action == SignalAction.BUY
    assert up_sig.confidence > 0.5
    assert down_sig.action == SignalAction.SELL


def test_strategy_returns_hold_on_short_history() -> None:
    short_df = generate_synthetic_ohlcv(bars=10, seed=1)
    for name in ("moving_average", "trend_following", "composite"):
        strat = create_strategy(name)
        sig = strat.generate_signal(short_df, "ETH/USDT")
        assert sig.action == SignalAction.HOLD


def test_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        create_strategy("nonexistent_strategy")
