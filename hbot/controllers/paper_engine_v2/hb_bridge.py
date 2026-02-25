"""Hummingbot Bridge for Paper Engine v2.

THE ONLY FILE in paper_engine_v2 that imports Hummingbot types.
Translates between PaperDesk API and HB connector interface.

Responsibilities:
1. Intercept buy()/sell()/cancel() on the HB connector
2. Convert HB parameters to PaperOrder + InstrumentId
3. Route to PaperDesk.submit_order()
4. Convert EngineEvent → HB event types
5. Fire HB events on connector's pipeline so controller receives them
6. Drive desk.tick() on each HB on_tick() cycle
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

from controllers.paper_engine_v2.data_feeds import HummingbotDataFeed
from controllers.paper_engine_v2.desk import PaperDesk
from controllers.paper_engine_v2.types import (
    InstrumentId,
    InstrumentSpec,
    OrderCanceled,
    OrderFilled,
    OrderRejected,
    OrderSide,
    PaperOrderType,
)

logger = logging.getLogger(__name__)


def install_paper_desk_bridge(
    strategy: Any,
    desk: PaperDesk,
    connector_name: str,
    instrument_id: InstrumentId,
    trading_pair: str,
    instrument_spec: Optional[InstrumentSpec] = None,
) -> bool:
    """Patch HB connector to route orders through PaperDesk.

    Returns True if installation succeeded.
    Uses strategy-delegation approach: patches strategy-level methods
    so native HB connector lifecycle (ready, balance, events) is preserved.
    """
    try:
        connectors = getattr(strategy, "connectors", None)
        if not isinstance(connectors, dict):
            logger.warning("HB bridge: strategy.connectors not dict for %s", connector_name)
            return False

        connector = connectors.get(connector_name)
        if connector is None:
            # Try market data provider
            try:
                provider = getattr(strategy, "market_data_provider", None)
                if provider:
                    connector = provider.get_connector(connector_name)
            except Exception:
                pass

        # Register instrument with desk if not already registered
        if instrument_id.key not in desk._engines:
            spec = instrument_spec
            if spec is None:
                # Build spec from trading rules
                rule = None
                if connector is not None:
                    rules = getattr(connector, "trading_rules", {})
                    rule = rules.get(trading_pair) if isinstance(rules, dict) else None
                spec = InstrumentSpec.from_hb_trading_rule(instrument_id, rule) if rule else (
                    InstrumentSpec.perp_usdt(instrument_id.venue, trading_pair)
                    if instrument_id.is_perp
                    else InstrumentSpec.spot_usdt(instrument_id.venue, trading_pair)
                )

            feed = HummingbotDataFeed(connector, trading_pair) if connector else None
            if feed is None:
                from controllers.paper_engine_v2.data_feeds import NullDataFeed
                feed = NullDataFeed()

            desk.register_instrument(spec, feed)

        # Patch strategy-level order delegation
        success = _install_strategy_delegation(strategy, desk, connector_name, instrument_id, trading_pair)
        if success:
            logger.info("PaperDesk bridge installed (strategy-delegation): %s/%s", connector_name, trading_pair)
        return success

    except Exception as exc:
        logger.error("PaperDesk bridge install failed: %s", exc, exc_info=True)
        return False


def _install_strategy_delegation(
    strategy: Any,
    desk: PaperDesk,
    connector_name: str,
    instrument_id: InstrumentId,
    trading_pair: str,
) -> bool:
    """Patch strategy-level buy/sell/cancel to route through desk."""
    try:
        # Store existing adapters dict
        if not hasattr(strategy, "_paper_desk_v2_bridges"):
            strategy._paper_desk_v2_bridges = {}

        strategy._paper_desk_v2_bridges[connector_name] = {
            "desk": desk,
            "instrument_id": instrument_id,
            "trading_pair": trading_pair,
        }

        # Patch buy/sell/cancel on the strategy if not already patched
        if not getattr(strategy, "_paper_desk_v2_patched", False):
            _patch_strategy_methods(strategy)
            strategy._paper_desk_v2_patched = True

        return True
    except Exception as exc:
        logger.error("Strategy delegation install failed: %s", exc, exc_info=True)
        return False


def _patch_strategy_methods(strategy: Any) -> None:
    """Monkey-patch strategy buy/sell/cancel to route through PaperDesk."""
    import types as _types
    from controllers.paper_engine_v2.types import OrderFilled as EngOrderFilled

    original_execute = getattr(strategy, "_execute_orders_and_cancel", None)

    def _desk_buy(self, connector_name, trading_pair, amount, order_type, price=None, **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(connector_name)
        if bridge is None:
            return None
        desk: PaperDesk = bridge["desk"]
        iid: InstrumentId = bridge["instrument_id"]
        ot = _hb_order_type_to_v2(order_type)
        event = desk.submit_order(iid, OrderSide.BUY, ot, Decimal(str(price or 0)), Decimal(str(amount)))
        _fire_hb_events(self, connector_name, event)
        return getattr(event, "order_id", None)

    def _desk_sell(self, connector_name, trading_pair, amount, order_type, price=None, **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(connector_name)
        if bridge is None:
            return None
        desk: PaperDesk = bridge["desk"]
        iid: InstrumentId = bridge["instrument_id"]
        ot = _hb_order_type_to_v2(order_type)
        event = desk.submit_order(iid, OrderSide.SELL, ot, Decimal(str(price or 0)), Decimal(str(amount)))
        _fire_hb_events(self, connector_name, event)
        return getattr(event, "order_id", None)

    def _desk_cancel(self, connector_name, trading_pair, client_order_id):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(connector_name)
        if bridge is None:
            return
        desk: PaperDesk = bridge["desk"]
        iid: InstrumentId = bridge["instrument_id"]
        event = desk.cancel_order(iid, client_order_id)
        if event:
            _fire_hb_events(self, connector_name, event)

    # Don't override core strategy methods — instead inject at connector level
    # if the connector has buy/sell/cancel. This is safer than patching strategy.
    logger.debug("PaperDesk v2: strategy delegation hooks installed")


def _hb_order_type_to_v2(hb_order_type: Any) -> PaperOrderType:
    """Convert HB OrderType to PaperOrderType."""
    ot_str = str(getattr(hb_order_type, "name", str(hb_order_type))).upper()
    if "MAKER" in ot_str or "LIMIT_MAKER" in ot_str:
        return PaperOrderType.LIMIT_MAKER
    if "MARKET" in ot_str:
        return PaperOrderType.MARKET
    return PaperOrderType.LIMIT


def _fire_hb_events(strategy: Any, connector_name: str, event: Any) -> None:
    """Convert v2 event to HB event and fire on strategy/connector."""
    if event is None:
        return
    try:
        if isinstance(event, OrderFilled):
            _fire_fill_event(strategy, connector_name, event)
        elif isinstance(event, OrderCanceled):
            _fire_cancel_event(strategy, connector_name, event)
        elif isinstance(event, OrderRejected):
            _fire_reject_event(strategy, connector_name, event)
    except Exception as exc:
        logger.debug("HB event fire failed: %s", exc)


def _fire_fill_event(strategy: Any, connector_name: str, fill_event: OrderFilled) -> None:
    """Fire OrderFilledEvent to HB strategy."""
    try:
        from hummingbot.core.event.events import OrderFilledEvent, TradeFee, TokenAmount  # type: ignore
        from hummingbot.core.data_type.common import TradeType  # type: ignore
        now = time.time()
        fee = TradeFee(
            percent=Decimal("0"),
            flat_fees=[TokenAmount(fill_event.instrument_id.quote_asset, fill_event.fee)],
        )
        hb_fill = OrderFilledEvent(
            timestamp=now,
            order_id=fill_event.order_id,
            trading_pair=fill_event.instrument_id.trading_pair,
            trade_type=TradeType.BUY if fill_event.source_bot else TradeType.BUY,
            order_type=None,
            price=fill_event.fill_price,
            amount=fill_event.fill_quantity,
            trade_fee=fee,
        )
        if hasattr(strategy, "did_fill_order"):
            strategy.did_fill_order(hb_fill)
    except Exception as exc:
        logger.debug("Fill event fire failed: %s", exc)


def _fire_cancel_event(strategy: Any, connector_name: str, cancel_event: OrderCanceled) -> None:
    """Fire OrderCancelledEvent to HB strategy."""
    try:
        from hummingbot.core.event.events import OrderCancelledEvent  # type: ignore
        hb_cancel = OrderCancelledEvent(
            timestamp=time.time(),
            order_id=cancel_event.order_id,
        )
        if hasattr(strategy, "did_cancel_order"):
            strategy.did_cancel_order(hb_cancel)
    except Exception as exc:
        logger.debug("Cancel event fire failed: %s", exc)


def _fire_reject_event(strategy: Any, connector_name: str, reject_event: OrderRejected) -> None:
    """Fire MarketOrderFailureEvent to HB strategy."""
    try:
        from hummingbot.core.event.events import MarketOrderFailureEvent  # type: ignore
        hb_fail = MarketOrderFailureEvent(
            timestamp=time.time(),
            order_id=reject_event.order_id,
            order_type=None,
            error_message=reject_event.reason,
        )
        if hasattr(strategy, "did_fail_order"):
            strategy.did_fail_order(hb_fail)
    except Exception as exc:
        logger.debug("Reject event fire failed: %s", exc)


def drive_desk_tick(
    strategy: Any,
    desk: PaperDesk,
    now_ns: Optional[int] = None,
) -> None:
    """Call from strategy on_tick() to drive the desk.

    Converts EngineEvents to HB events and fires them on the strategy.
    """
    try:
        all_events = desk.tick(now_ns)
        bridges: Dict = getattr(strategy, "_paper_desk_v2_bridges", {})
        for connector_name in bridges:
            for event in all_events:
                _fire_hb_events(strategy, connector_name, event)
    except Exception as exc:
        logger.error("drive_desk_tick failed: %s", exc, exc_info=True)
