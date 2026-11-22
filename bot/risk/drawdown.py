"""Drawdown, daily loss, and consecutive-loss circuit breaker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass
class DrawdownStatus:
    can_trade: bool
    is_halted: bool
    halt_reason: str
    peak_equity: float
    current_equity: float
    drawdown_pct: float
    daily_loss_pct: float
    consecutive_losses: int


class DrawdownGuard:
    """Enforces account-level capital preservation limits."""

    def __init__(
        self,
        initial_equity: float,
        max_drawdown_pct: float = 0.10,
        max_daily_loss_pct: float = 0.03,
        max_consecutive_losses: int = 4,
    ) -> None:
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self.peak_equity = float(initial_equity)
        self.current_equity = float(initial_equity)
        self.daily_start_equity = float(initial_equity)
        self.current_day: date = datetime.now(timezone.utc).date()

        self.max_drawdown_pct = max_drawdown_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses

        self.consecutive_losses = 0
        self.is_halted = False
        self.halt_reason = ""

    def update_equity(
        self, equity: float, timestamp: datetime | None = None
    ) -> DrawdownStatus:
        """Update current equity and trip circuit breakers if thresholds are breached."""
        now_day = (timestamp or datetime.now(timezone.utc)).date()
        if now_day != self.current_day:
            self.current_day = now_day
            self.daily_start_equity = float(equity)
            # Daily loss halts automatically clear on a new UTC trading day
            if self.is_halted and self.halt_reason.startswith("Daily loss limit"):
                self.is_halted = False
                self.halt_reason = ""

        self.current_equity = float(equity)
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        dd = self.drawdown_pct
        daily_loss = self.daily_loss_pct

        if dd >= self.max_drawdown_pct:
            self.is_halted = True
            self.halt_reason = (
                f"Max drawdown breached ({dd * 100:.2f}% >= {self.max_drawdown_pct * 100:.2f}%)"
            )
        elif daily_loss >= self.max_daily_loss_pct:
            self.is_halted = True
            self.halt_reason = (
                f"Daily loss limit breached "
                f"({daily_loss * 100:.2f}% >= {self.max_daily_loss_pct * 100:.2f}%)"
            )

        return self.status()

    def record_trade_result(self, realized_pnl: float) -> DrawdownStatus:
        """Track consecutive losing trades to halt during adverse market regimes."""
        if realized_pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.is_halted = True
                self.halt_reason = (
                    f"Consecutive loss limit reached ({self.consecutive_losses} losses in a row)"
                )
        elif realized_pnl > 0:
            self.consecutive_losses = 0
        return self.status()

    def reset_halt(self, new_equity: float | None = None) -> None:
        """Manually clear a circuit breaker after operator review."""
        self.is_halted = False
        self.halt_reason = ""
        self.consecutive_losses = 0
        if new_equity is not None and new_equity > 0:
            self.current_equity = float(new_equity)
            self.peak_equity = float(new_equity)
            self.daily_start_equity = float(new_equity)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)

    @property
    def daily_loss_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return max(0.0, (self.daily_start_equity - self.current_equity) / self.daily_start_equity)

    def status(self) -> DrawdownStatus:
        return DrawdownStatus(
            can_trade=not self.is_halted,
            is_halted=self.is_halted,
            halt_reason=self.halt_reason,
            peak_equity=self.peak_equity,
            current_equity=self.current_equity,
            drawdown_pct=self.drawdown_pct,
            daily_loss_pct=self.daily_loss_pct,
            consecutive_losses=self.consecutive_losses,
        )
