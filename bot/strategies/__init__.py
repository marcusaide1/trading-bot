"""Trading strategies and unified signal generation."""

from bot.strategies.moving_average import MovingAverageStrategy
from bot.strategies.signals import (
    BaseStrategy,
    CompositeStrategy,
    SignalAction,
    TradingSignal,
    create_strategy,
)
from bot.strategies.trend_following import TrendFollowingStrategy

__all__ = [
    "SignalAction",
    "TradingSignal",
    "BaseStrategy",
    "MovingAverageStrategy",
    "TrendFollowingStrategy",
    "CompositeStrategy",
    "create_strategy",
]
