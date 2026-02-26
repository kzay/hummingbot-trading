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
7. EventSubscriber protocol for clean decoupled event routing (Phase 5).

Phase 5 — EventSubscriber architecture:
  The bridge now supports optional EventSubscribers that can receive desk events
  without monkey-patching. This allows testing without HB and cleaner separation
  between the desk domain and the HB framework domain.

  When subscribers are registered, events are dispatched to them BEFORE the
  legacy monkey-patch path, allowing gradual migration.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from types import MethodType, SimpleNamespace
from typing import Any, Dict, List, Optional, Protocol

from controllers.paper_engine_v2.data_feeds import HummingbotDataFeed
from controllers.paper_engine_v2.desk import PaperDesk
from controllers.paper_engine_v2.types import (
    EngineEvent,
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

# ---------------------------------------------------------------------------
# EventSubscriber protocol (Phase 5: clean decoupled event routing)
# ---------------------------------------------------------------------------

class EventSubscriber(Protocol):
    """Adapter-style subscriber that receives desk engine events.

    Implement this protocol to receive events from the bridge without
    relying on HB monkey-patching. Useful for:
    - Testing without HB (inject a TestSubscriber)
    - Custom loggers / analytics subscribers
    - Future non-HB connectors

    The bridge calls on_fill / on_cancel / on_reject for each event.
    Implementations should never raise; errors are caught and logged.
    """

    def on_fill(self, event: OrderFilled, connector_name: str) -> None: ...
    def on_cancel(self, event: OrderCanceled, connector_name: str) -> None: ...
    def on_reject(self, event: OrderRejected, connector_name: str) -> None: ...


# Global subscriber registry — use register_event_subscriber() to add.
_EVENT_SUBSCRIBERS: List[EventSubscriber] = []


def register_event_subscriber(subscriber: EventSubscriber) -> None:
    """Register a subscriber to receive desk events via clean protocol."""
    _EVENT_SUBSCRIBERS.append(subscriber)


def unregister_event_subscriber(subscriber: EventSubscriber) -> None:
    """Remove a previously registered subscriber."""
    try:
        _EVENT_SUBSCRIBERS.remove(subscriber)
    except ValueError:
        pass


def _dispatch_to_subscribers(event: EngineEvent, connector_name: str) -> None:
    """Dispatch a desk event to all registered EventSubscribers."""
    if not _EVENT_SUBSCRIBERS:
        return
    for sub in _EVENT_SUBSCRIBERS:
        try:
            if isinstance(event, OrderFilled):
                sub.on_fill(event, connector_name)
            elif isinstance(event, OrderCanceled):
                sub.on_cancel(event, connector_name)
            elif isinstance(event, OrderRejected):
                sub.on_reject(event, connector_name)
        except Exception as exc:
            logger.warning("EventSubscriber %s error: %s", type(sub).__name__, exc)


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

    def _patched_buy(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None, **kwargs):
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
        return original_buy(conn_name, trading_pair, amount, order_type, price, position_action=position_action, **kwargs)

    def _patched_sell(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None, **kwargs):
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
        return original_sell(conn_name, trading_pair, amount, order_type, price, position_action=position_action, **kwargs)

    def _patched_cancel(self, conn_name, trading_pair, order_id, *args, **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(conn_name)
        if bridge is not None:
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            event = _desk.cancel_order(_iid, order_id)
            if event:
                _fire_hb_events(self, conn_name, event)
            return
        return original_cancel(conn_name, trading_pair, order_id, *args, **kwargs)

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
        # Expose the active desk on the connector so controllers/exporters can
        # read canonical paper accounting (position, avg entry, daily open equity).
        if not hasattr(connector, "_paper_desk_v2"):
            connector._paper_desk_v2 = desk
        if not hasattr(connector, "_paper_desk_v2_instrument_id"):
            connector._paper_desk_v2_instrument_id = iid

        # Keep original methods for safety/fallback.
        if not hasattr(connector, "_epp_v2_orig_get_balance") and hasattr(connector, "get_balance"):
            connector._epp_v2_orig_get_balance = connector.get_balance
        if not hasattr(connector, "_epp_v2_orig_get_available_balance") and hasattr(connector, "get_available_balance"):
            connector._epp_v2_orig_get_available_balance = connector.get_available_balance
        if not hasattr(connector, "_epp_v2_orig_ready") and hasattr(connector, "ready"):
            connector._epp_v2_orig_ready = connector.ready
        if not hasattr(connector, "_epp_v2_orig_get_position") and hasattr(connector, "get_position"):
            connector._epp_v2_orig_get_position = connector.get_position
        if not hasattr(connector, "_epp_v2_orig_account_positions") and hasattr(connector, "account_positions"):
            connector._epp_v2_orig_account_positions = connector.account_positions

        def _paper_balance(asset: str) -> Decimal:
            return desk.portfolio.balance(asset)

        def _paper_available(asset: str) -> Decimal:
            return desk.portfolio.available(asset)

        def _patched_get_balance(self, asset: str) -> Decimal:
            try:
                return _paper_balance(asset)
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_balance", None)
                return orig(asset) if callable(orig) else Decimal("0")

        def _patched_get_available_balance(self, asset: str) -> Decimal:
            try:
                return _paper_available(asset)
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_available_balance", None)
                return orig(asset) if callable(orig) else Decimal("0")

        def _patched_ready(self) -> bool:
            # In paper mode we route orders through PaperDesk, so connector readiness
            # shouldn't block startup checks / ops guard.
            return True

        def _paper_position_obj():
            pos = desk.portfolio.get_position(iid)
            # Hummingbot connectors typically return a position-like object with `amount`.
            return SimpleNamespace(
                trading_pair=iid.trading_pair,
                amount=pos.quantity,
                entry_price=pos.avg_entry_price,
            )

        def _patched_get_position(self, trading_pair: Optional[str] = None, *args, **kwargs):
            try:
                if trading_pair and str(trading_pair) != str(iid.trading_pair):
                    orig = getattr(self, "_epp_v2_orig_get_position", None)
                    return orig(trading_pair, *args, **kwargs) if callable(orig) else None
                return _paper_position_obj()
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_position", None)
                return orig(trading_pair, *args, **kwargs) if callable(orig) else None

        def _patched_account_positions(self, *args, **kwargs):
            try:
                # Some connectors expose account_positions as a dict-like structure.
                return {iid.trading_pair: {"amount": desk.portfolio.get_position(iid).quantity}}
            except Exception:
                orig = getattr(self, "_epp_v2_orig_account_positions", None)
                return orig(*args, **kwargs) if callable(orig) else {}

        # Monkeypatch connector methods so the rest of the codebase (runtime adapter,
        # minute logger, reconciliation services) sees PaperDesk equity/position.
        if hasattr(connector, "get_balance"):
            connector.get_balance = MethodType(_patched_get_balance, connector)
        if hasattr(connector, "get_available_balance"):
            connector.get_available_balance = MethodType(_patched_get_available_balance, connector)
        if hasattr(connector, "ready"):
            connector.ready = MethodType(_patched_ready, connector)
        if hasattr(connector, "get_position"):
            connector.get_position = MethodType(_patched_get_position, connector)
        if hasattr(connector, "account_positions"):
            connector.account_positions = MethodType(_patched_account_positions, connector)

        connector._paper_desk_v2_get_balance = _paper_balance
        connector._paper_desk_v2_get_available = _paper_available
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

        connector.paper_stats = _paper_stats
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
    """Convert v2 event to HB event and fire on the correct controller.

    The controller's did_fill_order() writes to fills.csv and updates
    minute.csv — this is what Grafana reads. Without this, fills are
    invisible to the dashboard regardless of paper/live mode.

    Phase 5: Dispatches to registered EventSubscribers FIRST (clean path),
    then falls through to the legacy HB monkey-patch path.
    """
    if event is None:
        return

    # Clean subscriber dispatch (non-raising)
    _dispatch_to_subscribers(event, connector_name)

    # Legacy HB monkey-patch path (preserved for full backward compat)
    try:
        if isinstance(event, OrderFilled):
            _fire_fill_event(strategy, connector_name, event)
        elif isinstance(event, OrderCanceled):
            _fire_cancel_event(strategy, connector_name, event)
        elif isinstance(event, OrderRejected):
            _fire_reject_event(strategy, connector_name, event)
    except Exception as exc:
        logger.warning("HB event fire failed: %s", exc, exc_info=True)


def _find_controller_for_connector(strategy: Any, connector_name: str) -> Any:
    """Find the controller that owns this connector_name."""
    controllers = getattr(strategy, "controllers", {})
    for _, ctrl in controllers.items():
        cfg = getattr(ctrl, "config", None)
        if cfg and str(getattr(cfg, "connector_name", "")) == connector_name:
            return ctrl
    return None


def _fire_fill_event(strategy: Any, connector_name: str, fill_event: OrderFilled) -> None:
    """Fire fill event directly to the controller's did_fill_order().

    This is the critical path: controller.did_fill_order() writes to
    fills.csv, updates daily counters, and feeds Grafana.
    """
    try:
        from hummingbot.core.event.events import OrderFilledEvent as HBOrderFilledEvent  # type: ignore
        from hummingbot.core.data_type.common import TradeType  # type: ignore

        # Determine side from the order_id or source_bot
        # The desk stores the side in the PositionChanged event, but OrderFilled
        # doesn't carry it. We look it up from the desk's internal order tracker.
        trade_type = TradeType.BUY  # default
        bridges = getattr(strategy, "_paper_desk_v2_bridges", {})
        bridge = bridges.get(connector_name)
        if bridge:
            _desk: PaperDesk = bridge["desk"]
            for key, engine in _desk._engines.items():
                # get_order_side works even after order is filled and removed
                side_str = engine.get_order_side(fill_event.order_id)
                if side_str:
                    trade_type = TradeType.BUY if side_str == "buy" else TradeType.SELL
                    break

        now = time.time()

        # Build fee object
        try:
            from hummingbot.core.event.events import TradeFee, TokenAmount
            fee = TradeFee(
                percent=Decimal("0"),
                flat_fees=[TokenAmount(fill_event.instrument_id.quote_asset, fill_event.fee)],
            )
        except Exception:
            fee = SimpleNamespace(
                percent=Decimal("0"),
                flat_fees=[],
                fee_amount_in_token=lambda *a, **k: fill_event.fee,
                is_maker=fill_event.is_maker,
            )

        hb_fill = HBOrderFilledEvent(
            timestamp=now,
            order_id=fill_event.order_id,
            trading_pair=fill_event.instrument_id.trading_pair,
            trade_type=trade_type,
            order_type=None,
            price=fill_event.fill_price,
            amount=fill_event.fill_quantity,
            trade_fee=fee,
        )

        # Fire to the controller directly (writes fills.csv, updates counters)
        controller = _find_controller_for_connector(strategy, connector_name)
        if controller and hasattr(controller, "did_fill_order"):
            try:
                controller.did_fill_order(hb_fill)
            except Exception as exc:
                logger.warning("Controller did_fill_order failed: %s", exc, exc_info=True)

        # Publish fill to hb.bot_telemetry.v1 via Redis so the event_store
        # service ingests paper fills the same way it ingests live fills.
        # Falls back to direct JSONL write when Redis is unavailable.
        #
        # NOTE: We use `redis` directly here rather than importing from
        # services.* because `controllers/types.py` shadows stdlib `types`,
        # which breaks any services import chain that passes through enum/json.
        try:
            instance_name = str(getattr(getattr(controller, "config", None), "instance_name", "") or "")
            controller_id = str(getattr(controller, "id", "") or getattr(controller, "controller_id", "") or "")
            is_maker_val = bool(getattr(fill_event, "is_maker", False))
            side_str = "buy" if trade_type == TradeType.BUY else "sell"

            from datetime import datetime, timezone as _tz
            from pathlib import Path
            import json as _json
            import os as _os
            import uuid as _uuid_mod

            _redis_published = False
            try:
                import redis as _redis_lib  # available in hummingbot conda env (redis 7.1.0)
                _redis_host = _os.environ.get("REDIS_HOST", "")
                if _redis_host:
                    _r = _redis_lib.Redis(
                        host=_redis_host,
                        port=int(_os.environ.get("REDIS_PORT", "6379")),
                        db=int(_os.environ.get("REDIS_DB", "0")),
                        password=_os.environ.get("REDIS_PASSWORD") or None,
                        decode_responses=True,
                        socket_connect_timeout=1,
                    )
                    _payload = {
                        "event_id": str(_uuid_mod.uuid4()),
                        "event_type": "bot_fill",
                        "event_version": "v1",
                        "schema_version": "1.0",
                        "ts_utc": datetime.now(_tz.utc).isoformat(),
                        "producer": "hb.paper_engine_v2",
                        "instance_name": instance_name,
                        "controller_id": controller_id,
                        "connector_name": str(connector_name),
                        "trading_pair": str(fill_event.instrument_id.trading_pair),
                        "side": side_str,
                        "price": float(fill_event.fill_price),
                        "amount_base": float(fill_event.fill_quantity),
                        "notional_quote": float(fill_event.fill_price * fill_event.fill_quantity),
                        "fee_quote": float(fill_event.fee),
                        "order_id": str(fill_event.order_id),
                        "accounting_source": "paper_desk_v2",
                        "is_maker": is_maker_val,
                        "realized_pnl_quote": 0.0,
                        "bot_state": "",
                        "correlation_id": str(getattr(fill_event, "event_id", "") or ""),
                    }
                    _r.xadd(
                        "hb.bot_telemetry.v1",
                        {"payload": _json.dumps(_payload)},
                        maxlen=100_000,
                        approximate=True,
                    )
                    _redis_published = True
            except Exception:
                pass  # Redis not available or down — fall through to JSONL

            if not _redis_published:
                # Fallback: direct JSONL write (offline / Redis-off environments)
                root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
                out_dir = root / "reports" / "event_store"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"events_{datetime.now(_tz.utc).strftime('%Y%m%d')}.jsonl"
                envelope = {
                    "event_id": str(_uuid_mod.uuid4()),
                    "event_type": "bot_fill",
                    "event_version": "v1",
                    "ts_utc": datetime.now(_tz.utc).isoformat(),
                    "producer": "hb.paper_engine_v2",
                    "instance_name": instance_name,
                    "controller_id": controller_id,
                    "connector_name": str(connector_name),
                    "trading_pair": str(fill_event.instrument_id.trading_pair),
                    "correlation_id": str(getattr(fill_event, "event_id", "") or ""),
                    "stream": "local.paper_engine_v2.fallback",
                    "stream_entry_id": "",
                    "accounting_source": "paper_desk_v2",
                    "payload": {
                        "order_id": str(fill_event.order_id),
                        "side": side_str,
                        "price": float(fill_event.fill_price),
                        "amount_base": float(fill_event.fill_quantity),
                        "fee_quote": float(fill_event.fee),
                        "is_maker": is_maker_val,
                    },
                    "ingest_ts_utc": datetime.now(_tz.utc).isoformat(),
                    "schema_validation_status": "ok",
                }
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(_json.dumps(envelope, ensure_ascii=True) + "\n")
        except Exception:
            # Never let telemetry break trading.
            pass

        # Also fire to the strategy (for V2 base class accounting)
        if hasattr(strategy, "did_fill_order"):
            try:
                strategy.did_fill_order(hb_fill)
            except Exception:
                pass

    except Exception as exc:
        logger.warning("Fill event fire failed: %s", exc, exc_info=True)


def _fire_cancel_event(strategy: Any, connector_name: str, cancel_event: OrderCanceled) -> None:
    """Fire cancel event to controller."""
    try:
        from hummingbot.core.event.events import OrderCancelledEvent as HBCancelEvent
        hb_cancel = HBCancelEvent(
            timestamp=time.time(),
            order_id=cancel_event.order_id,
        )
        controller = _find_controller_for_connector(strategy, connector_name)
        if controller and hasattr(controller, "did_cancel_order"):
            controller.did_cancel_order(hb_cancel)
    except Exception as exc:
        logger.debug("Cancel event fire failed: %s", exc)


def _fire_reject_event(strategy: Any, connector_name: str, reject_event: OrderRejected) -> None:
    """Fire reject event to controller."""
    try:
        from hummingbot.core.event.events import MarketOrderFailureEvent as HBFailEvent
        hb_fail = HBFailEvent(
            timestamp=time.time(),
            order_id=reject_event.order_id,
            order_type=None,
            error_message=reject_event.reason,
        )
        controller = _find_controller_for_connector(strategy, connector_name)
        if controller and hasattr(controller, "did_fail_order"):
            controller.did_fail_order(hb_fail)
    except Exception as exc:
        logger.debug("Reject event fire failed: %s", exc)


def drive_desk_tick(
    strategy: Any,
    desk: PaperDesk,
    now_ns: Optional[int] = None,
) -> None:
    """Call from strategy on_tick() to drive the desk.

    Drives all engines, then converts fill/cancel/reject events into
    HB events and fires them on the correct controller. This is what
    makes fills appear in fills.csv and Grafana.
    """
    try:
        all_events = desk.tick(now_ns)
        if not all_events:
            return
        bridges: Dict = getattr(strategy, "_paper_desk_v2_bridges", {})
        for event in all_events:
            # Route event to the correct connector bridge
            event_iid = getattr(event, "instrument_id", None)
            if event_iid is None:
                continue
            for conn_name, bridge in bridges.items():
                bridge_iid = bridge.get("instrument_id")
                if bridge_iid and bridge_iid == event_iid:
                    _fire_hb_events(strategy, conn_name, event)
                    break
    except Exception as exc:
        logger.error("drive_desk_tick failed: %s", exc, exc_info=True)
