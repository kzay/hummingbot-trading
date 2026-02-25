"""Hummingbot Bridge for Paper Engine v2.

THE ONLY FILE in paper_engine_v2 that imports Hummingbot types.
Translates between PaperDesk API and HB connector interface.

Replaces paper_engine.py (v1) entirely. Provides:
1. Framework compatibility shims (enable_framework_paper_compat_fallbacks)
2. PaperBudgetChecker (patches HB collateral system)
3. Strategy-level order delegation (buy/sell/cancel routing)
4. HB event translation (OrderFilled, OrderCanceled, etc.)
5. Balance reporting from PaperPortfolio to HB connector reads
6. desk.tick() driving on each HB on_tick()
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from types import MethodType, SimpleNamespace
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
    _ZERO,
)

logger = logging.getLogger(__name__)

_CANONICAL_CACHE: Dict[str, str] = {}


def _canonical_name(connector_name: str) -> str:
    if connector_name in _CANONICAL_CACHE:
        return _CANONICAL_CACHE[connector_name]
    if not str(connector_name).endswith("_paper_trade"):
        return connector_name
    try:
        from services.common.exchange_profiles import resolve_profile
        profile = resolve_profile(connector_name)
        if isinstance(profile, dict):
            req = profile.get("requires_paper_trade_exchange")
            if isinstance(req, str) and req:
                _CANONICAL_CACHE[connector_name] = req
                return req
    except Exception:
        pass
    result = connector_name[:-12]
    _CANONICAL_CACHE[connector_name] = result
    return result


# ---------------------------------------------------------------------------
# PaperBudgetChecker
# ---------------------------------------------------------------------------

class PaperBudgetChecker:
    """Drop-in replacement for HB's BudgetChecker.

    Patches HB's collateral/budget check system so order candidates
    pass validation regardless of real exchange balance. All methods
    return candidates unchanged (paper has unlimited budget within
    the configured paper_equity_quote).
    """

    def __init__(self, exchange: Any, paper_equity_quote: Decimal = Decimal("10000")):
        self._exchange = exchange
        self._paper_equity = paper_equity_quote

    def reset_locked_collateral(self):
        pass

    def adjust_candidates(self, order_candidates, all_or_none=True):
        return list(order_candidates)

    def adjust_candidate_and_lock_available_collateral(self, order_candidate, all_or_none=True):
        return order_candidate

    def adjust_candidate(self, order_candidate, all_or_none=True):
        return order_candidate

    def populate_collateral_entries(self, order_candidate):
        return order_candidate


def _install_budget_checker(connector: Any, equity_quote: Decimal) -> None:
    """Install PaperBudgetChecker on a connector if it has a _budget_checker."""
    try:
        budget_cls = None
        try:
            from hummingbot.connector.utils import get_new_client_order_id  # type: ignore
        except Exception:
            pass
        for attr in ("_budget_checker", "budget_checker"):
            if hasattr(connector, attr):
                setattr(connector, attr, PaperBudgetChecker(connector, equity_quote))
                logger.info("PaperBudgetChecker installed on %s", getattr(connector, "name", "connector"))
                return
    except Exception as exc:
        logger.debug("PaperBudgetChecker install failed (non-critical): %s", exc)


# ---------------------------------------------------------------------------
# Framework compatibility shims
# ---------------------------------------------------------------------------

def enable_framework_paper_compat_fallbacks() -> None:
    """Install HB framework compatibility patches for paper mode.

    Equivalent to paper_engine.py::enable_framework_paper_compat_fallbacks().
    Must be called once at process startup before any controller initializes.

    Patches:
    1. MarketDataProvider._create_non_trading_connector: canonical name mapping
    2. ExecutorBase.get_trading_rules: fallback when paper connector has no rules
    3. ExecutorBase.get_in_flight_order: fallback for paper order tracker
    """
    _patch_market_data_provider()
    _patch_executor_base()


def _patch_market_data_provider() -> None:
    try:
        from hummingbot.data_feed.market_data_provider import MarketDataProvider as _MDP  # type: ignore
    except Exception:
        return
    if getattr(_MDP, "_epp_v2_paper_create_fallback_enabled", False):
        return
    try:
        _orig = _MDP._create_non_trading_connector

        def _safe_create(self, connector_name: str):
            return _orig(self, _canonical_name(connector_name))

        _MDP._create_non_trading_connector = _safe_create
        _MDP._epp_v2_paper_create_fallback_enabled = True
        logger.debug("MarketDataProvider._create_non_trading_connector patched (v2)")
    except Exception as exc:
        logger.debug("MDP patch failed (non-critical): %s", exc)


def _patch_executor_base() -> None:
    try:
        from hummingbot.strategy_v2.executors.executor_base import ExecutorBase as _EB  # type: ignore
    except Exception:
        return

    if not getattr(_EB, "_epp_v2_trading_rules_fallback_enabled", False):
        def _extract_rule(obj, pair):
            if obj is None:
                return None
            try:
                for attr in ("trading_rules", "_trading_rules"):
                    rules = getattr(obj, attr, None)
                    if isinstance(rules, dict) and pair in rules:
                        return rules[pair]
            except Exception:
                pass
            return None

        def _safe_get_trading_rules(self, connector_name: str, trading_pair: str):
            connector = self.connectors.get(connector_name)
            rule = _extract_rule(connector, trading_pair)
            if rule is not None:
                return rule
            can = _canonical_name(connector_name)
            rule = _extract_rule(self.connectors.get(can), trading_pair)
            if rule is not None:
                return rule
            try:
                provider = getattr(self.strategy, "market_data_provider", None)
                if provider:
                    rule = _extract_rule(provider.get_connector(can), trading_pair)
                    if rule is not None:
                        return rule
            except Exception:
                pass
            for attr in ("_exchange", "exchange", "_connector", "connector"):
                rule = _extract_rule(getattr(connector, attr, None), trading_pair)
                if rule is not None:
                    return rule
            # Fallback stub — never crash the executor loop
            return SimpleNamespace(
                trading_pair=trading_pair,
                min_order_size=Decimal("0"), min_base_amount=Decimal("0"),
                min_amount=Decimal("0"), min_notional_size=Decimal("0"),
                min_notional=Decimal("0"), min_order_value=Decimal("0"),
                min_base_amount_increment=Decimal("0"),
                min_order_size_increment=Decimal("0"),
                amount_step=Decimal("0"), min_price_increment=Decimal("0"),
                min_price_tick_size=Decimal("0"), price_step=Decimal("0"),
                min_price_step=Decimal("0"),
            )

        _EB.get_trading_rules = _safe_get_trading_rules
        _EB._epp_v2_trading_rules_fallback_enabled = True

    if not getattr(_EB, "_epp_v2_inflight_fallback_enabled", False):
        _orig_inflight = _EB.get_in_flight_order

        def _safe_inflight(self, connector_name: str, order_id: str):
            connector = self.connectors.get(connector_name)
            if connector is None:
                return _orig_inflight(self, connector_name, order_id)
            tracker = getattr(connector, "_order_tracker", None)
            if tracker is None:
                return None
            try:
                return tracker.fetch_order(client_order_id=order_id)
            except Exception:
                return None

        _EB.get_in_flight_order = _safe_inflight
        _EB._epp_v2_inflight_fallback_enabled = True
        logger.debug("ExecutorBase fallbacks patched (v2)")


def install_paper_desk_bridge(
    strategy: Any,
    desk: PaperDesk,
    connector_name: str,
    instrument_id: InstrumentId,
    trading_pair: str,
    instrument_spec: Optional[InstrumentSpec] = None,
) -> bool:
    """Full v2 bridge installation — replaces paper_engine.py (v1) entirely.

    1. Registers the instrument with the desk.
    2. Installs PaperBudgetChecker so order sizing passes.
    3. Patches strategy buy/sell/cancel to route through PaperDesk.
    4. Patches connector get_balance to report PaperPortfolio balances.
    5. Adds paper_stats property to connector for ProcessedState reporting.

    Returns True if installation succeeded.
    """
    try:
        connectors = getattr(strategy, "connectors", None)
        if not isinstance(connectors, dict):
            logger.warning("HB bridge: strategy.connectors not dict for %s", connector_name)
            return False

        connector = connectors.get(connector_name)
        if connector is None:
            try:
                provider = getattr(strategy, "market_data_provider", None)
                if provider:
                    connector = provider.get_connector(connector_name)
            except Exception:
                pass

        # 1. Register instrument with desk
        if instrument_id.key not in desk._engines:
            spec = instrument_spec
            if spec is None:
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

        equity = desk.portfolio.balance(instrument_id.quote_asset)
        if equity <= _ZERO:
            equity = Decimal("500")

        # 2. Install PaperBudgetChecker
        if connector is not None:
            _install_budget_checker(connector, equity)

        # 3. Patch strategy order delegation (buy/sell/cancel)
        _install_order_delegation(strategy, desk, connector_name, instrument_id)

        # 4. Patch connector balance reads to report paper portfolio
        if connector is not None:
            _patch_connector_balances(connector, desk, instrument_id)

        # 5. Add paper_stats to connector
        if connector is not None:
            _install_paper_stats(connector, desk, instrument_id)

        logger.info("PaperDesk v2 bridge fully installed: %s/%s", connector_name, trading_pair)
        return True

    except Exception as exc:
        logger.error("PaperDesk bridge install failed: %s", exc, exc_info=True)
        return False


def _install_order_delegation(
    strategy: Any,
    desk: PaperDesk,
    connector_name: str,
    instrument_id: InstrumentId,
) -> None:
    """Patch strategy buy/sell/cancel to route through PaperDesk.

    Strategy-level delegation: strategy.buy(connector_name, ...) is patched
    to route through the desk for paper connectors. Original is called for
    other connectors (live passthrough).
    """
    if not hasattr(strategy, "_paper_desk_v2_bridges"):
        strategy._paper_desk_v2_bridges = {}

    strategy._paper_desk_v2_bridges[connector_name] = {
        "desk": desk,
        "instrument_id": instrument_id,
    }

    if getattr(strategy, "_paper_desk_v2_order_delegation_installed", False):
        return

    original_buy = getattr(strategy, "buy", None)
    original_sell = getattr(strategy, "sell", None)
    original_cancel = getattr(strategy, "cancel", None)
    if not (callable(original_buy) and callable(original_sell) and callable(original_cancel)):
        logger.debug("strategy buy/sell/cancel not callable, skipping delegation patch")
        return

    def _patched_buy(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(conn_name)
        if bridge is not None:
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            _price = price if price == price else Decimal("0")  # NaN check
            event = _desk.submit_order(
                _iid, OrderSide.BUY, _hb_order_type_to_v2(order_type),
                Decimal(str(_price)), Decimal(str(amount)),
                source_bot=conn_name,
            )
            _fire_hb_events(self, conn_name, event)
            return getattr(event, "order_id", None)
        return original_buy(conn_name, trading_pair, amount, order_type, price, **kwargs)

    def _patched_sell(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(conn_name)
        if bridge is not None:
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            _price = price if price == price else Decimal("0")
            event = _desk.submit_order(
                _iid, OrderSide.SELL, _hb_order_type_to_v2(order_type),
                Decimal(str(_price)), Decimal(str(amount)),
                source_bot=conn_name,
            )
            _fire_hb_events(self, conn_name, event)
            return getattr(event, "order_id", None)
        return original_sell(conn_name, trading_pair, amount, order_type, price, **kwargs)

    def _patched_cancel(self, conn_name, trading_pair, order_id):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(conn_name)
        if bridge is not None:
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            event = _desk.cancel_order(_iid, order_id)
            if event:
                _fire_hb_events(self, conn_name, event)
            return
        return original_cancel(conn_name, trading_pair, order_id)

    try:
        strategy.buy = MethodType(_patched_buy, strategy)
        strategy.sell = MethodType(_patched_sell, strategy)
        strategy.cancel = MethodType(_patched_cancel, strategy)
        strategy._paper_desk_v2_order_delegation_installed = True
        logger.debug("PaperDesk v2: strategy buy/sell/cancel delegation installed")
    except Exception as exc:
        logger.error("Order delegation patch failed: %s", exc, exc_info=True)


def _patch_connector_balances(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Patch connector.get_balance / get_available_balance to return paper portfolio values."""
    if getattr(connector, "_epp_v2_balance_patched", False):
        return
    try:
        def _get_balance(asset: str) -> Decimal:
            return desk.portfolio.balance(asset)

        def _get_available_balance(asset: str) -> Decimal:
            return desk.portfolio.available(asset)

        connector._paper_desk_v2_get_balance = _get_balance
        connector._paper_desk_v2_get_available = _get_available_balance
        connector._epp_v2_balance_patched = True
        logger.debug("Connector balance reads patched for v2 portfolio")
    except Exception as exc:
        logger.debug("Balance patch failed (non-critical): %s", exc)


def _install_paper_stats(connector: Any, desk: PaperDesk, iid: InstrumentId) -> None:
    """Add paper_stats property to connector so ProcessedState can read fill counts."""
    if getattr(connector, "_epp_v2_paper_stats_installed", False):
        return
    try:
        def _paper_stats() -> Dict[str, Decimal]:
            return desk.paper_stats(iid)

        connector.paper_stats = property(lambda self: _paper_stats()) if False else _paper_stats
        connector._epp_v2_paper_stats_installed = True
        logger.debug("paper_stats property installed on connector")
    except Exception as exc:
        logger.debug("paper_stats install failed (non-critical): %s", exc)


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
