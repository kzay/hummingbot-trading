"""Incremental Order Block detector.

Order Blocks are the last opposite-direction candle *before* a structure
break (BOS/CHoCH).  They mark institutional supply/demand zones.

  - Bullish OB: the last bearish candle before a bullish structure break.
  - Bearish OB: the last bullish candle before a bearish structure break.

Active OBs are mitigated when price trades through them, and invalidated
when they exceed ``max_age`` bars.  The active list is bounded to
``max_active`` entries.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from controllers.common.ict._types import OrderBlockEvent, StructureEvent


class OrderBlockDetector:
    """O(k) per-bar OB detector where k = max_active."""

    __slots__ = (
        "_active",
        "_all_events",
        "_bar_idx",
        "_max_active",
        "_max_age",
        "_newly_mitigated",
        "_prev_candles",
    )

    def __init__(self, max_active: int = 15, max_age: int = 50) -> None:
        self._max_active = max_active
        self._max_age = max_age
        self._bar_idx: int = 0
        self._prev_candles: list[tuple[int, Decimal, Decimal, Decimal, Decimal]] = []
        self._active: list[OrderBlockEvent] = []
        self._all_events: list[OrderBlockEvent] = []
        self._newly_mitigated: list[OrderBlockEvent] = []

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = Decimal(0),
    ) -> None:
        """Track candle history for OB zone detection."""
        self._bar_idx += 1
        self._newly_mitigated.clear()
        self._prev_candles.append((self._bar_idx - 1, open_, high, low, close))
        if len(self._prev_candles) > 10:
            self._prev_candles.pop(0)

        self._age_and_mitigate(high, low)

    def on_structure(self, event: StructureEvent) -> OrderBlockEvent | None:
        """Called when StructureDetector emits a BOS/CHoCH.
        Scans recent candles for the last opposite-direction candle."""
        if not self._prev_candles:
            return None

        for idx, o, h, l, c in reversed(self._prev_candles):
            is_bearish_candle = c < o
            is_bullish_candle = c > o

            if event.direction == +1 and is_bearish_candle:
                ob = OrderBlockEvent(
                    index=idx,
                    direction=+1,
                    top=h,
                    bottom=l,
                    status="active",
                )
                self._active.append(ob)
                self._all_events.append(ob)
                self._trim_active()
                return ob

            if event.direction == -1 and is_bullish_candle:
                ob = OrderBlockEvent(
                    index=idx,
                    direction=-1,
                    top=h,
                    bottom=l,
                    status="active",
                )
                self._active.append(ob)
                self._all_events.append(ob)
                self._trim_active()
                return ob

        return None

    def _age_and_mitigate(self, high: Decimal, low: Decimal) -> None:
        surviving: list[OrderBlockEvent] = []
        for ob in self._active:
            age = self._bar_idx - 1 - ob.index
            if age > self._max_age:
                continue
            if ob.direction == +1 and low <= ob.bottom:
                mitigated = replace(ob, status="mitigated", status_index=self._bar_idx - 1)
                self._replace_in_history(ob, mitigated)
                self._newly_mitigated.append(mitigated)
                continue
            if ob.direction == -1 and high >= ob.top:
                mitigated = replace(ob, status="mitigated", status_index=self._bar_idx - 1)
                self._replace_in_history(ob, mitigated)
                self._newly_mitigated.append(mitigated)
                continue
            surviving.append(ob)
        self._active = surviving

    def _replace_in_history(self, old: OrderBlockEvent, new: OrderBlockEvent) -> None:
        for i in range(len(self._all_events) - 1, -1, -1):
            if self._all_events[i] is old:
                self._all_events[i] = new
                return

    def _trim_active(self) -> None:
        if len(self._active) > self._max_active:
            self._active = self._active[-self._max_active :]

    @property
    def active(self) -> list[OrderBlockEvent]:
        return list(self._active)

    @property
    def all_events(self) -> list[OrderBlockEvent]:
        return list(self._all_events)

    @property
    def newly_mitigated(self) -> list[OrderBlockEvent]:
        """OBs mitigated during the most recent add_bar call."""
        return list(self._newly_mitigated)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._bar_idx = 0
        self._prev_candles.clear()
        self._active.clear()
        self._all_events.clear()
        self._newly_mitigated.clear()
