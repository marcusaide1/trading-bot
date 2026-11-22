"""Exponential Moving Average (EMA), Simple Moving Average (SMA), and ATR indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Compute Exponential Moving Average with standard smoothing factor 2 / (period + 1)."""
    if period < 1:
        raise ValueError("EMA period must be >= 1")
    return series.astype(float).ewm(span=period, adjust=False, min_periods=period).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Compute Simple Moving Average."""
    if period < 1:
        raise ValueError("SMA period must be >= 1")
    return series.astype(float).rolling(window=period, min_periods=period).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range (Wilder's smoothing) for volatility-aware stops and sizing."""
    if period < 1:
        raise ValueError("ATR period must be >= 1")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return atr.replace([np.inf, -np.inf], np.nan)
