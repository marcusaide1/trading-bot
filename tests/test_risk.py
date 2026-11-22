"""Tests for risk management: position sizing, stops, trailing stops, and drawdown guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bot.risk.drawdown import DrawdownGuard
from bot.risk.position_sizing import PositionSizer
from bot.risk.stop_loss import StopLossManager


def test_position_sizer_respects_risk_and_max_exposure() -> None:
    sizer = PositionSizer(risk_per_trade_pct=0.01, max_position_pct=0.25)

    # Equity=$10,000, risk 1% = $100, entry=$100, stop=$95 (distance=$5) -> risk qty = 20 units ($2000 <= $2500 cap)
    qty = sizer.calculate_quantity(
        equity=10000.0,
        available_cash=10000.0,
        entry_price=100.0,
        stop_loss_price=95.0,
        confidence=1.0,
    )
    assert pytest.approx(qty, rel=1e-4) == 20.0

    # Very tight stop ($99.90) would risk-size to 1000 units ($100k), must be capped at 25% ($2500 -> 25 units)
    capped_qty = sizer.calculate_quantity(
        equity=10000.0,
        available_cash=10000.0,
        entry_price=100.0,
        stop_loss_price=99.90,
        confidence=1.0,
    )
    assert pytest.approx(capped_qty, rel=1e-4) == 25.0


def test_fractional_kelly_bounds() -> None:
    assert PositionSizer.fractional_kelly(win_rate=0.30, avg_win=100, avg_loss=150) == 0.0
    k = PositionSizer.fractional_kelly(win_rate=0.60, avg_win=200, avg_loss=100, cap=0.03)
    assert 0.0 < k <= 0.03


def test_stop_loss_manager_atr_and_trailing() -> None:
    mgr = StopLossManager(
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        trailing_stop_pct=0.015,
        use_atr_stops=True,
        atr_stop_multiplier=2.0,
        atr_tp_multiplier=4.0,
    )
    levels = mgr.compute_levels(entry_price=1000.0, side="long", atr=10.0)
    assert pytest.approx(levels.stop_loss) == 980.0
    assert pytest.approx(levels.take_profit) == 1040.0

    # Price rallies to $1050 -> trailing stop ratchets up to 1050 * 0.985 = 1034.25
    trailed = mgr.update_trailing_stop("long", 1000.0, 1050.0, levels.stop_loss)
    assert pytest.approx(trailed) == 1034.25

    # Price dips to $1040 -> trailing stop MUST NOT loosen
    trailed_down = mgr.update_trailing_stop("long", 1000.0, 1040.0, trailed)
    assert trailed_down == trailed


def test_stop_loss_trigger_is_conservative_when_both_hit() -> None:
    # Bar sweeps both below stop_loss (98) and above take_profit (104) -> stop_loss must win
    trigger, price = StopLossManager.check_exit_trigger(
        side="long", bar_high=106.0, bar_low=97.0, stop_loss=98.0, take_profit=104.0
    )
    assert trigger == "stop_loss"
    assert price == 98.0


def test_drawdown_guard_halts_on_drawdown_daily_loss_and_streak() -> None:
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    guard = DrawdownGuard(
        initial_equity=10000.0,
        max_drawdown_pct=0.10,
        max_daily_loss_pct=0.03,
        max_consecutive_losses=3,
    )

    # New peak at $10,500
    status = guard.update_equity(10500.0, timestamp=t0)
    assert status.can_trade
    assert status.peak_equity == 10500.0

    # Daily loss >= 3% from $10,000 start -> $9,690 triggers daily halt
    status = guard.update_equity(9690.0, timestamp=t0 + timedelta(hours=1))
    assert status.is_halted
    assert "Daily loss limit" in status.halt_reason

    # Next UTC day clears daily loss halt
    status = guard.update_equity(9690.0, timestamp=t0 + timedelta(days=1))
    assert not status.is_halted

    # Max drawdown >= 10% from $10,500 peak (<= $9,450) triggers permanent halt
    status = guard.update_equity(9400.0, timestamp=t0 + timedelta(days=1, hours=1))
    assert status.is_halted
    assert "Max drawdown" in status.halt_reason

    # Reset and verify consecutive-loss circuit breaker
    guard.reset_halt(new_equity=9400.0)
    assert not guard.is_halted
    guard.record_trade_result(-50.0)
    guard.record_trade_result(-40.0)
    assert not guard.is_halted
    guard.record_trade_result(-30.0)
    assert guard.is_halted
    assert "Consecutive loss" in guard.halt_reason
