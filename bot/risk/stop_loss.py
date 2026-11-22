"""Stop-loss, take-profit, ATR volatility stops, and trailing stop management."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopLevels:
    stop_loss: float
    take_profit: float
    trailing_stop: float | None = None


class StopLossManager:
    """Computes protective stops and evaluates exit triggers conservatively."""

    def __init__(
        self,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
        trailing_stop_pct: float = 0.015,
        use_atr_stops: bool = True,
        atr_stop_multiplier: float = 2.0,
        atr_tp_multiplier: float = 4.0,
    ) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.use_atr_stops = use_atr_stops
        self.atr_stop_multiplier = atr_stop_multiplier
        self.atr_tp_multiplier = atr_tp_multiplier

    def compute_levels(
        self,
        entry_price: float,
        side: str = "long",
        atr: float | None = None,
    ) -> StopLevels:
        """Calculate initial stop-loss and take-profit prices."""
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        side_norm = side.lower()
        if self.use_atr_stops and atr is not None and atr > 0:
            stop_dist = min(atr * self.atr_stop_multiplier, entry_price * 0.15)
            tp_dist = atr * self.atr_tp_multiplier
        else:
            stop_dist = entry_price * self.stop_loss_pct
            tp_dist = entry_price * self.take_profit_pct

        if side_norm in ("long", "buy"):
            sl = max(entry_price - stop_dist, entry_price * 0.01)
            tp = entry_price + tp_dist
            trail = sl if self.trailing_stop_pct > 0 else None
        elif side_norm in ("short", "sell"):
            sl = entry_price + stop_dist
            tp = max(entry_price - tp_dist, entry_price * 0.01)
            trail = sl if self.trailing_stop_pct > 0 else None
        else:
            raise ValueError(f"Unknown position side: {side}")

        return StopLevels(stop_loss=sl, take_profit=tp, trailing_stop=trail)

    def update_trailing_stop(
        self,
        side: str,
        entry_price: float,
        current_price: float,
        current_stop: float,
    ) -> float:
        """Ratchet trailing stop in the profitable direction; never widen risk."""
        if self.trailing_stop_pct <= 0:
            return current_stop

        side_norm = side.lower()
        if side_norm in ("long", "buy"):
            if current_price > entry_price:
                candidate = current_price * (1.0 - self.trailing_stop_pct)
                return max(current_stop, candidate)
            return current_stop

        if side_norm in ("short", "sell"):
            if current_price < entry_price:
                candidate = current_price * (1.0 + self.trailing_stop_pct)
                return min(current_stop, candidate)
            return current_stop

        return current_stop

    @staticmethod
    def check_exit_trigger(
        side: str,
        bar_high: float,
        bar_low: float,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[str | None, float | None]:
        """Evaluate whether a candle triggered stop-loss or take-profit.

        Conservative fill rule: if both stop-loss and take-profit lie inside the same bar,
        stop-loss is evaluated first to prevent optimistic backtest bias.
        """
        side_norm = side.lower()
        if side_norm in ("long", "buy"):
            if bar_low <= stop_loss:
                return "stop_loss", stop_loss
            if bar_high >= take_profit:
                return "take_profit", take_profit
        elif side_norm in ("short", "sell"):
            if bar_high >= stop_loss:
                return "stop_loss", stop_loss
            if bar_low <= take_profit:
                return "take_profit", take_profit
        return None, None
