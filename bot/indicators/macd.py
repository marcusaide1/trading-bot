"""Moving Average Convergence Divergence (MACD) indicator."""

from __future__ import annotations

import pandas as pd

from bot.indicators.ema import calculate_ema


def calculate_macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """Compute MACD line, Signal line, and Histogram.

    Returns a DataFrame with columns: ``macd``, ``signal``, ``histogram``.
    """
    if fast_period >= slow_period:
        raise ValueError("MACD fast_period must be less than slow_period")
    if signal_period < 1:
        raise ValueError("MACD signal_period must be >= 1")

    ema_fast = calculate_ema(series, fast_period)
    ema_slow = calculate_ema(series, slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(
        span=signal_period, adjust=False, min_periods=signal_period
    ).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram,
        },
        index=series.index,
    )
