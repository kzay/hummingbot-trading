"""MM Grid execution adapter — symmetric/skewed market-making grid.

Translates TradingSignal with family="mm_grid" into limit orders
on both sides with spread competitiveness cap and inventory skew.
"""

from __future__ import annotations

from decimal import Decimal

from controllers.runtime.v3.orders import DeskAction, DeskOrder
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")


class MMGridExecutionAdapter:
    """Market-making grid adapter.

    Produces limit orders on both buy and sell sides, with:
    - Spread competitiveness cap (don't quote tighter than N * market spread)
    - Inventory skew (widen on over-exposed side, tighten on under-exposed)
    - Size scaling per level
    """

    def __init__(
        self,
        *,
        spread_cap_mult: Decimal = Decimal("3"),
        skew_intensity: Decimal = Decimal("0.5"),
    ) -> None:
        self._spread_cap_mult = spread_cap_mult
        self._skew_intensity = skew_intensity

    def translate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> list[DeskOrder]:
        if signal.family == "no_trade" or not signal.levels:
            return []

        mid = snapshot.mid
        if mid <= _ZERO:
            return []

        market_spread = snapshot.order_book.spread_pct
        target_pct = signal.target_net_base_pct
        current_pct = snapshot.position.net_base_pct
        inventory_delta = current_pct - target_pct

        orders: list[DeskOrder] = []
        for level in signal.levels:
            spread = level.spread_pct

            # Spread competitiveness cap
            if market_spread > _ZERO:
                cap = market_spread * self._spread_cap_mult
                if spread < cap:
                    spread = cap

            # Inventory skew: widen on over-exposed side
            skew_adj = inventory_delta * self._skew_intensity
            if level.side == "buy":
                spread = spread + max(_ZERO, skew_adj)
                price = mid * (_ONE - spread)
            else:
                spread = spread + max(_ZERO, -skew_adj)
                price = mid * (_ONE + spread)

            orders.append(DeskOrder(
                side=level.side,
                order_type="limit",
                price=price,
                amount_quote=level.size_quote,
                level_id=level.level_id,
            ))

        return orders

    def manage_trailing(
        self,
        position: PositionSnapshot,
        signal: TradingSignal,
    ) -> list[DeskAction]:
        # MM grid doesn't use trailing stops
        return []


__all__ = ["MMGridExecutionAdapter"]
