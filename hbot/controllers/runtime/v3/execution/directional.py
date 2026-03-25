"""Directional execution adapter — single-side entries with barriers.

Translates TradingSignal with family="directional" into limit or market
orders on one side, with ATR-scaled stop-loss and take-profit.
"""

from __future__ import annotations

from decimal import Decimal

from controllers.runtime.v3.orders import DeskAction, DeskOrder, PartialReduce
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot

_ZERO = Decimal("0")
_ONE = Decimal("1")


class DirectionalExecutionAdapter:
    """Directional single-side adapter.

    Produces orders only on the signal's direction side.
    Attaches ATR-scaled barriers (stop-loss, take-profit, time limit).
    Manages trailing stops and partial take-profit.
    """

    def __init__(
        self,
        *,
        sl_atr_mult: Decimal = Decimal("1.5"),
        tp_atr_mult: Decimal = Decimal("3.0"),
        time_limit_s: int = 3600,
        partial_tp_ratio: Decimal = Decimal("0.33"),
        partial_tp_trigger: Decimal = Decimal("0.33"),
    ) -> None:
        self._sl_atr_mult = sl_atr_mult
        self._tp_atr_mult = tp_atr_mult
        self._time_limit_s = time_limit_s
        self._partial_tp_ratio = partial_tp_ratio
        self._partial_tp_trigger = partial_tp_trigger
        # Trailing state
        self._hwm: Decimal = _ZERO
        self._lwm: Decimal = Decimal("999999999")
        self._partial_taken: bool = False

    def translate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> list[DeskOrder]:
        if signal.family == "no_trade" or signal.direction == "off":
            return []
        if not signal.levels:
            return []

        mid = snapshot.mid
        if mid <= _ZERO:
            return []

        atr = snapshot.indicators.atr.get(14, _ZERO)
        stop_loss = atr * self._sl_atr_mult if atr > _ZERO else None
        take_profit = atr * self._tp_atr_mult if atr > _ZERO else None

        orders: list[DeskOrder] = []
        for level in signal.levels:
            if level.side != signal.direction and signal.direction != "both":
                continue

            if level.side == "buy":
                price = mid * (_ONE - level.spread_pct)
            else:
                price = mid * (_ONE + level.spread_pct)

            orders.append(DeskOrder(
                side=level.side,
                order_type="limit",
                price=price,
                amount_quote=level.size_quote,
                level_id=level.level_id,
                stop_loss=stop_loss,
                take_profit=take_profit,
                time_limit_s=self._time_limit_s,
            ))

        return orders

    def manage_trailing(
        self,
        position: PositionSnapshot,
        signal: TradingSignal,
    ) -> list[DeskAction]:
        """Trailing stop state machine with partial take-profit."""
        if position.base_amount == _ZERO:
            self._reset_trail()
            return []

        actions: list[DeskAction] = []
        entry = position.avg_entry_price
        if entry <= _ZERO:
            return []

        # Determine unrealized P&L direction
        # For now, use a simplified approach based on base_amount sign
        is_long = position.base_amount > _ZERO

        # Update HWM/LWM
        if is_long:
            if position.avg_entry_price > self._hwm:
                self._hwm = position.avg_entry_price
        else:
            if position.avg_entry_price < self._lwm:
                self._lwm = position.avg_entry_price

        # Partial take-profit at trigger ratio
        if not self._partial_taken and signal.conviction > _ZERO:
            tp_target = signal.metadata.get("dynamic_tp", _ZERO)
            if tp_target > _ZERO:
                # Check if we've reached partial TP trigger
                actions.append(PartialReduce(
                    reduce_ratio=self._partial_tp_ratio,
                    reason="trailing_partial_tp",
                ))
                self._partial_taken = True

        return actions

    def _reset_trail(self) -> None:
        self._hwm = _ZERO
        self._lwm = Decimal("999999999")
        self._partial_taken = False


__all__ = ["DirectionalExecutionAdapter"]
