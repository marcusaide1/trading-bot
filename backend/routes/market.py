"""Market data and indicator overlay endpoints for dashboard charting."""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Query, Request

from bot.exchange.client import BinanceExchangeClient
from bot.exchange.market_data import MarketDataProvider
from bot.indicators.ema import calculate_ema
from bot.indicators.macd import calculate_macd
from bot.indicators.rsi import calculate_rsi

router = APIRouter()


@router.get("/ohlcv")
def get_market_ohlcv(
    request: Request,
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="15m"),
    limit: int = Query(default=120, ge=30, le=500),
) -> dict[str, Any]:
    settings = request.app.state.settings
    client = BinanceExchangeClient(settings)
    md = MarketDataProvider(exchange_client=client, redis_url=settings.redis_url)
    df = md.get_ohlcv(symbol=symbol.upper(), timeframe=timeframe, limit=limit)

    close = df["close"].astype(float)
    df["ema_fast"] = calculate_ema(close, settings.ema_fast_period)
    df["ema_slow"] = calculate_ema(close, settings.ema_slow_period)
    df["rsi"] = calculate_rsi(close, settings.rsi_period)
    macd_df = calculate_macd(close, settings.macd_fast, settings.macd_slow, settings.macd_signal)
    df["macd_hist"] = macd_df["histogram"]

    candles: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        candles.append(
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "volume": round(float(row["volume"]), 2),
                "ema_fast": round(float(row["ema_fast"]), 4) if pd.notna(row["ema_fast"]) else None,
                "ema_slow": round(float(row["ema_slow"]), 4) if pd.notna(row["ema_slow"]) else None,
                "rsi": round(float(row["rsi"]), 2) if pd.notna(row["rsi"]) else None,
                "macd_hist": round(float(row["macd_hist"]), 5) if pd.notna(row["macd_hist"]) else None,
            }
        )

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "latest_price": candles[-1]["close"] if candles else 0.0,
        "candles": candles,
    }
