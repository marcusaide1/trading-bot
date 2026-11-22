"""Event-driven bar-by-bar backtesting engine with zero lookahead bias."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from bot.backtesting.performance import PerformanceMetrics, compute_performance_metrics
from bot.config import Settings
from bot.execution.orders import OrderExecutor
from bot.execution.portfolio import Portfolio
from bot.risk.drawdown import DrawdownGuard
from bot.risk.position_sizing import PositionSizer
from bot.risk.stop_loss import StopLossManager
from bot.strategies.signals import BaseStrategy, SignalAction, create_strategy


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    strategy: str
    metrics: PerformanceMetrics
    equity_curve: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    halted_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "metrics": self.metrics.to_dict(),
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "halted_reason": self.halted_reason,
        }


class BacktestEngine:
    """Replays historical OHLCV candles through the exact live strategy and risk stack."""

    def __init__(
        self,
        settings: Settings | None = None,
        strategy: BaseStrategy | None = None,
    ) -> None:
        self.settings = (settings or Settings()).model_copy(update={"trading_mode": "paper"})
        self.strategy = strategy or create_strategy(self.settings.strategy_name, self.settings)

    def run(
        self,
        df: pd.DataFrame,
        symbol: str = "BTC/USDT",
        timeframe: str = "15m",
        initial_capital: float | None = None,
    ) -> BacktestResult:
        """Execute a realistic bar-by-bar simulation with fees, slippage, and stops."""
        if df.empty or len(df) <= self.strategy.min_bars:
            raise ValueError(
                f"Need more than {self.strategy.min_bars} candles for {self.strategy.name} backtest"
            )

        capital = float(initial_capital or self.settings.initial_capital)
        portfolio = Portfolio(initial_capital=capital)
        executor = OrderExecutor(settings=self.settings, portfolio=portfolio)
        sizer = PositionSizer(
            risk_per_trade_pct=self.settings.risk_per_trade_pct,
            max_position_pct=self.settings.max_position_pct,
        )
        stop_manager = StopLossManager(
            stop_loss_pct=self.settings.stop_loss_pct,
            take_profit_pct=self.settings.take_profit_pct,
            trailing_stop_pct=self.settings.trailing_stop_pct,
            use_atr_stops=self.settings.use_atr_stops,
            atr_stop_multiplier=self.settings.atr_stop_multiplier,
            atr_tp_multiplier=self.settings.atr_tp_multiplier,
        )
        drawdown_guard = DrawdownGuard(
            initial_equity=capital,
            max_drawdown_pct=self.settings.max_drawdown_pct,
            max_daily_loss_pct=self.settings.max_daily_loss_pct,
            max_consecutive_losses=self.settings.max_consecutive_losses,
        )

        data = df.reset_index(drop=True)
        warmup = self.strategy.min_bars

        for i in range(warmup, len(data)):
            row = data.iloc[i]
            ts_raw = row["timestamp"] if "timestamp" in data.columns else datetime.now(timezone.utc)
            ts = ts_raw.to_pydatetime() if hasattr(ts_raw, "to_pydatetime") else ts_raw
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            bar_high = float(row["high"])
            bar_low = float(row["low"])
            bar_close = float(row["close"])

            # 1. Manage existing open position: check stops/targets first, then ratchet trailing stop
            if portfolio.has_position(symbol):
                pos = portfolio.positions[symbol]
                trigger, trigger_price = stop_manager.check_exit_trigger(
                    side=pos.side,
                    bar_high=bar_high,
                    bar_low=bar_low,
                    stop_loss=pos.effective_stop,
                    take_profit=pos.take_profit,
                )
                if trigger and trigger_price is not None:
                    res = executor.execute_exit(
                        symbol=symbol,
                        reference_price=trigger_price,
                        reason=trigger,
                        timestamp=ts,
                    )
                    if res.success and res.fill is not None:
                        drawdown_guard.record_trade_result(res.fill.realized_pnl)
                else:
                    portfolio.update_price(symbol, bar_close)
                    pos.trailing_stop = stop_manager.update_trailing_stop(
                        side=pos.side,
                        entry_price=pos.entry_price,
                        current_price=bar_close,
                        current_stop=pos.effective_stop,
                    )

            # 2. Evaluate strategy on strictly historical window up to bar i (no lookahead)
            window = data.iloc[max(0, i - 250) : i + 1]
            signal = self.strategy.generate_signal(window, symbol)

            # 3. Signal-based exit for open positions
            if portfolio.has_position(symbol):
                pos = portfolio.positions[symbol]
                should_exit = (pos.side == "long" and signal.action == SignalAction.SELL) or (
                    pos.side == "short" and signal.action == SignalAction.BUY
                )
                if should_exit:
                    res = executor.execute_exit(
                        symbol=symbol,
                        reference_price=bar_close,
                        reason=f"signal_reversal: {signal.reason}",
                        timestamp=ts,
                    )
                    if res.success and res.fill is not None:
                        drawdown_guard.record_trade_result(res.fill.realized_pnl)

            # 4. Update drawdown guard & evaluate new entries
            dd_status = drawdown_guard.update_equity(portfolio.equity, timestamp=ts)
            if dd_status.can_trade and not portfolio.has_position(symbol):
                if signal.action == SignalAction.BUY:
                    stops = stop_manager.compute_levels(
                        entry_price=bar_close, side="long", atr=signal.atr
                    )
                    qty = sizer.calculate_quantity(
                        equity=portfolio.equity,
                        available_cash=portfolio.cash,
                        entry_price=bar_close,
                        stop_loss_price=stops.stop_loss,
                        confidence=signal.confidence,
                    )
                    if qty > 0:
                        executor.execute_entry(
                            symbol=symbol,
                            side="long",
                            quantity=qty,
                            reference_price=bar_close,
                            stops=stops,
                            strategy=self.strategy.name,
                            reason=signal.reason,
                            timestamp=ts,
                        )
                elif (
                    signal.action == SignalAction.SELL
                    and self.settings.market_type == "futures"
                ):
                    stops = stop_manager.compute_levels(
                        entry_price=bar_close, side="short", atr=signal.atr
                    )
                    qty = sizer.calculate_quantity(
                        equity=portfolio.equity,
                        available_cash=portfolio.cash,
                        entry_price=bar_close,
                        stop_loss_price=stops.stop_loss,
                        confidence=signal.confidence,
                    )
                    if qty > 0:
                        executor.execute_entry(
                            symbol=symbol,
                            side="short",
                            quantity=qty,
                            reference_price=bar_close,
                            stops=stops,
                            strategy=self.strategy.name,
                            reason=signal.reason,
                            timestamp=ts,
                        )

            portfolio.snapshot(timestamp=ts)

        # Close any remaining position at final close so performance metrics reflect realized PnL
        if portfolio.has_position(symbol):
            last_row = data.iloc[-1]
            last_ts = (
                last_row["timestamp"].to_pydatetime()
                if "timestamp" in data.columns and hasattr(last_row["timestamp"], "to_pydatetime")
                else datetime.now(timezone.utc)
            )
            executor.execute_exit(
                symbol=symbol,
                reference_price=float(last_row["close"]),
                reason="end_of_backtest",
                timestamp=last_ts,
            )
            portfolio.snapshot(timestamp=last_ts)

        metrics = compute_performance_metrics(
            equity_curve=portfolio.equity_curve,
            trades=portfolio.trades,
            initial_capital=capital,
            timeframe=timeframe,
        )

        # Downsample equity curve gently if massive so API payloads stay crisp
        curve = portfolio.equity_curve
        if len(curve) > 300:
            step = max(1, len(curve) // 300)
            curve = curve[::step] + ([curve[-1]] if curve[-1] != curve[::step][-1] else [])

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            strategy=self.strategy.name,
            metrics=metrics,
            equity_curve=curve,
            trades=[t.to_dict() for t in portfolio.trades],
            halted_reason=drawdown_guard.halt_reason,
        )
