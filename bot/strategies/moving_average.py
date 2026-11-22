"""Moving Average Crossover strategy with RSI and volume confirmation."""

from __future__ import annotations

import pandas as pd

from bot.indicators.ema import calculate_atr, calculate_ema
from bot.indicators.rsi import calculate_rsi
from bot.strategies.signals import BaseStrategy, SignalAction, TradingSignal


class MovingAverageStrategy(BaseStrategy):
    """EMA fast/slow crossover enhanced with momentum and volume filters."""

    name = "moving_average"

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        atr_period: int = 14,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.atr_period = atr_period

    @property
    def min_bars(self) -> int:
        return max(self.slow_period, self.rsi_period, self.atr_period) + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> TradingSignal:
        if len(df) < self.min_bars:
            price = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.HOLD,
                confidence=0.0,
                price=price,
                strategy=self.name,
                reason=f"Insufficient bars ({len(df)} < {self.min_bars})",
            )

        close = df["close"].astype(float)
        ema_fast = calculate_ema(close, self.fast_period)
        ema_slow = calculate_ema(close, self.slow_period)
        rsi = calculate_rsi(close, self.rsi_period)
        atr = calculate_atr(df, self.atr_period)

        curr_price = float(close.iloc[-1])
        fast_now, fast_prev = float(ema_fast.iloc[-1]), float(ema_fast.iloc[-2])
        slow_now, slow_prev = float(ema_slow.iloc[-1]), float(ema_slow.iloc[-2])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else None

        vol_ratio = 1.0
        if "volume" in df.columns and len(df) >= 20:
            avg_vol = float(df["volume"].iloc[-20:].mean())
            if avg_vol > 0:
                vol_ratio = float(df["volume"].iloc[-1]) / avg_vol

        meta = {
            "ema_fast": round(fast_now, 4),
            "ema_slow": round(slow_now, 4),
            "rsi": round(rsi_now, 2),
            "atr": round(atr_now, 4) if atr_now is not None else None,
            "volume_ratio": round(vol_ratio, 2),
        }

        bullish_cross = fast_prev <= slow_prev and fast_now > slow_now
        bearish_cross = fast_prev >= slow_prev and fast_now < slow_now

        if bullish_cross and rsi_now < self.rsi_overbought:
            confidence = 0.70 + (0.15 if vol_ratio >= 1.1 else 0.0) + (0.10 if rsi_now > 50 else 0.0)
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.BUY,
                confidence=min(confidence, 0.95),
                price=curr_price,
                atr=atr_now,
                strategy=self.name,
                reason=f"EMA({self.fast_period}) crossed above EMA({self.slow_period}), RSI={rsi_now:.1f}",
                metadata=meta,
            )

        if bearish_cross and rsi_now > self.rsi_oversold:
            confidence = 0.70 + (0.15 if vol_ratio >= 1.1 else 0.0) + (0.10 if rsi_now < 50 else 0.0)
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.SELL,
                confidence=min(confidence, 0.95),
                price=curr_price,
                atr=atr_now,
                strategy=self.name,
                reason=f"EMA({self.fast_period}) crossed below EMA({self.slow_period}), RSI={rsi_now:.1f}",
                metadata=meta,
            )

        return TradingSignal(
            symbol=symbol,
            action=SignalAction.HOLD,
            confidence=0.0,
            price=curr_price,
            atr=atr_now,
            strategy=self.name,
            reason="No MA crossover confirmation",
            metadata=meta,
        )
