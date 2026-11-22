"""Multi-factor Trend Following strategy using EMA trend regime, MACD, and RSI."""

from __future__ import annotations

import pandas as pd

from bot.indicators.ema import calculate_atr, calculate_ema
from bot.indicators.macd import calculate_macd
from bot.indicators.rsi import calculate_rsi
from bot.strategies.signals import BaseStrategy, SignalAction, TradingSignal


class TrendFollowingStrategy(BaseStrategy):
    """Follows primary trend using EMA alignment + MACD momentum + RSI pullback bounds."""

    name = "trend_following"

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        trend_period: int = 200,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        atr_period: int = 14,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.trend_period = trend_period
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period

    @property
    def min_bars(self) -> int:
        # Allow operation even when fewer than 200 bars exist by degrading trend period smoothly
        return max(self.slow_period + self.macd_signal, self.rsi_period, self.atr_period) + 5

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
        effective_trend_period = min(self.trend_period, max(50, len(df) - 5))

        ema_fast = calculate_ema(close, self.fast_period)
        ema_slow = calculate_ema(close, self.slow_period)
        ema_trend = calculate_ema(close, effective_trend_period)
        rsi = calculate_rsi(close, self.rsi_period)
        macd_df = calculate_macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        atr = calculate_atr(df, self.atr_period)

        curr_price = float(close.iloc[-1])
        fast_now = float(ema_fast.iloc[-1])
        slow_now = float(ema_slow.iloc[-1])
        trend_now = float(ema_trend.iloc[-1])
        trend_prev = float(ema_trend.iloc[-5]) if len(ema_trend) >= 5 else trend_now
        rsi_now = float(rsi.iloc[-1])
        hist_now = float(macd_df["histogram"].iloc[-1])
        hist_prev = float(macd_df["histogram"].iloc[-2])
        atr_now = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else None

        meta = {
            "ema_fast": round(fast_now, 4),
            "ema_slow": round(slow_now, 4),
            "ema_trend": round(trend_now, 4),
            "rsi": round(rsi_now, 2),
            "macd_hist": round(hist_now, 5),
            "atr": round(atr_now, 4) if atr_now is not None else None,
        }

        # Bullish trend continuation: price above macro EMA, fast > slow, rising MACD hist, healthy RSI
        uptrend = curr_price > trend_now and trend_now >= trend_prev * 0.999 and fast_now > slow_now
        macd_bullish = hist_now > 0 and hist_now > hist_prev
        rsi_healthy_buy = 45.0 <= rsi_now <= self.rsi_overbought

        if uptrend and macd_bullish and rsi_healthy_buy:
            strength = min(1.0, abs(fast_now - slow_now) / max(curr_price * 0.005, 1e-9))
            confidence = min(0.95, 0.65 + 0.25 * strength)
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.BUY,
                confidence=confidence,
                price=curr_price,
                atr=atr_now,
                strategy=self.name,
                reason=(
                    f"Uptrend above EMA({effective_trend_period}), "
                    f"MACD hist accelerating ({hist_now:+.4f}), RSI={rsi_now:.1f}"
                ),
                metadata=meta,
            )

        # Bearish reversal / exit trigger: loss of EMA alignment or overbought breakdown
        downtrend = (curr_price < trend_now and fast_now < slow_now) or (
            fast_now < slow_now and hist_now < 0 and hist_now < hist_prev
        )
        rsi_exit = rsi_now < 48.0 or rsi_now > self.rsi_overbought + 8.0

        if downtrend and rsi_exit and hist_now < 0:
            strength = min(1.0, abs(slow_now - fast_now) / max(curr_price * 0.005, 1e-9))
            confidence = min(0.95, 0.65 + 0.25 * strength)
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.SELL,
                confidence=confidence,
                price=curr_price,
                atr=atr_now,
                strategy=self.name,
                reason=(
                    f"Bearish trend/momentum shift, MACD hist={hist_now:+.4f}, RSI={rsi_now:.1f}"
                ),
                metadata=meta,
            )

        return TradingSignal(
            symbol=symbol,
            action=SignalAction.HOLD,
            confidence=0.0,
            price=curr_price,
            atr=atr_now,
            strategy=self.name,
            reason="Trend/momentum conditions neutral",
            metadata=meta,
        )
