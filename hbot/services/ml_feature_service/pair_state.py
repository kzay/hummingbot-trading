"""Per-pair rolling window state for the ML feature service.

Maintains a 1440-bar (24h) rolling window of 1m candles, resamples to
higher timeframes on demand, and caches sentiment data.
"""
from __future__ import annotations

import logging
import time
from collections import deque

import pandas as pd

from services.ml_feature_service.bar_builder import Bar

logger = logging.getLogger(__name__)

ROLLING_WINDOW = 1440  # 24 hours of 1m bars


class PairFeatureState:
    """Holds rolling bar history and cached sentiment for one pair."""

    def __init__(self, pair: str, exchange: str) -> None:
        self.pair = pair
        self.exchange = exchange
        self._bars: deque[Bar] = deque(maxlen=ROLLING_WINDOW)
        self._warmup_complete = False
        self._last_feature_ts_ms: int = 0
        self._cached_funding: pd.DataFrame | None = None
        self._cached_ls_ratio: pd.DataFrame | None = None
        self._last_sentiment_poll_s: float = 0.0

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
        return pd.DataFrame(data)

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

    @property
    def sentiment_stale_s(self) -> float:
        if self._last_sentiment_poll_s == 0:
            return float("inf")
        return time.time() - self._last_sentiment_poll_s
