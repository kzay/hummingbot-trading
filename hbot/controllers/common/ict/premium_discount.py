"""Premium / Discount zone calculator.

Given the most recent swing range (swing high to swing low), divides the
range into Fibonacci levels:
  - Premium zone: above the 50% (equilibrium) level.
  - Discount zone: below the 50% level.

Standard ICT Fibonacci levels: 0%, 23.6%, 38.2%, 50%, 61.8%, 76.4%, 100%.
"""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict._types import SwingEvent

_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_FIB_LEVELS = [
    Decimal("0"),
    Decimal("0.236"),
    Decimal("0.382"),
    Decimal("0.5"),
    Decimal("0.618"),
    Decimal("0.764"),
    Decimal("1"),
]


class PremiumDiscountZone:
    """Stateless zone calculator driven by swing updates."""

    __slots__ = ("_bar_idx", "_equilibrium", "_fib_prices", "_swing_high", "_swing_low")

    def __init__(self) -> None:
        self._swing_high: Decimal | None = None
        self._swing_low: Decimal | None = None
        self._equilibrium: Decimal = _ZERO
        self._fib_prices: dict[str, Decimal] = {}
        self._bar_idx: int = 0

    def on_swing(self, swing: SwingEvent) -> None:
        """Update range from latest swing."""
        if swing.direction == +1:
            self._swing_high = swing.level
        else:
            self._swing_low = swing.level

        if self._swing_high is not None and self._swing_low is not None:
            range_size = self._swing_high - self._swing_low
            if range_size > _ZERO:
                self._equilibrium = self._swing_low + range_size * _HALF
                self._fib_prices = {
                    f"fib_{fib}": self._swing_low + range_size * fib
                    for fib in _FIB_LEVELS
                }

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = _ZERO,
    ) -> None:
        self._bar_idx += 1

    def zone_for_price(self, price: Decimal) -> str:
        """Returns 'premium', 'discount', or 'equilibrium'."""
        if self._equilibrium == _ZERO:
            return "equilibrium"
        if price > self._equilibrium:
            return "premium"
        elif price < self._equilibrium:
            return "discount"
        return "equilibrium"

    @property
    def equilibrium(self) -> Decimal:
        return self._equilibrium

    @property
    def fib_levels(self) -> dict[str, Decimal]:
        return dict(self._fib_prices)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._swing_high = None
        self._swing_low = None
        self._equilibrium = _ZERO
        self._fib_prices.clear()
        self._bar_idx = 0
