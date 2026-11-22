"""Order execution engine coordinating Binance API calls, slippage, fees, and Portfolio."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.config import Settings
from bot.exchange.client import BinanceExchangeClient
from bot.execution.portfolio import Portfolio, TradeFill
from bot.monitoring.alerts import AlertManager
from bot.monitoring.logger import get_logger
from bot.risk.stop_loss import StopLevels

logger = get_logger("execution.orders")


@dataclass
class OrderResult:
    success: bool
    fill: TradeFill | None = None
    error: str = ""


class OrderExecutor:
    """Routes validated trade intents to paper simulator or Binance testnet/live."""

    def __init__(
        self,
        settings: Settings,
        portfolio: Portfolio,
        exchange_client: BinanceExchangeClient | None = None,
        alerts: AlertManager | None = None,
    ) -> None:
        self.settings = settings
        self.portfolio = portfolio
        self.exchange_client = exchange_client
        self.alerts = alerts

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = self.settings.slippage_pct
        if side.lower() == "buy":
            return price * (1.0 + slip)
        return price * (1.0 - slip)

    def execute_entry(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        stops: StopLevels,
        strategy: str = "composite",
        reason: str = "",
        timestamp: datetime | None = None,
    ) -> OrderResult:
        """Open a new position with slippage/fee accounting and optional live order routing."""
        if quantity <= 0 or reference_price <= 0:
            return OrderResult(success=False, error="Invalid quantity or price")
        if self.portfolio.has_position(symbol):
            return OrderResult(success=False, error=f"Position already exists for {symbol}")

        order_side = "buy" if side.lower() in ("long", "buy") else "sell"
        ts = timestamp or datetime.now(timezone.utc)

        try:
            if self.exchange_client is not None and self.exchange_client.is_live:
                receipt = self.exchange_client.create_order(
                    symbol=symbol,
                    side=order_side,
                    quantity=quantity,
                    order_type="market",
                )
                order_id = str(receipt.get("id") or f"live-{uuid.uuid4().hex[:12]}")
                fill_price = float(
                    receipt.get("average") or receipt.get("price") or reference_price
                )
                filled_qty = float(receipt.get("filled") or receipt.get("amount") or quantity)
                fee_info = receipt.get("fee") or {}
                fee = float(
                    fee_info.get("cost")
                    if fee_info.get("cost") is not None
                    else fill_price * filled_qty * self.settings.fee_rate
                )
            else:
                order_id = f"paper-{uuid.uuid4().hex[:12]}"
                fill_price = self._apply_slippage(reference_price, order_side)
                filled_qty = quantity
                fee = fill_price * filled_qty * self.settings.fee_rate

            # Guard against slippage pushing cost slightly above cash
            max_affordable = (self.portfolio.cash * 0.999) / (
                fill_price * (1.0 + self.settings.fee_rate)
            )
            if filled_qty > max_affordable:
                filled_qty = max_affordable
                fee = fill_price * filled_qty * self.settings.fee_rate
            if filled_qty <= 0:
                return OrderResult(success=False, error="Insufficient cash after slippage")

            _, fill = self.portfolio.open_position(
                order_id=order_id,
                symbol=symbol,
                side="long" if order_side == "buy" else "short",
                quantity=filled_qty,
                fill_price=fill_price,
                fee=fee,
                stop_loss=stops.stop_loss,
                take_profit=stops.take_profit,
                trailing_stop=stops.trailing_stop,
                strategy=strategy,
                mode=self.settings.trading_mode,
                reason=reason,
                timestamp=ts,
            )

            logger.info(
                "ENTRY %s %s qty=%.6f @ $%.4f | SL=$%.4f TP=$%.4f | %s",
                order_side.upper(),
                symbol,
                filled_qty,
                fill_price,
                stops.stop_loss,
                stops.take_profit,
                reason,
            )
            if self.alerts:
                self.alerts.notify_trade(
                    symbol=symbol,
                    side=order_side,
                    quantity=filled_qty,
                    price=fill_price,
                    reason=reason,
                )
            return OrderResult(success=True, fill=fill)
        except Exception as exc:
            logger.error("Entry execution failed for %s: %s", symbol, exc)
            return OrderResult(success=False, error=str(exc))

    def execute_exit(
        self,
        symbol: str,
        reference_price: float,
        reason: str = "signal_exit",
        timestamp: datetime | None = None,
    ) -> OrderResult:
        """Close an active position and realize PnL."""
        if not self.portfolio.has_position(symbol):
            return OrderResult(success=False, error=f"No open position for {symbol}")

        pos = self.portfolio.positions[symbol]
        close_side = "sell" if pos.side == "long" else "buy"
        ts = timestamp or datetime.now(timezone.utc)

        try:
            if self.exchange_client is not None and self.exchange_client.is_live:
                receipt = self.exchange_client.create_order(
                    symbol=symbol,
                    side=close_side,
                    quantity=pos.quantity,
                    order_type="market",
                )
                order_id = str(receipt.get("id") or f"live-{uuid.uuid4().hex[:12]}")
                fill_price = float(
                    receipt.get("average") or receipt.get("price") or reference_price
                )
                fee_info = receipt.get("fee") or {}
                fee = float(
                    fee_info.get("cost")
                    if fee_info.get("cost") is not None
                    else fill_price * pos.quantity * self.settings.fee_rate
                )
            else:
                order_id = f"paper-{uuid.uuid4().hex[:12]}"
                fill_price = self._apply_slippage(reference_price, close_side)
                fee = fill_price * pos.quantity * self.settings.fee_rate

            fill = self.portfolio.close_position(
                order_id=order_id,
                symbol=symbol,
                fill_price=fill_price,
                fee=fee,
                mode=self.settings.trading_mode,
                reason=reason,
                timestamp=ts,
            )

            logger.info(
                "EXIT %s %s qty=%.6f @ $%.4f | PnL=$%+.2f (%.2f%%) | %s",
                close_side.upper(),
                symbol,
                fill.quantity,
                fill.price,
                fill.realized_pnl,
                fill.pnl_pct * 100.0,
                reason,
            )
            if self.alerts:
                self.alerts.notify_trade(
                    symbol=symbol,
                    side=close_side,
                    quantity=fill.quantity,
                    price=fill.price,
                    pnl=fill.realized_pnl,
                    reason=reason,
                )
            return OrderResult(success=True, fill=fill)
        except Exception as exc:
            logger.error("Exit execution failed for %s: %s", symbol, exc)
            return OrderResult(success=False, error=str(exc))
