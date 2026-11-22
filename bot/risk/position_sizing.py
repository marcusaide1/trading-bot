"""Position sizing engine using fixed-fractional risk, exposure caps, and Kelly bounds."""

from __future__ import annotations

import math


class PositionSizer:
    """Computes risk-adjusted order quantities so no single stop-out blows up the account."""

    def __init__(
        self,
        risk_per_trade_pct: float = 0.01,
        max_position_pct: float = 0.25,
        min_notional: float = 10.0,
    ) -> None:
        if not 0 < risk_per_trade_pct <= 0.25:
            raise ValueError("risk_per_trade_pct must be in (0, 0.25]")
        if not 0 < max_position_pct <= 1.0:
            raise ValueError("max_position_pct must be in (0, 1.0]")
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.min_notional = min_notional

    def calculate_quantity(
        self,
        equity: float,
        available_cash: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: float = 1.0,
        precision: int = 6,
    ) -> float:
        """Calculate asset quantity constrained by risk-per-trade, max exposure, and cash.

        Args:
            equity: Total account equity (cash + open positions).
            available_cash: Free quote currency available for margin/spot purchase.
            entry_price: Expected execution price.
            stop_loss_price: Protective stop price.
            confidence: Strategy conviction scalar in [0.25, 1.0] to scale size dynamically.
            precision: Decimal rounding precision for exchange lot compliance.
        """
        if equity <= 0 or available_cash <= 0 or entry_price <= 0:
            return 0.0

        stop_distance = abs(entry_price - stop_loss_price)
        if stop_distance <= 0:
            return 0.0

        # Scale risk modestly by signal conviction (bounded between 50% and 100% of base risk)
        conviction_scalar = max(0.5, min(1.0, float(confidence)))
        risk_dollars = equity * self.risk_per_trade_pct * conviction_scalar

        # Fixed-fractional quantity: qty * stop_distance == risk_dollars
        risk_based_qty = risk_dollars / stop_distance

        # Cap by maximum notional allocation per position and available cash (leaving 1% fee buffer)
        max_notional = min(equity * self.max_position_pct, available_cash * 0.99)
        max_qty = max_notional / entry_price

        qty = min(risk_based_qty, max_qty)
        if qty * entry_price < self.min_notional:
            return 0.0

        factor = 10**precision
        return math.floor(qty * factor) / factor

    @staticmethod
    def fractional_kelly(
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.25,
        cap: float = 0.03,
    ) -> float:
        """Compute conservative quarter-Kelly risk fraction capped to prevent over-betting."""
        if avg_win <= 0 or avg_loss <= 0 or not 0.0 < win_rate < 1.0:
            return 0.0
        payoff_ratio = avg_win / avg_loss
        kelly = win_rate - ((1.0 - win_rate) / payoff_ratio)
        if kelly <= 0:
            return 0.0
        return min(kelly * fraction, cap)
