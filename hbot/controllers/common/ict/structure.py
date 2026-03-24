"""Incremental BOS / CHoCH detector.

Consumes SwingEvents to detect market structure shifts:
  - **BOS** (Break of Structure): price breaks the last swing in the
    current trend direction (continuation).
  - **CHoCH** (Change of Character): price breaks the last swing
    *against* the current trend direction (reversal).

Uses a 4-element sliding window of alternating swing highs/lows.
"""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict._types import StructureEvent, SwingEvent


class StructureDetector:
    """O(1) per-bar structure detector (driven by SwingDetector output)."""

    __slots__ = (
        "_bar_idx",
        "_events",
        "_last_swing_high",
        "_last_swing_low",
        "_trend",  # +1 bullish, -1 bearish, 0 undefined
    )

    def __init__(self) -> None:
        self._last_swing_high: SwingEvent | None = None
        self._last_swing_low: SwingEvent | None = None
        self._trend: int = 0
        self._events: list[StructureEvent] = []
        self._bar_idx: int = 0

    def on_swing(self, swing: SwingEvent) -> StructureEvent | None:
        """Process a new confirmed swing.  Returns a StructureEvent if
        a BOS or CHoCH is detected."""
        event: StructureEvent | None = None

        if swing.direction == +1:
            # New swing high
            if self._last_swing_high is not None:
                if swing.level > self._last_swing_high.level:
                    if self._trend == +1 or self._trend == 0:
                        event = StructureEvent(
                            index=swing.index,
                            event_type="bos",
                            direction=+1,
                            level=swing.level,
                            swing_index=swing.index,
                        )
                    else:
                        event = StructureEvent(
                            index=swing.index,
                            event_type="choch",
                            direction=+1,
                            level=swing.level,
                            swing_index=swing.index,
                        )
                    self._trend = +1
            self._last_swing_high = swing

        elif swing.direction == -1:
            # New swing low
            if self._last_swing_low is not None:
                if swing.level < self._last_swing_low.level:
                    if self._trend == -1 or self._trend == 0:
                        event = StructureEvent(
                            index=swing.index,
                            event_type="bos",
                            direction=-1,
                            level=swing.level,
                            swing_index=swing.index,
                        )
                    else:
                        event = StructureEvent(
                            index=swing.index,
                            event_type="choch",
                            direction=-1,
                            level=swing.level,
                            swing_index=swing.index,
                        )
                    self._trend = -1
            self._last_swing_low = swing

        if event is not None:
            self._events.append(event)
        return event

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = Decimal(0),
    ) -> None:
        """Track bar count for warmup checks (structure is swing-driven)."""
        self._bar_idx += 1

    @property
    def trend(self) -> int:
        """Current trend: +1 bullish, -1 bearish, 0 undefined."""
        return self._trend

    @property
    def events(self) -> list[StructureEvent]:
        return list(self._events)

    @property
    def last_event(self) -> StructureEvent | None:
        return self._events[-1] if self._events else None

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._last_swing_high = None
        self._last_swing_low = None
        self._trend = 0
        self._events.clear()
        self._bar_idx = 0
