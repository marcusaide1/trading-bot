"""Centralized typed configuration loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with safe defaults (paper mode by default)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Mode & Exchange
    trading_mode: Literal["paper", "testnet", "live"] = "paper"
    exchange_name: str = "binance"
    market_type: Literal["spot", "futures"] = "spot"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet_api_key: str = ""
    binance_testnet_api_secret: str = ""
    default_leverage: int = Field(default=1, ge=1, le=20)

    # Trading Universe & Cadence
    trading_symbols: str = "BTC/USDT,ETH/USDT"
    timeframe: str = "15m"
    strategy_name: Literal["trend_following", "moving_average", "composite"] = "composite"
    poll_interval_seconds: int = Field(default=30, ge=1, le=3600)
    initial_capital: float = Field(default=10000.0, gt=0)

    # Indicator Parameters
    ema_fast_period: int = Field(default=12, ge=2)
    ema_slow_period: int = Field(default=26, ge=3)
    ema_trend_period: int = Field(default=200, ge=20)
    rsi_period: int = Field(default=14, ge=2)
    rsi_overbought: float = Field(default=70.0, gt=50.0, lt=100.0)
    rsi_oversold: float = Field(default=30.0, gt=0.0, lt=50.0)
    macd_fast: int = Field(default=12, ge=2)
    macd_slow: int = Field(default=26, ge=3)
    macd_signal: int = Field(default=9, ge=2)

    # Risk Management
    risk_per_trade_pct: float = Field(default=0.01, gt=0.0, le=0.10)
    max_position_pct: float = Field(default=0.25, gt=0.0, le=1.0)
    max_open_positions: int = Field(default=3, ge=1, le=20)
    stop_loss_pct: float = Field(default=0.02, gt=0.001, le=0.50)
    take_profit_pct: float = Field(default=0.04, gt=0.002, le=2.0)
    trailing_stop_pct: float = Field(default=0.015, ge=0.0, le=0.50)
    use_atr_stops: bool = True
    atr_period: int = Field(default=14, ge=2)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    atr_tp_multiplier: float = Field(default=4.0, gt=0.2, le=20.0)
    max_daily_loss_pct: float = Field(default=0.03, gt=0.001, le=0.50)
    max_drawdown_pct: float = Field(default=0.10, gt=0.005, le=0.80)
    max_consecutive_losses: int = Field(default=4, ge=1, le=20)

    # Execution Simulation
    fee_rate: float = Field(default=0.001, ge=0.0, le=0.05)
    slippage_pct: float = Field(default=0.0005, ge=0.0, le=0.05)

    # Infrastructure
    database_url: str = "sqlite:///./trading_bot.db"
    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Monitoring & Alerts
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    @field_validator("ema_slow_period")
    @classmethod
    def validate_ema_order(cls, v: int, info) -> int:
        fast = info.data.get("ema_fast_period", 12)
        if v <= fast:
            raise ValueError("ema_slow_period must be greater than ema_fast_period")
        return v

    @property
    def symbols_list(self) -> list[str]:
        return [s.strip().upper() for s in self.trading_symbols.split(",") if s.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def active_api_key(self) -> str:
        if self.trading_mode == "testnet":
            return self.binance_testnet_api_key
        if self.trading_mode == "live":
            return self.binance_api_key
        return ""

    @property
    def active_api_secret(self) -> str:
        if self.trading_mode == "testnet":
            return self.binance_testnet_api_secret
        if self.trading_mode == "live":
            return self.binance_api_secret
        return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
