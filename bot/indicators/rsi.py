"""Relative Strength Index (RSI) using Wilder's exponential smoothing."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute Wilder's RSI bounded cleanly in [0, 100]."""
    if period < 2:
        raise ValueError("RSI period must be >= 2")

    prices = series.astype(float)
    delta = prices.diff()

    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Handle flat or pure-upward / pure-downward segments cleanly
    rsi = rsi.where(~((avg_loss == 0.0) & (avg_gain > 0.0)), 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss > 0.0)), 0.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)

    return rsi.clip(lower=0.0, upper=100.0)
