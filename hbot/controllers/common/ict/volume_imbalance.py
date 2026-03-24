"""Incremental Volume Imbalance detector.

Unlike FVG (wick-to-wick gap), a Volume Imbalance is a body-to-body gap:
  - Bullish VI: bar[i-1].close < bar[i].open (gap up in bodies).
  - Bearish VI: bar[i-1].close > bar[i].open (gap down in bodies).

Active VIs are mitigated when price revisits the gap zone.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from controllers.common.ict._types import VolumeImbalanceEvent

_ZERO = Decimal("0")
_TEN_K = Decimal("10000")


class VolumeImbalanceDetector:
    """O(k) per-bar volume imbalance detector."""

    __slots__ = (
        "_active",
        "_all_events",
        "_bar_idx",
        "_decay_bars",
        "_max_active",
        "_prev_close",
    )

    def __init__(self, max_active: int = 20, decay_bars: int = 15) -> None:
        self._max_active = max_active
        self._decay_bars = decay_bars
        self._prev_close: Decimal | None = None
        self._bar_idx: int = 0
        self._active: list[VolumeImbalanceEvent] = []
        self._all_events: list[VolumeImbalanceEvent] = []

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = _ZERO,
    ) -> VolumeImbalanceEvent | None:
        self._bar_idx += 1
        new_event: VolumeImbalanceEvent | None = None

        if self._prev_close is not None:
            # Bullish VI: previous close < current open
            if self._prev_close < open_:
                new_event = VolumeImbalanceEvent(
                    index=self._bar_idx - 1,
                    direction=+1,
                    top=open_,
                    bottom=self._prev_close,
                )
                self._active.append(new_event)
                self._all_events.append(new_event)

            # Bearish VI: previous close > current open
            elif self._prev_close > open_:
                new_event = VolumeImbalanceEvent(
                    index=self._bar_idx - 1,
                    direction=-1,
                    top=self._prev_close,
                    bottom=open_,
                )
                self._active.append(new_event)
                self._all_events.append(new_event)

        self._mitigate_and_decay(high, low)

        if len(self._active) > self._max_active:
            self._active = self._active[-self._max_active :]

        self._prev_close = close
        return new_event

    def _mitigate_and_decay(self, high: Decimal, low: Decimal) -> None:
        surviving: list[VolumeImbalanceEvent] = []
        for vi in self._active:
            age = self._bar_idx - 1 - vi.index
            if age > self._decay_bars:
                continue
            if vi.direction == +1 and low <= vi.bottom:
                mitigated = replace(vi, mitigated=True, mitigated_index=self._bar_idx - 1)
                self._replace_in_history(vi, mitigated)
                continue
            if vi.direction == -1 and high >= vi.top:
                mitigated = replace(vi, mitigated=True, mitigated_index=self._bar_idx - 1)
                self._replace_in_history(vi, mitigated)
                continue
            surviving.append(vi)
        self._active = surviving

    def _replace_in_history(self, old: VolumeImbalanceEvent, new: VolumeImbalanceEvent) -> None:
        for i in range(len(self._all_events) - 1, -1, -1):
            if self._all_events[i] is old:
                self._all_events[i] = new
                return

    @property
    def active(self) -> list[VolumeImbalanceEvent]:
        return list(self._active)

    @property
    def all_events(self) -> list[VolumeImbalanceEvent]:
        return list(self._all_events)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._prev_close = None
        self._bar_idx = 0
        self._active.clear()
        self._all_events.clear()
