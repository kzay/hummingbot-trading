"""Optimal Trade Entry (OTE) detector.

OTE zones lie in the 62%--79% Fibonacci retracement of the last impulse
move.  Signals are enhanced when confluence with FVG, OB, or displacement
events is present.

Marked as experimental -- confluence scoring is intentionally simple
until validated via backtest ledger.
"""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict._types import SwingEvent

_ZERO = Decimal("0")
_FIB_62 = Decimal("0.618")
_FIB_79 = Decimal("0.786")


class OTEDetector:
    """Fibonacci retracement zone detector for OTE."""

    __slots__ = (
        "_bar_idx",
        "_impulse_direction",
        "_last_impulse_high",
        "_last_impulse_low",
        "_ote_bottom",
        "_ote_top",
    )

    def __init__(self) -> None:
        self._last_impulse_high: Decimal | None = None
        self._last_impulse_low: Decimal | None = None
        self._impulse_direction: int = 0
        self._ote_top: Decimal = _ZERO
        self._ote_bottom: Decimal = _ZERO
        self._bar_idx: int = 0

    def on_swing(self, swing: SwingEvent) -> None:
        """Update impulse range from swings.  The OTE zone is
        recalculated whenever both a swing high and swing low exist."""
        if swing.direction == +1:
            self._last_impulse_high = swing.level
            self._impulse_direction = +1
        else:
            self._last_impulse_low = swing.level
            self._impulse_direction = -1

        self._recalculate()

    def _recalculate(self) -> None:
        if self._last_impulse_high is None or self._last_impulse_low is None:
            return
        range_size = self._last_impulse_high - self._last_impulse_low
        if range_size <= _ZERO:
            return
        if self._impulse_direction == +1:
            # Bullish impulse: OTE retracement is below the high
            self._ote_top = self._last_impulse_high - range_size * _FIB_62
            self._ote_bottom = self._last_impulse_high - range_size * _FIB_79
        else:
            # Bearish impulse: OTE retracement is above the low
            self._ote_bottom = self._last_impulse_low + range_size * _FIB_62
            self._ote_top = self._last_impulse_low + range_size * _FIB_79

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = _ZERO,
    ) -> None:
        self._bar_idx += 1

    def in_ote_zone(self, price: Decimal) -> bool:
        """True if price is within the OTE retracement zone."""
        if self._ote_top == _ZERO and self._ote_bottom == _ZERO:
            return False
        return self._ote_bottom <= price <= self._ote_top

    @property
    def ote_top(self) -> Decimal:
        return self._ote_top

    @property
    def ote_bottom(self) -> Decimal:
        return self._ote_bottom

    @property
    def impulse_direction(self) -> int:
        return self._impulse_direction

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._last_impulse_high = None
        self._last_impulse_low = None
        self._impulse_direction = 0
        self._ote_top = _ZERO
        self._ote_bottom = _ZERO
        self._bar_idx = 0
