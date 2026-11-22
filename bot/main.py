"""Main TradingBot runtime orchestrator and CLI entry point."""

from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import datetime, timezone
from typing import Any

from bot.backtesting.engine import BacktestEngine
from bot.config import Settings, get_settings
from bot.exchange.client import BinanceExchangeClient
from bot.exchange.market_data import MarketDataProvider
from bot.execution.orders import OrderExecutor
from bot.execution.portfolio import Portfolio, TradeFill
from bot.monitoring.alerts import AlertManager
from bot.monitoring.logger import get_logger, setup_logging
from bot.risk.drawdown import DrawdownGuard
from bot.risk.position_sizing import PositionSizer
from bot.risk.stop_loss import StopLossManager
from bot.strategies.signals import SignalAction, TradingSignal, create_strategy
from database.models import (
    BotState,
    EquitySnapshot,
    PositionRecord,
    SignalRecord,
    TradeRecord,
    get_session_factory,
    init_db,
)

logger = get_logger("main")


class TradingBot:
    """Autonomous multi-symbol trading engine with risk guards and DB state sync."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        setup_logging(level=self.settings.log_level, log_format=self.settings.log_format)

        init_db(self.settings.database_url)
        self.session_factory = get_session_factory(self.settings.database_url)

        self.exchange = BinanceExchangeClient(self.settings)
        self.market_data = MarketDataProvider(
            exchange_client=self.exchange,
            redis_url=self.settings.redis_url,
        )
        self.alerts = AlertManager(
            telegram_bot_token=self.settings.telegram_bot_token,
            telegram_chat_id=self.settings.telegram_chat_id,
            discord_webhook_url=self.settings.discord_webhook_url,
        )

        self.portfolio = Portfolio(initial_capital=self.settings.initial_capital)
        self.executor = OrderExecutor(
            settings=self.settings,
            portfolio=self.portfolio,
            exchange_client=self.exchange,
            alerts=self.alerts,
        )
        self.strategy = create_strategy(self.settings.strategy_name, self.settings)
        self.sizer = PositionSizer(
            risk_per_trade_pct=self.settings.risk_per_trade_pct,
            max_position_pct=self.settings.max_position_pct,
        )
        self.stop_manager = StopLossManager(
            stop_loss_pct=self.settings.stop_loss_pct,
            take_profit_pct=self.settings.take_profit_pct,
            trailing_stop_pct=self.settings.trailing_stop_pct,
            use_atr_stops=self.settings.use_atr_stops,
            atr_stop_multiplier=self.settings.atr_stop_multiplier,
            atr_tp_multiplier=self.settings.atr_tp_multiplier,
        )
        self.drawdown_guard = DrawdownGuard(
            initial_equity=self.settings.initial_capital,
            max_drawdown_pct=self.settings.max_drawdown_pct,
            max_daily_loss_pct=self.settings.max_daily_loss_pct,
            max_consecutive_losses=self.settings.max_consecutive_losses,
        )
        self._running = False
        self._sync_bot_state(is_running=False)

    def _sync_bot_state(self, is_running: bool | None = None) -> BotState:
        with self.session_factory() as db:
            state = db.get(BotState, 1)
            if state is None:
                state = BotState(
                    id=1,
                    is_running=bool(is_running),
                    is_halted=self.drawdown_guard.is_halted,
                    halt_reason=self.drawdown_guard.halt_reason,
                    mode=self.settings.trading_mode,
                    strategy=self.strategy.name,
                    symbols=",".join(self.settings.symbols_list),
                    timeframe=self.settings.timeframe,
                    equity=self.portfolio.equity,
                    cash=self.portfolio.cash,
                    peak_equity=self.drawdown_guard.peak_equity,
                )
                db.add(state)
            else:
                if is_running is not None:
                    state.is_running = is_running
                state.is_halted = self.drawdown_guard.is_halted
                state.halt_reason = self.drawdown_guard.halt_reason
                state.mode = self.settings.trading_mode
                state.strategy = self.strategy.name
                state.symbols = ",".join(self.settings.symbols_list)
                state.timeframe = self.settings.timeframe
                state.equity = self.portfolio.equity
                state.cash = self.portfolio.cash
                state.peak_equity = self.drawdown_guard.peak_equity
                state.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(state)
            return state

    def _persist_trade(self, fill: TradeFill) -> None:
        with self.session_factory() as db:
            db.add(
                TradeRecord(
                    order_id=fill.order_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    action=fill.action,
                    quantity=fill.quantity,
                    price=fill.price,
                    fee=fill.fee,
                    realized_pnl=fill.realized_pnl,
                    pnl_pct=fill.pnl_pct * 100.0,
                    strategy=fill.strategy,
                    mode=fill.mode,
                    reason=fill.reason[:255],
                    created_at=fill.timestamp,
                )
            )
            db.commit()

    def _persist_signal(self, sig: TradingSignal) -> None:
        with self.session_factory() as db:
            db.add(
                SignalRecord(
                    symbol=sig.symbol,
                    strategy=sig.strategy,
                    action=sig.action.value,
                    confidence=sig.confidence,
                    price=sig.price,
                    stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit,
                    reason=sig.reason,
                    metadata_json=sig.metadata,
                    created_at=sig.timestamp,
                )
            )
            db.commit()

    def _sync_positions_and_equity(self) -> None:
        with self.session_factory() as db:
            # Synchronize active positions table
            db.query(PositionRecord).delete()
            for pos in self.portfolio.positions.values():
                db.add(
                    PositionRecord(
                        symbol=pos.symbol,
                        side=pos.side,
                        quantity=pos.quantity,
                        entry_price=pos.entry_price,
                        current_price=pos.current_price,
                        stop_loss=pos.effective_stop,
                        take_profit=pos.take_profit,
                        trailing_stop=pos.trailing_stop,
                        unrealized_pnl=pos.unrealized_pnl,
                        strategy=pos.strategy,
                        opened_at=pos.opened_at,
                    )
                )

            db.add(
                EquitySnapshot(
                    equity=self.portfolio.equity,
                    cash=self.portfolio.cash,
                    unrealized_pnl=self.portfolio.unrealized_pnl,
                    drawdown_pct=self.drawdown_guard.drawdown_pct * 100.0,
                    open_positions=len(self.portfolio.positions),
                    mode=self.settings.trading_mode,
                )
            )
            db.commit()

    def run_cycle(self) -> dict[str, Any]:
        """Run one complete market evaluation and execution cycle across all symbols."""
        cycle_signals: list[dict[str, Any]] = []
        executed_trades: list[dict[str, Any]] = []

        for symbol in self.settings.symbols_list:
            try:
                df = self.market_data.get_ohlcv(
                    symbol=symbol,
                    timeframe=self.settings.timeframe,
                    limit=260,
                )
                latest_bar = df.iloc[-1]
                bar_high = float(latest_bar["high"])
                bar_low = float(latest_bar["low"])
                bar_close = float(latest_bar["close"])

                # 1. Manage open position stops & trailing stops
                if self.portfolio.has_position(symbol):
                    pos = self.portfolio.positions[symbol]
                    trigger, trigger_price = self.stop_manager.check_exit_trigger(
                        side=pos.side,
                        bar_high=bar_high,
                        bar_low=bar_low,
                        stop_loss=pos.effective_stop,
                        take_profit=pos.take_profit,
                    )
                    if trigger and trigger_price is not None:
                        res = self.executor.execute_exit(
                            symbol=symbol, reference_price=trigger_price, reason=trigger
                        )
                        if res.success and res.fill is not None:
                            self._persist_trade(res.fill)
                            executed_trades.append(res.fill.to_dict())
                            self.drawdown_guard.record_trade_result(res.fill.realized_pnl)
                    else:
                        self.portfolio.update_price(symbol, bar_close)
                        pos.trailing_stop = self.stop_manager.update_trailing_stop(
                            side=pos.side,
                            entry_price=pos.entry_price,
                            current_price=bar_close,
                            current_stop=pos.effective_stop,
                        )

                # 2. Generate strategy signal
                sig = self.strategy.generate_signal(df, symbol)
                if sig.action in (SignalAction.BUY, SignalAction.SELL):
                    side_for_stops = "long" if sig.action == SignalAction.BUY else "short"
                    preview_stops = self.stop_manager.compute_levels(
                        entry_price=sig.price, side=side_for_stops, atr=sig.atr
                    )
                    sig.stop_loss = preview_stops.stop_loss
                    sig.take_profit = preview_stops.take_profit

                self._persist_signal(sig)
                cycle_signals.append(sig.to_dict())

                # 3. Signal reversal exit
                if self.portfolio.has_position(symbol):
                    pos = self.portfolio.positions[symbol]
                    reverse = (pos.side == "long" and sig.action == SignalAction.SELL) or (
                        pos.side == "short" and sig.action == SignalAction.BUY
                    )
                    if reverse:
                        res = self.executor.execute_exit(
                            symbol=symbol,
                            reference_price=bar_close,
                            reason=f"signal_reversal: {sig.reason}",
                        )
                        if res.success and res.fill is not None:
                            self._persist_trade(res.fill)
                            executed_trades.append(res.fill.to_dict())
                            self.drawdown_guard.record_trade_result(res.fill.realized_pnl)

                # 4. Risk-gated new entry
                was_halted = self.drawdown_guard.is_halted
                dd_status = self.drawdown_guard.update_equity(self.portfolio.equity)
                if dd_status.is_halted and not was_halted:
                    logger.critical("RISK HALT TRIGGERED: %s", dd_status.halt_reason)
                    self.alerts.notify_risk_halt(
                        reason=dd_status.halt_reason,
                        equity=dd_status.current_equity,
                        drawdown_pct=dd_status.drawdown_pct,
                    )

                can_open_more = len(self.portfolio.positions) < self.settings.max_open_positions
                if dd_status.can_trade and can_open_more and not self.portfolio.has_position(symbol):
                    if sig.action == SignalAction.BUY:
                        stops = self.stop_manager.compute_levels(
                            entry_price=bar_close, side="long", atr=sig.atr
                        )
                        qty = self.sizer.calculate_quantity(
                            equity=self.portfolio.equity,
                            available_cash=self.portfolio.cash,
                            entry_price=bar_close,
                            stop_loss_price=stops.stop_loss,
                            confidence=sig.confidence,
                        )
                        if qty > 0:
                            res = self.executor.execute_entry(
                                symbol=symbol,
                                side="long",
                                quantity=qty,
                                reference_price=bar_close,
                                stops=stops,
                                strategy=self.strategy.name,
                                reason=sig.reason,
                            )
                            if res.success and res.fill is not None:
                                self._persist_trade(res.fill)
                                executed_trades.append(res.fill.to_dict())
                    elif (
                        sig.action == SignalAction.SELL
                        and self.settings.market_type == "futures"
                    ):
                        stops = self.stop_manager.compute_levels(
                            entry_price=bar_close, side="short", atr=sig.atr
                        )
                        qty = self.sizer.calculate_quantity(
                            equity=self.portfolio.equity,
                            available_cash=self.portfolio.cash,
                            entry_price=bar_close,
                            stop_loss_price=stops.stop_loss,
                            confidence=sig.confidence,
                        )
                        if qty > 0:
                            res = self.executor.execute_entry(
                                symbol=symbol,
                                side="short",
                                quantity=qty,
                                reference_price=bar_close,
                                stops=stops,
                                strategy=self.strategy.name,
                                reason=sig.reason,
                            )
                            if res.success and res.fill is not None:
                                self._persist_trade(res.fill)
                                executed_trades.append(res.fill.to_dict())

            except Exception as exc:
                logger.exception("Error processing symbol %s: %s", symbol, exc)

        self.portfolio.snapshot()
        self._sync_positions_and_equity()
        self._sync_bot_state(is_running=self._running)

        return {
            "equity": round(self.portfolio.equity, 2),
            "signals": cycle_signals,
            "trades": executed_trades,
            "drawdown_pct": round(self.drawdown_guard.drawdown_pct * 100.0, 2),
            "halted": self.drawdown_guard.is_halted,
        }

    def start(self, run_once: bool = False) -> None:
        """Start the main trading loop."""
        self._running = True
        self._sync_bot_state(is_running=True)
        logger.info(
            "Starting TradingBot | mode=%s | market=%s | strategy=%s | symbols=%s | tf=%s",
            self.settings.trading_mode.upper(),
            self.settings.market_type.upper(),
            self.strategy.name,
            ",".join(self.settings.symbols_list),
            self.settings.timeframe,
        )

        def _handle_stop(signum: int, _frame: Any) -> None:
            logger.info("Received signal %s; shutting down gracefully...", signum)
            self._running = False

        try:
            signal.signal(signal.SIGINT, _handle_stop)
            signal.signal(signal.SIGTERM, _handle_stop)
        except ValueError:
            pass

        try:
            while self._running:
                summary = self.run_cycle()
                logger.info(
                    "Cycle complete | Equity=$%.2f | DD=%.2f%% | Trades=%d | Halted=%s",
                    summary["equity"],
                    summary["drawdown_pct"],
                    len(summary["trades"]),
                    summary["halted"],
                )
                if run_once:
                    break
                time.sleep(self.settings.poll_interval_seconds)
        finally:
            self._running = False
            self._sync_bot_state(is_running=False)
            logger.info("TradingBot stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profitable Binance Trading Bot")
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run a historical backtest and print performance metrics",
    )
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair (e.g. BTC/USDT)")
    parser.add_argument("--timeframe", default="15m", help="Candle timeframe (e.g. 15m, 1h)")
    parser.add_argument(
        "--strategy",
        default=None,
        choices=["trend_following", "moving_average", "composite"],
        help="Strategy override",
    )
    parser.add_argument("--bars", type=int, default=500, help="Number of candles for backtest")
    parser.add_argument("--once", action="store_true", help="Run a single trading cycle and exit")
    args = parser.parse_args()

    settings = get_settings()
    if args.strategy:
        settings = settings.model_copy(update={"strategy_name": args.strategy})

    if args.backtest:
        setup_logging(level=settings.log_level, log_format=settings.log_format)
        client = BinanceExchangeClient(settings)
        md = MarketDataProvider(exchange_client=client, redis_url=settings.redis_url)
        df = md.get_ohlcv(symbol=args.symbol, timeframe=args.timeframe, limit=args.bars)
        engine = BacktestEngine(settings=settings)
        result = engine.run(df=df, symbol=args.symbol, timeframe=args.timeframe)
        print(json.dumps(result.metrics.to_dict(), indent=2))
        return

    bot = TradingBot(settings=settings)
    bot.start(run_once=args.once)


if __name__ == "__main__":
    main()
