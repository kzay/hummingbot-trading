"""Shared incremental ATR helper.

Extracted from ``controllers.backtesting.smc_mm_adapter._IncrementalATR``
so it can be reused by ICT detectors (DisplacementDetector, ICTState)
and the original adapter without duplication.
"""
from __future__ import annotations

from decimal import Decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")


class IncrementalATR:
    """O(1) per-bar EMA-based ATR.

    Uses exponential smoothing with ``alpha = 2 / (period + 1)``.
    First bar seeds ATR as ``high - low``.
    """

    __slots__ = ("_alpha", "_atr", "_count", "_prev_close")

    def __init__(self, period: int = 14) -> None:
        self._alpha: Decimal = _TWO / Decimal(period + 1)
        self._atr: Decimal = _ZERO
        self._prev_close: Decimal = _ZERO
        self._count: int = 0

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        if self._count == 0:
            self._atr = high - low
            self._prev_close = close
            self._count += 1
            return
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._atr = self._alpha * tr + (_ONE - self._alpha) * self._atr
        self._prev_close = close
        self._count += 1

    @property
    def value(self) -> Decimal:
        return self._atr

    @property
    def count(self) -> int:
        return self._count

    def reset(self) -> None:
        self._atr = _ZERO
        self._prev_close = _ZERO
        self._count = 0
