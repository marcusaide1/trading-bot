"""Initial schema for trading bot tables.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False, server_default="entry"),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pnl_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("strategy", sa.String(64), nullable=False, server_default="composite"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="paper"),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trades_order_id", "trades", ["order_id"])
    op.create_index("ix_trades_symbol", "trades", ["symbol"])
    op.create_index("ix_trades_created_at", "trades", ["created_at"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profit", sa.Float(), nullable=False),
        sa.Column("trailing_stop", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("strategy", sa.String(64), nullable=False, server_default="composite"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"])

    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("drawdown_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("open_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="paper"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_equity_snapshots_timestamp", "equity_snapshots", ["timestamp"])

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])
    op.create_index("ix_signals_created_at", "signals", ["created_at"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("initial_capital", sa.Float(), nullable=False),
        sa.Column("final_equity", sa.Float(), nullable=False),
        sa.Column("total_return_pct", sa.Float(), nullable=False),
        sa.Column("sharpe_ratio", sa.Float(), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("win_rate_pct", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("equity_curve_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_runs_symbol", "backtest_runs", ["symbol"])
    op.create_index("ix_backtest_runs_created_at", "backtest_runs", ["created_at"])

    op.create_table(
        "bot_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_halted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halt_reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("mode", sa.String(16), nullable=False, server_default="paper"),
        sa.Column("strategy", sa.String(64), nullable=False, server_default="composite"),
        sa.Column("symbols", sa.String(255), nullable=False, server_default="BTC/USDT,ETH/USDT"),
        sa.Column("timeframe", sa.String(16), nullable=False, server_default="15m"),
        sa.Column("equity", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("cash", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("peak_equity", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bot_state")
    op.drop_table("backtest_runs")
    op.drop_table("signals")
    op.drop_table("equity_snapshots")
    op.drop_table("positions")
    op.drop_table("trades")
