"""Binance exchange client powered by ccxt with safe paper/testnet/live modes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from bot.config import Settings
from bot.monitoring.logger import get_logger

logger = get_logger("exchange.client")


class BinanceExchangeClient:
    """Thin, fault-tolerant wrapper around ccxt Binance (Spot & USDT-M Futures)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mode = settings.trading_mode
        self.market_type = settings.market_type
        self._exchange: Any = None
        self._init_exchange()

    def _init_exchange(self) -> None:
        try:
            import ccxt
        except ImportError:
            logger.warning("ccxt is not installed; operating in offline paper mode.")
            self._exchange = None
            return

        exchange_cls = (
            ccxt.binanceusdm if self.market_type == "futures" else ccxt.binance
        )
        config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {
                "defaultType": "future" if self.market_type == "futures" else "spot",
                "adjustForTimeDifference": True,
            },
        }

        if self.mode in ("testnet", "live"):
            if not self.settings.active_api_key or not self.settings.active_api_secret:
                raise ValueError(
                    f"Binance API credentials are required for TRADING_MODE={self.mode}. "
                    "Set BINANCE_API_KEY/SECRET (or BINANCE_TESTNET_API_KEY/SECRET) in .env."
                )
            config["apiKey"] = self.settings.active_api_key
            config["secret"] = self.settings.active_api_secret

        self._exchange = exchange_cls(config)

        if self.mode == "testnet":
            self._exchange.set_sandbox_mode(True)
            logger.info("Connected to Binance %s TESTNET", self.market_type.upper())
        elif self.mode == "live":
            logger.warning("Connected to Binance %s LIVE trading!", self.market_type.upper())
        else:
            logger.info("Initialized Binance client in PAPER mode (public market data only)")

    @property
    def is_live(self) -> bool:
        return self.mode in ("testnet", "live")

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "15m", limit: int = 300
    ) -> list[list[float]]:
        """Fetch OHLCV candles from Binance public API."""
        if self._exchange is None:
            raise RuntimeError("ccxt exchange client is unavailable")
        return self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_ticker_price(self, symbol: str) -> float:
        """Fetch latest traded price for a symbol."""
        if self._exchange is None:
            raise RuntimeError("ccxt exchange client is unavailable")
        ticker = self._exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    def fetch_balance(self, quote_currency: str = "USDT") -> dict[str, float]:
        """Return free/used/total balances for the quote currency."""
        if not self.is_live or self._exchange is None:
            return {
                "free": self.settings.initial_capital,
                "used": 0.0,
                "total": self.settings.initial_capital,
            }
        balance = self._exchange.fetch_balance()
        asset = balance.get(quote_currency, {})
        return {
            "free": float(asset.get("free", 0.0)),
            "used": float(asset.get("used", 0.0)),
            "total": float(asset.get("total", 0.0)),
        }

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set futures leverage on Binance USDT-M when operating in futures mode."""
        if self.market_type != "futures" or not self.is_live or self._exchange is None:
            return
        try:
            self._exchange.set_leverage(leverage, symbol)
            logger.info("Set leverage %dx for %s", leverage, symbol)
        except Exception as exc:
            logger.warning("Failed to set leverage for %s: %s", symbol, exc)

    def create_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit an order on Binance, or return a simulated receipt in paper mode."""
        side_lower = side.lower()
        if side_lower not in ("buy", "sell"):
            raise ValueError(f"Unsupported order side: {side}")
        if quantity <= 0:
            raise ValueError("Order quantity must be positive")

        if not self.is_live:
            fill_price = float(price) if price is not None else self.fetch_ticker_price(symbol)
            return {
                "id": f"paper-{uuid.uuid4().hex[:12]}",
                "symbol": symbol,
                "side": side_lower,
                "type": order_type,
                "amount": float(quantity),
                "filled": float(quantity),
                "average": fill_price,
                "price": fill_price,
                "status": "closed",
                "fee": {"cost": fill_price * quantity * self.settings.fee_rate, "currency": "USDT"},
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "mode": "paper",
            }

        if self._exchange is None:
            raise RuntimeError("Cannot submit live order: ccxt exchange not initialized")

        if self.market_type == "futures":
            self.set_leverage(symbol, self.settings.default_leverage)

        logger.info(
            "Submitting %s %s order: %s qty=%.6f price=%s",
            self.mode.upper(),
            order_type.upper(),
            symbol,
            quantity,
            price,
        )
        return self._exchange.create_order(
            symbol=symbol,
            type=order_type,
            side=side_lower,
            amount=quantity,
            price=price,
            params=params or {},
        )

    def cancel_all_orders(self, symbol: str) -> None:
        """Cancel open orders for a symbol on live/testnet exchanges."""
        if not self.is_live or self._exchange is None:
            return
        try:
            self._exchange.cancel_all_orders(symbol)
        except Exception as exc:
            logger.warning("Failed to cancel orders for %s: %s", symbol, exc)
