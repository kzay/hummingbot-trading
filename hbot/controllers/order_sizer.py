"""Order sizing, quantization, and notional projection for EPP v2.4.

All financial values use ``Decimal`` to avoid float precision loss in the
order pricing pipeline.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Optional

from hummingbot.core.data_type.common import TradeType

from services.common.utils import to_decimal


class OrderSizer:
    """Handles order amount/price quantization and notional limit enforcement."""

    def __init__(
        self,
        max_order_notional_quote: Decimal,
        max_total_notional_quote: Decimal,
    ):
        self._max_order_notional = max_order_notional_quote
        self._max_total_notional = max_total_notional_quote

    def quantize_price(self, price: Decimal, side: TradeType, rule: Any) -> Decimal:
        """Quantize *price* to the trading rule's tick size."""
        if rule is None or price <= 0:
            return price
        step = Decimal("0")
        for attr in ("min_price_increment", "min_price_tick_size", "price_step", "min_price_step"):
            value = getattr(rule, attr, None)
            if value is not None:
                step = to_decimal(value)
                break
        if step <= 0:
            return price
        rounding = ROUND_DOWN if side == TradeType.BUY else ROUND_UP
        steps = (price / step).to_integral_value(rounding=rounding)
        return max(step, steps * step)

    def quantize_amount(self, amount: Decimal, rule: Any, rounding: str = ROUND_DOWN) -> Decimal:
        """Quantize *amount* to the trading rule's lot step."""
        if rule is None or amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        for attr in ("min_order_size", "min_base_amount", "min_amount"):
            value = getattr(rule, attr, None)
            if value is not None:
                min_amount = max(min_amount, to_decimal(value))
        for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
            value = getattr(rule, attr, None)
            if value is not None:
                step = to_decimal(value)
                break
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=rounding)
            q_amount = max(min_amount, units * step)
        return q_amount

    def min_notional_quote(self, rule: Any) -> Decimal:
        """Return the exchange's minimum order notional (in quote)."""
        if rule is None:
            return Decimal("0")
        for attr in ("min_notional_size", "min_notional", "min_order_value"):
            value = getattr(rule, attr, None)
            if value is not None:
                return to_decimal(value)
        return Decimal("0")

    def project_total_amount_quote(
        self,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        total_levels: int,
        rule: Any,
    ) -> Decimal:
        """Estimate total order notional for risk check purposes."""
        min_notional = self.min_notional_quote(rule)
        per_order_quote = max(min_notional, equity_quote * quote_size_pct)
        if self._max_order_notional > 0:
            per_order_quote = min(per_order_quote, self._max_order_notional)
        projected = per_order_quote * Decimal(max(1, total_levels))
        if self._max_total_notional > 0:
            projected = min(projected, self._max_total_notional)
        min_base = min_notional / mid if min_notional > 0 and mid > 0 else Decimal("0")
        if min_base > 0 and mid > 0 and projected > 0 and (projected / mid) < min_base:
            projected = min_base * mid
        return projected
