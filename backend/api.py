"""FastAPI application entry point and shared runtime manager."""

from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.config import Settings, get_settings
from bot.main import TradingBot
from bot.monitoring.logger import get_logger, setup_logging
from database.models import init_db

logger = get_logger("backend.api")


class BotRuntimeManager:
    """Thread-safe controller allowing the API to start, stop, and step a TradingBot."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._bot: TradingBot | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def get_or_create_bot(self) -> TradingBot:
        with self._lock:
            if self._bot is None:
                self._bot = TradingBot(settings=self.settings)
            return self._bot

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> dict[str, Any]:
        bot = self.get_or_create_bot()
        with self._lock:
            if self.is_running:
                return {"status": "already_running", "mode": bot.settings.trading_mode}

            self._stop_event.clear()
            bot._running = True
            bot._sync_bot_state(is_running=True)

            def _loop() -> None:
                logger.info("Background bot worker started via API")
                try:
                    while not self._stop_event.is_set():
                        bot.run_cycle()
                        self._stop_event.wait(timeout=bot.settings.poll_interval_seconds)
                finally:
                    bot._running = False
                    bot._sync_bot_state(is_running=False)
                    logger.info("Background bot worker stopped")

            self._thread = threading.Thread(target=_loop, name="trading-bot-worker", daemon=True)
            self._thread.start()
            return {"status": "started", "mode": bot.settings.trading_mode}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_event.set()
            if self._bot is not None:
                self._bot._running = False
                self._bot._sync_bot_state(is_running=False)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        return {"status": "stopped"}

    def run_single_cycle(self) -> dict[str, Any]:
        bot = self.get_or_create_bot()
        return bot.run_cycle()

    def reset_halt(self) -> dict[str, Any]:
        bot = self.get_or_create_bot()
        bot.drawdown_guard.reset_halt(new_equity=bot.portfolio.equity)
        bot._sync_bot_state(is_running=self.is_running)
        return {"status": "reset", "equity": round(bot.portfolio.equity, 2)}

    def update_config(
        self,
        strategy: str | None = None,
        timeframe: str | None = None,
        symbols: list[str] | None = None,
        risk_per_trade_pct: float | None = None,
    ) -> dict[str, Any]:
        from bot.strategies.signals import create_strategy

        bot = self.get_or_create_bot()
        updates: dict[str, Any] = {}
        if strategy is not None:
            updates["strategy_name"] = strategy
        if timeframe is not None:
            updates["timeframe"] = timeframe
        if symbols is not None and len(symbols) > 0:
            updates["trading_symbols"] = ",".join(s.strip().upper() for s in symbols if s.strip())
        if risk_per_trade_pct is not None:
            updates["risk_per_trade_pct"] = risk_per_trade_pct

        if updates:
            bot.settings = bot.settings.model_copy(update=updates)
            self.settings = bot.settings
            if strategy is not None:
                bot.strategy = create_strategy(strategy, bot.settings)
            if risk_per_trade_pct is not None:
                bot.sizer.risk_per_trade_pct = risk_per_trade_pct
            bot._sync_bot_state(is_running=self.is_running)

        return {
            "strategy": bot.strategy.name,
            "timeframe": bot.settings.timeframe,
            "symbols": bot.settings.symbols_list,
            "risk_per_trade_pct": bot.settings.risk_per_trade_pct,
        }


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    setup_logging(level=cfg.log_level, log_format=cfg.log_format)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_db(cfg.database_url)
        application.state.settings = cfg
        application.state.runtime = BotRuntimeManager(cfg)
        logger.info("FastAPI management backend initialized (mode=%s)", cfg.trading_mode)
        yield
        application.state.runtime.stop()

    application = FastAPI(
        title="Profitable Trading Bot API",
        description="Management, monitoring, and backtesting REST API for the Binance Trading Bot.",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Eagerly attach defaults so TestClient without lifespan still works cleanly
    application.state.settings = cfg
    application.state.runtime = BotRuntimeManager(cfg)
    init_db(cfg.database_url)

    from backend.routes import backtest, market, trades
    from backend.routes import bot as bot_routes

    application.include_router(bot_routes.router, prefix="/api/bot", tags=["Bot Control"])
    application.include_router(trades.router, prefix="/api", tags=["Portfolio & Trades"])
    application.include_router(backtest.router, prefix="/api/backtest", tags=["Backtesting"])
    application.include_router(market.router, prefix="/api/market", tags=["Market Data"])

    @application.get("/health", tags=["Health"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": cfg.trading_mode,
            "exchange": cfg.exchange_name,
            "market_type": cfg.market_type,
            "timestamp": int(time.time()),
        }

    return application


app = create_app()
