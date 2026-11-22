"""Institutional-grade backtest and live performance analytics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from bot.execution.portfolio import TradeFill

PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 525600.0,
    "3m": 175200.0,
    "5m": 105120.0,
    "15m": 35040.0,
    "30m": 17520.0,
    "1h": 8760.0,
    "2h": 4380.0,
    "4h": 2190.0,
    "1d": 365.0,
}


@dataclass
class PerformanceMetrics:
    initial_capital: float
    final_equity: float
    net_profit: float
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: float
    expectancy: float
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_fees_paid: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_performance_metrics(
    equity_curve: list[dict[str, Any]],
    trades: list[TradeFill],
    initial_capital: float,
    timeframe: str = "15m",
) -> PerformanceMetrics:
    """Compute risk-adjusted performance metrics from an equity curve and trade list."""
    if not equity_curve:
        return PerformanceMetrics(
            initial_capital=round(initial_capital, 2),
            final_equity=round(initial_capital, 2),
            net_profit=0.0,
            total_return_pct=0.0,
            cagr_pct=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            best_trade=0.0,
            worst_trade=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            total_fees_paid=0.0,
        )

    equities = pd.Series([float(pt["equity"]) for pt in equity_curve], dtype=float)
    final_equity = float(equities.iloc[-1])
    net_profit = final_equity - initial_capital
    total_return = net_profit / initial_capital if initial_capital > 0 else 0.0

    # Peak-to-trough max drawdown
    running_max = equities.cummax()
    drawdowns = (running_max - equities) / running_max.replace(0.0, np.nan)
    max_dd = float(drawdowns.max()) if not drawdowns.empty and pd.notna(drawdowns.max()) else 0.0

    # Periodic returns & annualized Sharpe / Sortino
    returns = equities.pct_change().dropna()
    periods_per_year = PERIODS_PER_YEAR.get(timeframe, 35040.0)

    if len(returns) > 1 and returns.std() > 1e-12:
        sharpe = float((returns.mean() / returns.std()) * math.sqrt(periods_per_year))
    else:
        sharpe = 0.0

    downside = returns[returns < 0]
    if len(downside) > 1 and downside.std() > 1e-12:
        sortino = float((returns.mean() / downside.std()) * math.sqrt(periods_per_year))
    else:
        sortino = sharpe if sharpe > 0 else 0.0

    # Annualized CAGR
    years = max(len(equities) / periods_per_year, 1e-6)
    if final_equity > 0 and initial_capital > 0:
        ratio = final_equity / initial_capital
        cagr = (ratio ** (1.0 / years) - 1.0) if years >= (1.0 / 365.0) else total_return
        cagr = max(-1.0, min(cagr, 100.0))  # clamp extreme short-window extrapolations
    else:
        cagr = -1.0

    calmar = (cagr / max_dd) if max_dd > 1e-6 else 0.0

    # Closed trade statistics
    closed = [t for t in trades if t.action == "exit"]
    pnls = [t.realized_pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_trades = len(closed)
    win_rate = (len(wins) / total_trades) if total_trades > 0 else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = 99.99
    else:
        profit_factor = 0.0

    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0
    expectancy = (sum(pnls) / total_trades) if total_trades > 0 else 0.0
    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0
    total_fees = sum(t.fee for t in trades)

    return PerformanceMetrics(
        initial_capital=round(initial_capital, 2),
        final_equity=round(final_equity, 2),
        net_profit=round(net_profit, 2),
        total_return_pct=round(total_return * 100.0, 2),
        cagr_pct=round(cagr * 100.0, 2),
        sharpe_ratio=round(sharpe, 3),
        sortino_ratio=round(sortino, 3),
        calmar_ratio=round(calmar, 3),
        max_drawdown_pct=round(max_dd * 100.0, 2),
        win_rate_pct=round(win_rate * 100.0, 2),
        profit_factor=round(profit_factor, 3),
        expectancy=round(expectancy, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        best_trade=round(best_trade, 2),
        worst_trade=round(worst_trade, 2),
        total_trades=total_trades,
        winning_trades=len(wins),
        losing_trades=len(losses),
        total_fees_paid=round(total_fees, 4),
    )
