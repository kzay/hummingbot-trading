"""Breaker Block tracker.

A Breaker Block is a *failed* Order Block whose polarity flips:
  - A bullish OB that gets mitigated and then retested from above
    becomes a bearish breaker.
  - A bearish OB that gets mitigated and then retested from below
    becomes a bullish breaker.

This tracker monitors mitigated OBs and records retest events.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from controllers.common.ict._types import OrderBlockEvent


class BreakerBlockTracker:
    """O(k) per-bar breaker tracker."""

    __slots__ = ("_active_breakers", "_bar_idx", "_candidates")

    def __init__(self) -> None:
        self._candidates: list[OrderBlockEvent] = []
        self._active_breakers: list[OrderBlockEvent] = []
        self._bar_idx: int = 0

    def on_ob_mitigated(self, ob: OrderBlockEvent) -> None:
        """Register a mitigated OB as a breaker candidate."""
        if ob.status == "mitigated":
            self._candidates.append(ob)

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = Decimal(0),
    ) -> OrderBlockEvent | None:
        """Check if any candidate has been retested (polarity flip)."""
        self._bar_idx += 1
        result: OrderBlockEvent | None = None

        surviving: list[OrderBlockEvent] = []
        for ob in self._candidates:
            # Bullish OB mitigated -> becomes bearish breaker if retested from above
            if ob.direction == +1 and low <= ob.top and high >= ob.bottom:
                breaker = replace(ob, status="breaker", status_index=self._bar_idx - 1)
                self._active_breakers.append(breaker)
                result = breaker
                continue
            # Bearish OB mitigated -> becomes bullish breaker if retested from below
            if ob.direction == -1 and high >= ob.bottom and low <= ob.top:
                breaker = replace(ob, status="breaker", status_index=self._bar_idx - 1)
                self._active_breakers.append(breaker)
                result = breaker
                continue
            surviving.append(ob)
        self._candidates = surviving

        return result

    @property
    def active_breakers(self) -> list[OrderBlockEvent]:
        return list(self._active_breakers)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._candidates.clear()
        self._active_breakers.clear()
        self._bar_idx = 0
