"""Portfolio state, position tracking, PnL accounting, and equity curve management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Position:
    """Represents an active open position."""

    symbol: str
    side: str  # "long" | "short"
    quantity: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    entry_fee: float = 0.0
    trailing_stop: float | None = None
    strategy: str = "composite"
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def notional_entry(self) -> float:
        return self.quantity * self.entry_price

    @property
    def unrealized_pnl(self) -> float:
        if self.side == "long":
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.notional_entry <= 0:
            return 0.0
        return self.unrealized_pnl / self.notional_entry

    @property
    def equity_value(self) -> float:
        if self.side == "long":
            return self.quantity * self.current_price
        return self.notional_entry + self.unrealized_pnl

    @property
    def effective_stop(self) -> float:
        if self.trailing_stop is None:
            return self.stop_loss
        if self.side == "long":
            return max(self.stop_loss, self.trailing_stop)
        return min(self.stop_loss, self.trailing_stop)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": round(self.quantity, 6),
            "entry_price": round(self.entry_price, 6),
            "current_price": round(self.current_price, 6),
            "stop_loss": round(self.effective_stop, 6),
            "take_profit": round(self.take_profit, 6),
            "trailing_stop": round(self.trailing_stop, 6) if self.trailing_stop else None,
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct * 100.0, 2),
            "strategy": self.strategy,
            "opened_at": self.opened_at.isoformat(),
        }


@dataclass
class TradeFill:
    """Immutable record of an executed fill."""

    order_id: str
    symbol: str
    side: str  # "buy" | "sell"
    action: str  # "entry" | "exit"
    quantity: float
    price: float
    fee: float
    realized_pnl: float = 0.0
    pnl_pct: float = 0.0
    strategy: str = "composite"
    mode: str = "paper"
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "action": self.action,
            "quantity": round(self.quantity, 6),
            "price": round(self.price, 6),
            "fee": round(self.fee, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "pnl_pct": round(self.pnl_pct * 100.0, 2),
            "strategy": self.strategy,
            "mode": self.mode,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


class Portfolio:
    """Tracks cash, open positions, realized/unrealized PnL, and equity history."""

    def __init__(self, initial_capital: float = 10000.0) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.initial_capital = float(initial_capital)
        self.cash = float(initial_capital)
        self.positions: dict[str, Position] = {}
        self.trades: list[TradeFill] = []
        self.equity_curve: list[dict[str, Any]] = []
        self.total_fees_paid: float = 0.0
        self.realized_pnl_total: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def equity(self) -> float:
        return self.cash + sum(p.equity_value for p in self.positions.values())

    @property
    def total_return_pct(self) -> float:
        return (self.equity - self.initial_capital) / self.initial_capital

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def open_position(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        fee: float,
        stop_loss: float,
        take_profit: float,
        trailing_stop: float | None = None,
        strategy: str = "composite",
        mode: str = "paper",
        reason: str = "",
        timestamp: datetime | None = None,
    ) -> tuple[Position, TradeFill]:
        if symbol in self.positions:
            raise ValueError(f"Position already open for {symbol}")
        if quantity <= 0 or fill_price <= 0:
            raise ValueError("quantity and fill_price must be positive")

        side_norm = "long" if side.lower() in ("long", "buy") else "short"
        notional = quantity * fill_price
        total_debit = notional + fee
        if total_debit > self.cash + 1e-6:
            raise ValueError(
                f"Insufficient cash: required ${total_debit:.2f}, available ${self.cash:.2f}"
            )

        ts = timestamp or datetime.now(timezone.utc)
        self.cash -= total_debit
        self.total_fees_paid += fee

        pos = Position(
            symbol=symbol,
            side=side_norm,
            quantity=quantity,
            entry_price=fill_price,
            current_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_fee=fee,
            trailing_stop=trailing_stop,
            strategy=strategy,
            opened_at=ts,
        )
        self.positions[symbol] = pos

        fill = TradeFill(
            order_id=order_id,
            symbol=symbol,
            side="buy" if side_norm == "long" else "sell",
            action="entry",
            quantity=quantity,
            price=fill_price,
            fee=fee,
            realized_pnl=0.0,
            pnl_pct=0.0,
            strategy=strategy,
            mode=mode,
            reason=reason,
            timestamp=ts,
        )
        self.trades.append(fill)
        return pos, fill

    def close_position(
        self,
        order_id: str,
        symbol: str,
        fill_price: float,
        fee: float,
        mode: str = "paper",
        reason: str = "",
        timestamp: datetime | None = None,
    ) -> TradeFill:
        if symbol not in self.positions:
            raise ValueError(f"No open position for {symbol}")

        pos = self.positions.pop(symbol)
        ts = timestamp or datetime.now(timezone.utc)

        if pos.side == "long":
            gross_pnl = (fill_price - pos.entry_price) * pos.quantity
            self.cash += pos.quantity * fill_price - fee
            close_side = "sell"
        else:
            gross_pnl = (pos.entry_price - fill_price) * pos.quantity
            self.cash += pos.notional_entry + gross_pnl - fee
            close_side = "buy"

        net_pnl = gross_pnl - pos.entry_fee - fee
        pnl_pct = net_pnl / pos.notional_entry if pos.notional_entry > 0 else 0.0

        self.total_fees_paid += fee
        self.realized_pnl_total += net_pnl

        fill = TradeFill(
            order_id=order_id,
            symbol=symbol,
            side=close_side,
            action="exit",
            quantity=pos.quantity,
            price=fill_price,
            fee=fee,
            realized_pnl=net_pnl,
            pnl_pct=pnl_pct,
            strategy=pos.strategy,
            mode=mode,
            reason=reason,
            timestamp=ts,
        )
        self.trades.append(fill)
        return fill

    def update_price(self, symbol: str, price: float) -> None:
        if symbol in self.positions and price > 0:
            self.positions[symbol].current_price = float(price)

    def snapshot(self, timestamp: datetime | None = None) -> dict[str, Any]:
        ts = timestamp or datetime.now(timezone.utc)
        snap = {
            "timestamp": ts.isoformat(),
            "equity": round(self.equity, 4),
            "cash": round(self.cash, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "open_positions": len(self.positions),
        }
        self.equity_curve.append(snap)
        return snap

    def summary(self) -> dict[str, Any]:
        closed = [t for t in self.trades if t.action == "exit"]
        wins = [t for t in closed if t.realized_pnl > 0]
        win_rate = (len(wins) / len(closed) * 100.0) if closed else 0.0
        return {
            "initial_capital": round(self.initial_capital, 2),
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl_total, 2),
            "total_return_pct": round(self.total_return_pct * 100.0, 2),
            "total_fees_paid": round(self.total_fees_paid, 4),
            "open_positions_count": len(self.positions),
            "closed_trades_count": len(closed),
            "win_rate_pct": round(win_rate, 2),
        }
