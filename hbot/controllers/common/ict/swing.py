"""Incremental swing high/low detector.

Uses a sliding window of size ``2 * length + 1`` to detect pivot points.
A swing high is confirmed when the bar at position ``length`` has the
highest high in the window.  Swing low is symmetric.

Alternation is enforced: the detector never emits two consecutive highs
or two consecutive lows.  If two highs (lows) occur in sequence, only
the more extreme one is kept.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal

from controllers.common.ict._types import SwingEvent


class SwingDetector:
    """O(k) per-bar swing detector where k = 2 * length + 1."""

    __slots__ = (
        "_bar_idx",
        "_highs",
        "_last_direction",
        "_length",
        "_lows",
        "_swings",
        "_window_size",
    )

    def __init__(self, length: int = 10) -> None:
        if length < 1:
            raise ValueError("length must be >= 1")
        self._length = length
        self._window_size = 2 * length + 1
        self._highs: deque[Decimal] = deque(maxlen=self._window_size)
        self._lows: deque[Decimal] = deque(maxlen=self._window_size)
        self._bar_idx: int = 0
        self._swings: list[SwingEvent] = []
        self._last_direction: int = 0

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = Decimal(0),
    ) -> SwingEvent | None:
        """Feed one OHLCV bar.  Returns a SwingEvent if the bar at the
        pivot position is confirmed, otherwise ``None``."""
        self._highs.append(high)
        self._lows.append(low)
        self._bar_idx += 1

        if len(self._highs) < self._window_size:
            return None

        pivot_pos = self._length
        pivot_idx = self._bar_idx - self._length - 1  # 0-based bar index of pivot

        pivot_high = self._highs[pivot_pos]
        pivot_low = self._lows[pivot_pos]

        is_swing_high = all(
            pivot_high > self._highs[i]
            for i in range(self._window_size)
            if i != pivot_pos
        )
        is_swing_low = all(
            pivot_low < self._lows[i]
            for i in range(self._window_size)
            if i != pivot_pos
        )

        event: SwingEvent | None = None

        if is_swing_high and is_swing_low:
            # Both qualify -- pick the more significant relative to neighbours
            high_margin = min(
                pivot_high - self._highs[i]
                for i in range(self._window_size)
                if i != pivot_pos
            )
            low_margin = min(
                self._lows[i] - pivot_low
                for i in range(self._window_size)
                if i != pivot_pos
            )
            if high_margin >= low_margin:
                event = self._try_emit(pivot_idx, +1, pivot_high)
            else:
                event = self._try_emit(pivot_idx, -1, pivot_low)
        elif is_swing_high:
            event = self._try_emit(pivot_idx, +1, pivot_high)
        elif is_swing_low:
            event = self._try_emit(pivot_idx, -1, pivot_low)

        return event

    def _try_emit(self, index: int, direction: int, level: Decimal) -> SwingEvent | None:
        """Enforce alternation and emit the event."""
        if self._last_direction == direction:
            if not self._swings:
                return None
            prev = self._swings[-1]
            if (direction == +1 and level > prev.level) or (direction == -1 and level < prev.level):
                self._swings[-1] = SwingEvent(index=index, direction=direction, level=level)
                return self._swings[-1]
            return None

        event = SwingEvent(index=index, direction=direction, level=level)
        self._swings.append(event)
        self._last_direction = direction
        return event

    @property
    def swings(self) -> list[SwingEvent]:
        return list(self._swings)

    @property
    def last_swing(self) -> SwingEvent | None:
        return self._swings[-1] if self._swings else None

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._bar_idx = 0
        self._swings.clear()
        self._last_direction = 0
