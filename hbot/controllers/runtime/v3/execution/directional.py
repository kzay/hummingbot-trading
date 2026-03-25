"""Directional execution adapter — single-side entries with barriers.

Translates TradingSignal with family="directional" into limit or market
orders on one side, with ATR-scaled stop-loss and take-profit.

Includes a trailing stop state machine migrated from bot7's
_manage_trailing_stop():
  inactive → tracking (when PnL >= activate_threshold)
  tracking → triggered (when retrace >= trail_offset)
  triggered → emits ClosePosition → resets to inactive
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from controllers.runtime.v3.orders import ClosePosition, DeskAction, DeskOrder, PartialReduce
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot

_ZERO = Decimal("0")
_ONE = Decimal("1")
_EPSILON = Decimal("1e-8")


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
        trail_activate_atr_mult: Decimal = Decimal("1.0"),
        trail_offset_atr_mult: Decimal = Decimal("0.5"),
        trailing_enabled: bool = True,
    ) -> None:
        self._sl_atr_mult = sl_atr_mult
        self._tp_atr_mult = tp_atr_mult
        self._time_limit_s = time_limit_s
        self._partial_tp_ratio = partial_tp_ratio
        self._trail_activate_atr_mult = trail_activate_atr_mult
        self._trail_offset_atr_mult = trail_offset_atr_mult
        self._trailing_enabled = trailing_enabled

        # Trailing state machine
        self._trail_state: Literal["inactive", "tracking", "triggered"] = "inactive"
        self._trail_hwm: Decimal = _ZERO
        self._trail_lwm: Decimal = Decimal("999999999")
        self._trail_entry_price: Decimal = _ZERO
        self._trail_entry_side: str = "off"
        self._trail_sl_distance: Decimal = _ZERO
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

        # Record SL distance for partial TP trigger (1R)
        if stop_loss is not None and mid > _ZERO:
            self._trail_sl_distance = stop_loss / mid

        # Record entry for trailing stop
        if self._trail_entry_price <= _ZERO and signal.direction in ("buy", "sell"):
            self._trail_entry_price = mid
            self._trail_entry_side = signal.direction

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
        mid: Decimal = _ZERO,
    ) -> list[DeskAction]:
        """Trailing stop state machine with partial take-profit.

        State transitions:
          inactive → tracking: when unrealized PnL >= activate_threshold
          tracking → triggered: when retrace from HWM/LWM >= trail_offset
          triggered: emits ClosePosition, resets state
        """
        if not self._trailing_enabled:
            return []

        if abs(position.base_amount) < _EPSILON:
            if self._trail_state != "inactive":
                self._reset_trail()
            return []

        if mid <= _ZERO:
            return []

        entry = self._trail_entry_price
        if entry <= _ZERO:
            entry = position.avg_entry_price
        if entry <= _ZERO:
            return []

        entry_side = self._trail_entry_side
        if entry_side == "off":
            entry_side = "buy" if position.base_amount > _ZERO else "sell"

        atr = signal.metadata.get("atr", _ZERO)
        if isinstance(atr, (int, float)):
            atr = Decimal(str(atr))
        if atr <= _ZERO:
            return []

        actions: list[DeskAction] = []

        # Compute unrealized PnL pct
        if entry_side == "buy":
            pnl_pct = (mid - entry) / entry
        elif entry_side == "sell":
            pnl_pct = (entry - mid) / entry
        else:
            return []

        # ── Partial profit-taking at 1R ──
        if not self._partial_taken and self._trail_sl_distance > _ZERO:
            if pnl_pct >= self._trail_sl_distance:
                actions.append(PartialReduce(
                    reduce_ratio=self._partial_tp_ratio,
                    reason="pb_partial_take",
                ))
                self._partial_taken = True

        # ── Trailing stop state machine ──
        activate_threshold = self._trail_activate_atr_mult * atr / mid
        trail_offset = self._trail_offset_atr_mult * atr

        if self._trail_state == "inactive":
            if pnl_pct >= activate_threshold:
                self._trail_state = "tracking"
                if entry_side == "buy":
                    self._trail_hwm = mid
                else:
                    self._trail_lwm = mid

        elif self._trail_state == "tracking":
            if entry_side == "buy":
                if mid > self._trail_hwm:
                    self._trail_hwm = mid
                retrace = self._trail_hwm - mid
                if retrace >= trail_offset:
                    self._trail_state = "triggered"
            else:  # sell
                if mid < self._trail_lwm:
                    self._trail_lwm = mid
                retrace = mid - self._trail_lwm
                if retrace >= trail_offset:
                    self._trail_state = "triggered"

        if self._trail_state == "triggered":
            actions.append(ClosePosition(reason="pb_trail_close"))
            self._reset_trail()

        return actions

    @property
    def trail_state(self) -> str:
        return self._trail_state

    def _reset_trail(self) -> None:
        self._trail_state = "inactive"
        self._trail_hwm = _ZERO
        self._trail_lwm = Decimal("999999999")
        self._trail_entry_price = _ZERO
        self._trail_entry_side = "off"
        self._trail_sl_distance = _ZERO
        self._partial_taken = False


__all__ = ["DirectionalExecutionAdapter"]
