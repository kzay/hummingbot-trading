"""Per-pair rolling window state for the ML feature service.

Maintains a configurable rolling window of 1m candles (default 20160 = 14d),
resamples to higher timeframes on demand, and caches sentiment data.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque

import pandas as pd

from services.ml_feature_service.bar_builder import Bar

logger = logging.getLogger(__name__)

_TF_MIN_WINDOWS = {"1m": 120, "5m": 600, "15m": 1800, "1h": 7200, "4h": 28800}

def _compute_rolling_window() -> int:
    """Derive rolling window from ML_TIMEFRAMES; >= 120 bars per highest TF."""
    env_override = os.getenv("ML_ROLLING_WINDOW")
    if env_override:
        return int(env_override)
    raw = os.getenv("ML_TIMEFRAMES", "1m,5m,15m,1h")
    tfs = [t.strip() for t in raw.split(",") if t.strip() in _TF_MIN_WINDOWS]
    if not tfs:
        return 20160
    return max(_TF_MIN_WINDOWS.get(tf, 20160) for tf in tfs)


ROLLING_WINDOW = _compute_rolling_window()


TRADE_BUFFER_SIZE = int(os.getenv("ML_TRADE_BUFFER_SIZE", "5000"))
MARK_INDEX_REFRESH_S = int(os.getenv("ML_MARK_INDEX_REFRESH_S", "60"))


class PairFeatureState:
    """Holds rolling bar history, trade buffer, mark/index cache, and sentiment for one pair."""

    def __init__(self, pair: str, exchange: str) -> None:
        self.pair = pair
        self.exchange = exchange
        self._bars: deque[Bar] = deque(maxlen=ROLLING_WINDOW)
        self._warmup_complete = False
        self._last_feature_ts_ms: int = 0
        self._cached_funding: pd.DataFrame | None = None
        self._cached_ls_ratio: pd.DataFrame | None = None
        self._last_sentiment_poll_s: float = 0.0
        self._trades: deque[dict] = deque(maxlen=TRADE_BUFFER_SIZE)
        self._mark_candles: pd.DataFrame | None = None
        self._index_candles: pd.DataFrame | None = None
        self._last_mark_index_refresh_s: float = 0.0

    @property
    def is_warm(self) -> bool:
        return len(self._bars) >= 60

    @property
    def bar_count(self) -> int:
        return len(self._bars)

    def seed_from_candles(self, candles_df: pd.DataFrame) -> int:
        """Bulk-load historical candles into the rolling window.

        Returns the number of bars loaded.
        """
        count = 0
        for row in candles_df.itertuples(index=False):
            bar = Bar(
                timestamp_ms=int(row.timestamp_ms),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                trade_count=0,
            )
            self._bars.append(bar)
            count += 1
        self._warmup_complete = count >= 60
        logger.info("Seeded %d bars for %s/%s (warm=%s)", count, self.exchange, self.pair, self._warmup_complete)
        return count

    def append_bar(self, bar: Bar) -> None:
        """Append a newly completed bar from the BarBuilder."""
        self._bars.append(bar)
        if not self._warmup_complete and len(self._bars) >= 60:
            self._warmup_complete = True

    def to_candles_df(self) -> pd.DataFrame:
        """Convert current rolling window to a float64 DataFrame."""
        if not self._bars:
            return pd.DataFrame(columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        data = [
            {
                "timestamp_ms": b.timestamp_ms,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in self._bars
        ]
        df = pd.DataFrame(data)
        return df.sort_values("timestamp_ms").reset_index(drop=True)

    def resample(self, period_minutes: int) -> pd.DataFrame:
        """Resample 1m bars to a higher timeframe (e.g. 5, 15, 60)."""
        df = self.to_candles_df()
        if df.empty:
            return df
        df["dt"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        df = df.set_index("dt")
        resampled = df.resample(f"{period_minutes}min", label="left", closed="left").agg({
            "timestamp_ms": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["timestamp_ms"])
        return resampled.reset_index(drop=True)

    def update_sentiment_cache(
        self,
        funding: pd.DataFrame | None = None,
        ls_ratio: pd.DataFrame | None = None,
    ) -> None:
        """Cache fresh sentiment data from periodic polling."""
        if funding is not None:
            self._cached_funding = funding
        if ls_ratio is not None:
            self._cached_ls_ratio = ls_ratio
        self._last_sentiment_poll_s = time.time()

    # -- Trade buffer ----------------------------------------------------------

    def append_trade(self, price: float, size: float, ts_ms: int, side: str = "unknown") -> None:
        """Buffer a raw trade for microstructure feature computation."""
        self._trades.append({
            "timestamp_ms": ts_ms,
            "price": price,
            "size": size,
            "side": side,
        })

    def trades_df(self) -> pd.DataFrame | None:
        """Return buffered trades as a DataFrame, or None if empty."""
        if not self._trades:
            return None
        return pd.DataFrame(list(self._trades))

    # -- Mark / Index price cache ---------------------------------------------

    def update_mark_index(
        self,
        mark: pd.DataFrame | None = None,
        index: pd.DataFrame | None = None,
    ) -> None:
        if mark is not None and not mark.empty:
            self._mark_candles = mark
        if index is not None and not index.empty:
            self._index_candles = index
        self._last_mark_index_refresh_s = time.time()

    @property
    def mark_index_stale_s(self) -> float:
        if self._last_mark_index_refresh_s == 0:
            return float("inf")
        return time.time() - self._last_mark_index_refresh_s

    @property
    def sentiment_stale_s(self) -> float:
        if self._last_sentiment_poll_s == 0:
            return float("inf")
        return time.time() - self._last_sentiment_poll_s
