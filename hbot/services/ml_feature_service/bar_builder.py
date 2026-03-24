"""Accumulate individual trade ticks into 1m OHLCV bars.

Each ``BarBuilder`` instance tracks a single trading pair.  Call
:meth:`on_trade` for each incoming trade; when the minute boundary
crosses, :meth:`on_trade` returns the completed bar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Bar:
    """A single 1m OHLCV bar."""

    timestamp_ms: int  # floor to minute boundary
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int


class BarBuilder:
    """Build 1m bars from a stream of trade events for a single pair.

    Parameters
    ----------
    pair : str
        Trading pair name (for logging).
    """

    def __init__(self, pair: str) -> None:
        self.pair = pair
        self._current_minute: int = 0
        self._open: float = 0.0
        self._high: float = 0.0
        self._low: float = 0.0
        self._close: float = 0.0
        self._volume: float = 0.0
        self._trade_count: int = 0

    def on_trade(
        self,
        price: float,
        size: float,
        timestamp_ms: int,
    ) -> Bar | None:
        """Process a trade. Returns a completed bar when the minute rolls over.

        Handles out-of-order trades by ignoring trades older than the
        current bar's minute.
        """
        minute = (timestamp_ms // 60_000) * 60_000

        if minute < self._current_minute:
            return None

        completed: Bar | None = None

        if self._current_minute > 0 and minute > self._current_minute:
            if self._trade_count > 0:
                completed = Bar(
                    timestamp_ms=self._current_minute,
                    open=self._open,
                    high=self._high,
                    low=self._low,
                    close=self._close,
                    volume=self._volume,
                    trade_count=self._trade_count,
                )
            self._reset(minute)

        if self._current_minute == 0:
            self._current_minute = minute

        if self._trade_count == 0:
            self._open = price
            self._high = price
            self._low = price
        else:
            self._high = max(self._high, price)
            self._low = min(self._low, price)

        self._close = price
        self._volume += size
        self._trade_count += 1

        return completed

    def flush(self) -> Bar | None:
        """Force-emit the current partial bar (e.g. on shutdown)."""
        if self._trade_count == 0 or self._current_minute == 0:
            return None
        bar = Bar(
            timestamp_ms=self._current_minute,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            trade_count=self._trade_count,
        )
        self._reset(0)
        return bar

    def _reset(self, minute: int) -> None:
        self._current_minute = minute
        self._open = 0.0
        self._high = 0.0
        self._low = 0.0
        self._close = 0.0
        self._volume = 0.0
        self._trade_count = 0
