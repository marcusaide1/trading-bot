"""Signal data models, BaseStrategy protocol, and Composite multi-strategy ensemble."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from bot.config import Settings


class SignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradingSignal:
    """Structured strategy output passed to risk management and order execution."""

    symbol: str
    action: SignalAction
    confidence: float
    price: float
    strategy: str
    reason: str = ""
    atr: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "confidence": round(self.confidence, 4),
            "price": round(self.price, 6),
            "strategy": self.strategy,
            "reason": self.reason,
            "atr": self.atr,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class BaseStrategy(ABC):
    """Interface implemented by all trading strategies."""

    name: str = "base"

    @property
    @abstractmethod
    def min_bars(self) -> int:
        """Minimum OHLCV bars needed before emitting non-HOLD signals."""

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> TradingSignal:
        """Evaluate OHLCV history and return a TradingSignal for the latest closed candle."""


class CompositeStrategy(BaseStrategy):
    """Weighted ensemble combining TrendFollowing and MovingAverage strategies."""

    name = "composite"

    def __init__(
        self,
        strategies: list[tuple[BaseStrategy, float]],
        buy_threshold: float = 0.45,
        sell_threshold: float = -0.45,
    ) -> None:
        if not strategies:
            raise ValueError("CompositeStrategy requires at least one sub-strategy")
        self.strategies = strategies
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    @property
    def min_bars(self) -> int:
        return max(s.min_bars for s, _ in self.strategies)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> TradingSignal:
        total_weight = sum(w for _, w in self.strategies)
        weighted_score = 0.0
        reasons: list[str] = []
        sub_signals: dict[str, str] = {}
        latest_price = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
        atr_val: float | None = None

        for strat, weight in self.strategies:
            sig = strat.generate_signal(df, symbol)
            latest_price = sig.price
            if sig.atr is not None:
                atr_val = sig.atr
            sub_signals[strat.name] = f"{sig.action.value}({sig.confidence:.2f})"
            if sig.action == SignalAction.BUY:
                weighted_score += weight * sig.confidence
                reasons.append(f"[{strat.name}] {sig.reason}")
            elif sig.action == SignalAction.SELL:
                weighted_score -= weight * sig.confidence
                reasons.append(f"[{strat.name}] {sig.reason}")

        normalized = weighted_score / total_weight if total_weight > 0 else 0.0

        if normalized >= self.buy_threshold:
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.BUY,
                confidence=min(1.0, abs(normalized)),
                price=latest_price,
                atr=atr_val,
                strategy=self.name,
                reason="; ".join(reasons) or "Composite bullish consensus",
                metadata={"score": round(normalized, 3), "votes": sub_signals},
            )

        if normalized <= self.sell_threshold:
            return TradingSignal(
                symbol=symbol,
                action=SignalAction.SELL,
                confidence=min(1.0, abs(normalized)),
                price=latest_price,
                atr=atr_val,
                strategy=self.name,
                reason="; ".join(reasons) or "Composite bearish consensus",
                metadata={"score": round(normalized, 3), "votes": sub_signals},
            )

        return TradingSignal(
            symbol=symbol,
            action=SignalAction.HOLD,
            confidence=0.0,
            price=latest_price,
            atr=atr_val,
            strategy=self.name,
            reason="Composite score within neutral band",
            metadata={"score": round(normalized, 3), "votes": sub_signals},
        )


def create_strategy(name: str, settings: Settings | None = None) -> BaseStrategy:
    """Factory creating a configured strategy instance by name."""
    from bot.strategies.moving_average import MovingAverageStrategy
    from bot.strategies.trend_following import TrendFollowingStrategy

    kwargs_ma: dict[str, Any] = {}
    kwargs_tf: dict[str, Any] = {}

    if settings is not None:
        kwargs_ma = {
            "fast_period": settings.ema_fast_period,
            "slow_period": settings.ema_slow_period,
            "rsi_period": settings.rsi_period,
            "rsi_overbought": settings.rsi_overbought,
            "rsi_oversold": settings.rsi_oversold,
            "atr_period": settings.atr_period,
        }
        kwargs_tf = {
            **kwargs_ma,
            "trend_period": settings.ema_trend_period,
            "macd_fast": settings.macd_fast,
            "macd_slow": settings.macd_slow,
            "macd_signal": settings.macd_signal,
        }

    key = name.strip().lower()
    if key == "moving_average":
        return MovingAverageStrategy(**kwargs_ma)
    if key == "trend_following":
        return TrendFollowingStrategy(**kwargs_tf)
    if key == "composite":
        return CompositeStrategy(
            strategies=[
                (TrendFollowingStrategy(**kwargs_tf), 0.60),
                (MovingAverageStrategy(**kwargs_ma), 0.40),
            ],
            buy_threshold=0.35,
            sell_threshold=-0.35,
        )
    raise ValueError(
        f"Unknown strategy '{name}'. Choose from: trend_following, moving_average, composite."
    )
