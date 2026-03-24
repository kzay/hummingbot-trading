"""Incremental Fair Value Gap detector.

A bullish FVG occurs when bar[i-2].high < bar[i].low.
A bearish FVG occurs when bar[i-2].low > bar[i].high.

Active FVGs are tracked and removed when mitigated (price revisits the gap)
or when they exceed ``decay_bars`` age.  The active list is bounded to
``max_active`` entries (oldest evicted first).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from controllers.common.ict._types import FVGEvent

_ZERO = Decimal("0")
_TEN_K = Decimal("10000")


class FVGDetector:
    """O(k) per-bar FVG detector where k = max_active."""

    __slots__ = (
        "_active",
        "_all_events",
        "_bar_idx",
        "_decay_bars",
        "_max_active",
        "_prev1_high",
        "_prev1_low",
        "_prev2_high",
        "_prev2_low",
    )

    def __init__(self, decay_bars: int = 10, max_active: int = 20) -> None:
        self._decay_bars = decay_bars
        self._max_active = max_active
        self._prev2_high: Decimal | None = None
        self._prev2_low: Decimal | None = None
        self._prev1_high: Decimal | None = None
        self._prev1_low: Decimal | None = None
        self._bar_idx: int = 0
        self._active: list[FVGEvent] = []
        self._all_events: list[FVGEvent] = []

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = _ZERO,
    ) -> FVGEvent | None:
        """Feed one OHLCV bar.  Returns new FVGEvent or None."""
        self._bar_idx += 1
        new_event: FVGEvent | None = None

        if self._prev2_high is not None and self._prev1_high is not None:
            # Bullish FVG: bar[i-2].high < bar[i].low
            if self._prev2_high < low:
                gap_top = low
                gap_bottom = self._prev2_high
                mid = (gap_top + gap_bottom) / Decimal(2)
                if mid > _ZERO:
                    size_bps = (gap_top - gap_bottom) / mid * _TEN_K
                else:
                    size_bps = _ZERO
                new_event = FVGEvent(
                    index=self._bar_idx - 1,
                    direction=+1,
                    top=gap_top,
                    bottom=gap_bottom,
                    size_bps=size_bps,
                )
                self._active.append(new_event)
                self._all_events.append(new_event)

            # Bearish FVG: bar[i-2].low > bar[i].high
            elif self._prev2_low is not None and self._prev2_low > high:
                gap_top = self._prev2_low
                gap_bottom = high
                mid = (gap_top + gap_bottom) / Decimal(2)
                if mid > _ZERO:
                    size_bps = (gap_top - gap_bottom) / mid * _TEN_K
                else:
                    size_bps = _ZERO
                new_event = FVGEvent(
                    index=self._bar_idx - 1,
                    direction=-1,
                    top=gap_top,
                    bottom=gap_bottom,
                    size_bps=size_bps,
                )
                self._active.append(new_event)
                self._all_events.append(new_event)

        self._mitigate_and_decay(high, low)

        if len(self._active) > self._max_active:
            self._active = self._active[-self._max_active :]

        self._prev2_high = self._prev1_high
        self._prev2_low = self._prev1_low
        self._prev1_high = high
        self._prev1_low = low

        return new_event

    def _mitigate_and_decay(self, high: Decimal, low: Decimal) -> None:
        surviving: list[FVGEvent] = []
        for fvg in self._active:
            age = self._bar_idx - 1 - fvg.index
            if age > self._decay_bars:
                continue
            # Bullish FVG mitigated when price trades below the gap bottom
            if fvg.direction == +1 and low <= fvg.bottom:
                mitigated = replace(fvg, mitigated=True, mitigated_index=self._bar_idx - 1)
                self._replace_in_history(fvg, mitigated)
                continue
            # Bearish FVG mitigated when price trades above the gap top
            if fvg.direction == -1 and high >= fvg.top:
                mitigated = replace(fvg, mitigated=True, mitigated_index=self._bar_idx - 1)
                self._replace_in_history(fvg, mitigated)
                continue
            surviving.append(fvg)
        self._active = surviving

    def _replace_in_history(self, old: FVGEvent, new: FVGEvent) -> None:
        for i in range(len(self._all_events) - 1, -1, -1):
            if self._all_events[i] is old:
                self._all_events[i] = new
                return

    @property
    def active(self) -> list[FVGEvent]:
        return list(self._active)

    @property
    def all_events(self) -> list[FVGEvent]:
        return list(self._all_events)

    @property
    def bullish_bias(self) -> int:
        """Net directional count of active FVGs: positive = bullish."""
        return sum(f.direction for f in self._active)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._prev2_high = None
        self._prev2_low = None
        self._prev1_high = None
        self._prev1_low = None
        self._bar_idx = 0
        self._active.clear()
        self._all_events.clear()
