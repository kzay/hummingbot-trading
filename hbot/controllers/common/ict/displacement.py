"""Incremental Displacement candle detector.

A displacement candle has a body size exceeding ``atr_mult`` times the
current ATR, signaling strong institutional participation.
"""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict._atr import IncrementalATR
from controllers.common.ict._types import DisplacementEvent

_ZERO = Decimal("0")


class DisplacementDetector:
    """O(1) per-bar displacement detector."""

    __slots__ = ("_atr", "_atr_mult", "_bar_idx", "_events")

    def __init__(
        self,
        atr_period: int = 14,
        atr_mult: Decimal = Decimal("2.0"),
    ) -> None:
        self._atr = IncrementalATR(period=atr_period)
        self._atr_mult = atr_mult
        self._bar_idx: int = 0
        self._events: list[DisplacementEvent] = []

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = _ZERO,
    ) -> DisplacementEvent | None:
        """Feed one OHLCV bar.  Returns a DisplacementEvent if the candle
        body exceeds ``atr_mult * ATR``."""
        self._atr.add_bar(high, low, close)
        self._bar_idx += 1

        if self._atr.count < 2:
            return None

        body = abs(close - open_)
        atr_val = self._atr.value
        if atr_val <= _ZERO:
            return None

        ratio = body / atr_val
        if ratio >= self._atr_mult:
            direction = +1 if close > open_ else -1
            event = DisplacementEvent(
                index=self._bar_idx - 1,
                direction=direction,
                body_atr_ratio=ratio,
            )
            self._events.append(event)
            return event
        return None

    @property
    def events(self) -> list[DisplacementEvent]:
        return list(self._events)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._atr.reset()
        self._bar_idx = 0
        self._events.clear()
