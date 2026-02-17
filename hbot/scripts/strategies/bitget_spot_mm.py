"""
Bitget Spot Market Making Strategy - Template

This is a PMM (Pure Market Making) script template for Bitget Spot.
Place this file in data/botX/scripts/ or mount via custom_strategies.

Usage in Hummingbot CLI:
  >>> start --script bitget_spot_mm.py
"""

import logging
from decimal import Decimal
from typing import Dict, List

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class BitgetSpotMM(ScriptStrategyBase):
    """
    Simple market-making strategy for Bitget Spot.
    Places bid/ask orders around the mid-price with configurable spread and size.
    """

    # ---- Configuration ----
    trading_pair: str = "BTC-USDT"
    exchange: str = "bitget"
    order_amount: Decimal = Decimal("0.001")
    bid_spread: Decimal = Decimal("0.002")       # 0.2%
    ask_spread: Decimal = Decimal("0.002")       # 0.2%
    order_refresh_time: int = 30                  # seconds
    max_order_age: int = 120                      # seconds
    price_source: PriceType = PriceType.MidPrice

    # Internal state
    create_timestamp: float = 0

    markets: Dict[str, set] = {
        "bitget": {trading_pair}
    }

    def on_tick(self) -> None:
        """Called on every tick (1 second by default)."""
        if self.create_timestamp <= self.current_timestamp:
            self.cancel_all_orders()
            proposal: List[OrderCandidate] = self.create_proposal()
            proposal = self.adjust_proposal_to_budget(proposal)
            self.place_orders(proposal)
            self.create_timestamp = self.current_timestamp + self.order_refresh_time

    def create_proposal(self) -> List[OrderCandidate]:
        """Create bid and ask order candidates."""
        ref_price = self.connectors[self.exchange].get_price_by_type(
            self.trading_pair, self.price_source
        )

        buy_price = ref_price * (Decimal("1") - self.bid_spread)
        sell_price = ref_price * (Decimal("1") + self.ask_spread)

        buy_order = OrderCandidate(
            trading_pair=self.trading_pair,
            is_maker=True,
            order_type=OrderType.LIMIT,
            order_side=TradeType.BUY,
            amount=self.order_amount,
            price=buy_price,
        )

        sell_order = OrderCandidate(
            trading_pair=self.trading_pair,
            is_maker=True,
            order_type=OrderType.LIMIT,
            order_side=TradeType.SELL,
            amount=self.order_amount,
            price=sell_price,
        )

        return [buy_order, sell_order]

    def adjust_proposal_to_budget(
        self, proposal: List[OrderCandidate]
    ) -> List[OrderCandidate]:
        """Adjust orders to available budget."""
        return self.connectors[self.exchange].budget_checker.adjust_candidates(
            proposal, all_or_none=False
        )

    def place_orders(self, proposal: List[OrderCandidate]) -> None:
        """Place the proposed orders."""
        for order in proposal:
            if order.amount > Decimal("0"):
                if order.order_side == TradeType.BUY:
                    self.buy(
                        connector_name=self.exchange,
                        trading_pair=order.trading_pair,
                        amount=order.amount,
                        order_type=order.order_type,
                        price=order.price,
                    )
                else:
                    self.sell(
                        connector_name=self.exchange,
                        trading_pair=order.trading_pair,
                        amount=order.amount,
                        order_type=order.order_type,
                        price=order.price,
                    )

    def cancel_all_orders(self) -> None:
        """Cancel all active orders."""
        for order in self.get_active_orders(connector_name=self.exchange):
            self.cancel(self.exchange, order.trading_pair, order.client_order_id)

    def on_order_filled(self, event: OrderFilledEvent) -> None:
        """Called when an order is filled."""
        msg = (
            f"Order filled: {event.trade_type.name} {event.amount} "
            f"{event.trading_pair} @ {event.price}"
        )
        self.logger().info(msg)
        self.notify_hb_app_with_timestamp(msg)

    def format_status(self) -> str:
        """Custom status output for the `status` command."""
        if not self.ready_to_trade:
            return "Market connectors are not ready."

        lines = []
        mid_price = self.connectors[self.exchange].get_price_by_type(
            self.trading_pair, PriceType.MidPrice
        )
        lines.append(f"  Exchange: {self.exchange}")
        lines.append(f"  Trading Pair: {self.trading_pair}")
        lines.append(f"  Mid Price: {mid_price:.2f}")
        lines.append(f"  Bid Spread: {self.bid_spread:.4f}")
        lines.append(f"  Ask Spread: {self.ask_spread:.4f}")
        lines.append(f"  Order Amount: {self.order_amount}")

        active_orders = self.get_active_orders(connector_name=self.exchange)
        lines.append(f"  Active Orders: {len(active_orders)}")
        for order in active_orders:
            lines.append(
                f"    {order.trade_type.name} {order.amount} @ {order.price}"
            )

        balances = self.connectors[self.exchange].get_all_balances()
        lines.append("  Balances:")
        for asset, balance in balances.items():
            if balance > Decimal("0"):
                lines.append(f"    {asset}: {balance}")

        return "\n".join(lines)
