"""Generic fill simulator for backtesting.

Evaluates order intents against bar data to determine fills, applying
conservative fill assumptions (no look-ahead bias).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from scripts.backtest.harness.data_provider import BarData
from scripts.backtest.harness.strategy_adapter import OrderIntent
from services.common.utils import to_decimal


@dataclass(frozen=True)
class SimulatedFill:
    """Result of a simulated fill."""
    side: str
    price: Decimal
    amount: Decimal
    fee_quote: Decimal
    level_id: str
    is_maker: bool


class FillSimulator:
    """Conservative fill model for backtesting.

    Only fills limit orders when the opposing book side price crosses
    the order price.  Applies configurable slippage and maker/taker fees.
    """

    def __init__(
        self,
        maker_fee_pct: Decimal = Decimal("0.001"),
        taker_fee_pct: Decimal = Decimal("0.001"),
        slippage_bps: Decimal = Decimal("1.0"),
        max_fill_ratio: Decimal = Decimal("0.5"),
    ):
        self._maker_fee = maker_fee_pct
        self._taker_fee = taker_fee_pct
        self._slippage_bps = slippage_bps
        self._max_fill_ratio = max_fill_ratio

    def evaluate(self, intent: OrderIntent, bar: BarData) -> Optional[SimulatedFill]:
        """Try to fill *intent* against *bar*.  Returns ``None`` if no fill."""
        if intent.amount <= 0 or intent.price <= 0:
            return None

        is_cross = False
        if intent.side == "buy":
            is_cross = intent.price >= bar.ask_price
            if not is_cross:
                return None
        elif intent.side == "sell":
            is_cross = intent.price <= bar.bid_price
            if not is_cross:
                return None
        else:
            return None

        fill_amount = intent.amount * self._max_fill_ratio
        slippage_mult = self._slippage_bps / Decimal("10000")
        if intent.side == "buy":
            fill_price = bar.ask_price * (Decimal("1") + slippage_mult)
        else:
            fill_price = bar.bid_price * (Decimal("1") - slippage_mult)

        fee_rate = self._taker_fee if is_cross else self._maker_fee
        fee_quote = fill_amount * fill_price * fee_rate

        return SimulatedFill(
            side=intent.side,
            price=fill_price,
            amount=fill_amount,
            fee_quote=fee_quote,
            level_id=intent.level_id,
            is_maker=not is_cross,
        )
