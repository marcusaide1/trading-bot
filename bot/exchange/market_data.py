"""Market data ingestion, Redis/in-memory caching, and synthetic OHLCV generation."""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
import pandas as pd

from bot.exchange.client import BinanceExchangeClient
from bot.monitoring.logger import get_logger

logger = get_logger("exchange.market_data")

TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


def generate_synthetic_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    bars: int = 500,
    start_price: float | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic regime-switching synthetic crypto OHLCV candles for offline testing."""
    rng = np.random.default_rng(seed)
    step_sec = TIMEFRAME_SECONDS.get(timeframe, 900)
    now_ts = int(time.time() // step_sec) * step_sec
    timestamps = pd.to_datetime(
        [now_ts - (bars - 1 - i) * step_sec for i in range(bars)], unit="s", utc=True
    )

    if start_price is None:
        base_map = {"BTC/USDT": 68000.0, "ETH/USDT": 3400.0, "SOL/USDT": 165.0}
        start_price = base_map.get(symbol.upper(), 100.0)

    # Regime-switching drift creates realistic trend waves + pullbacks
    closes = np.empty(bars, dtype=float)
    closes[0] = start_price
    regime_len = max(35, bars // 8)
    regimes = [0.0014, -0.0010, 0.0018, 0.0002, -0.0013, 0.0016, 0.0009, -0.0006]

    for i in range(1, bars):
        regime_idx = (i // regime_len) % len(regimes)
        drift = regimes[regime_idx]
        vol = 0.0065 if abs(drift) > 0.001 else 0.0045
        ret = rng.normal(drift, vol)
        closes[i] = max(closes[i - 1] * (1.0 + ret), start_price * 0.1)

    opens = np.roll(closes, 1)
    opens[0] = start_price
    spread = rng.uniform(0.0015, 0.0065, size=bars)
    highs = np.maximum(opens, closes) * (1.0 + spread)
    lows = np.minimum(opens, closes) * (1.0 - spread)
    volumes = rng.lognormal(mean=4.8, sigma=0.55, size=bars)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


class MarketDataProvider:
    """Fetches OHLCV candles from Binance with optional Redis caching and offline fallback."""

    def __init__(
        self,
        exchange_client: BinanceExchangeClient | None = None,
        redis_url: str | None = None,
        cache_ttl_seconds: int = 20,
    ) -> None:
        self.exchange_client = exchange_client
        self.cache_ttl_seconds = cache_ttl_seconds
        self._mem_cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._redis: Any = None
        if redis_url:
            self._init_redis(redis_url)

    def _init_redis(self, redis_url: str) -> None:
        try:
            import redis

            client = redis.from_url(redis_url, socket_connect_timeout=1.5, socket_timeout=1.5)
            client.ping()
            self._redis = client
            logger.info("Connected to Redis market data cache")
        except Exception:
            self._redis = None
            logger.debug("Redis unavailable; using in-memory market data cache")

    def _cache_key(self, symbol: str, timeframe: str, limit: int) -> str:
        return f"ohlcv:{symbol}:{timeframe}:{limit}"

    def _get_cached(self, key: str) -> pd.DataFrame | None:
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw:
                    records = json.loads(raw)
                    df = pd.DataFrame(records)
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                    return df
            except Exception:
                pass

        cached = self._mem_cache.get(key)
        if cached and (time.time() - cached[0]) < self.cache_ttl_seconds:
            return cached[1].copy()
        return None

    def _set_cached(self, key: str, df: pd.DataFrame) -> None:
        self._mem_cache[key] = (time.time(), df.copy())
        if self._redis is not None:
            try:
                serializable = df.copy()
                serializable["timestamp"] = serializable["timestamp"].astype(str)
                self._redis.setex(
                    key, self.cache_ttl_seconds, serializable.to_json(orient="records")
                )
            except Exception:
                pass

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 300,
        allow_synthetic_fallback: bool = True,
    ) -> pd.DataFrame:
        """Retrieve OHLCV DataFrame sorted chronologically."""
        key = self._cache_key(symbol, timeframe, limit)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        if self.exchange_client is not None:
            try:
                raw = self.exchange_client.fetch_ohlcv(
                    symbol=symbol, timeframe=timeframe, limit=limit
                )
                df = pd.DataFrame(
                    raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                for col in ("open", "high", "low", "close", "volume"):
                    df[col] = df[col].astype(float)
                df = df.sort_values("timestamp").reset_index(drop=True)
                self._set_cached(key, df)
                return df
            except Exception as exc:
                logger.warning("Live OHLCV fetch failed for %s (%s)", symbol, exc)
                if not allow_synthetic_fallback:
                    raise

        logger.info("Using synthetic OHLCV fallback for %s (%s)", symbol, timeframe)
        seed = abs(hash(f"{symbol}:{timeframe}")) % (2**31)
        df = generate_synthetic_ohlcv(symbol=symbol, timeframe=timeframe, bars=limit, seed=seed)
        self._set_cached(key, df)
        return df

    def get_latest_price(self, symbol: str, timeframe: str = "15m") -> float:
        """Get most recent price from live ticker or latest OHLCV close."""
        if self.exchange_client is not None:
            try:
                return self.exchange_client.fetch_ticker_price(symbol)
            except Exception:
                pass
        df = self.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=50)
        return float(df["close"].iloc[-1])
