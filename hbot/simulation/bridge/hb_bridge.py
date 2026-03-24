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

DEBT-3: Signal consumption, adverse inference, and HB event firing have been
extracted into focused modules under paper_engine_v2/. This file imports and
delegates to them while preserving the original public API.
"""
from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from types import MethodType
from typing import Any

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None  # type: ignore[assignment]

from concurrent.futures import ThreadPoolExecutor

from simulation.bridge.signal_consumer import (  # noqa: F401
    _check_hard_stop_transitions,
    _consume_ml_features,
    _consume_signals,
    _find_controller_by_instance,
)

try:
    from simulation.adverse_inference import _run_adverse_inference
except ImportError:
    _run_adverse_inference = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Re-exports from split modules — backward compatibility
# ---------------------------------------------------------------------------

from simulation.bridge.bridge_utils import (  # noqa: F401
    _CANONICAL_CACHE,
    _canonical_name,
    _fmt_contract_decimal,
    _hb_order_type_to_v2,
    _instance_env_suffix,
    _normalize_position_action,
    _normalize_position_action_hint,
    _order_type_text,
    _parse_env_bool,
)
from simulation.bridge.bridge_state import (  # noqa: F401
    BridgeState,
    _LATENCY_TRACKER,
    _bridge_state,
    _get_signal_redis,
)
from simulation.bridge.paper_exchange_protocol import (  # noqa: F401
    _active_cancel_all_command_event_id,
    _active_cancel_all_fingerprint,
    _active_cancel_all_retry_ttl_s,
    _active_cancel_command_event_id,
    _active_cancel_fingerprint,
    _active_cancel_retry_ttl_s,
    _active_command_ttl_ms,
    _active_submit_fingerprint,
    _active_submit_order_id,
    _active_submit_retry_ttl_s,
    _bootstrap_paper_exchange_cursor,
    _cancel_reconciled_ghost_orders,
    _canonical_runtime_order_state,
    _controller_accounting_contract_metadata,
    _controller_tracked_order_ids,
    _ensure_sync_state_command,
    _get_runtime_order_for_executor,
    _hydrate_runtime_orders_from_state_snapshot,
    _paper_exchange_cursor_key,
    _paper_exchange_state_snapshot_path,
    _prune_runtime_orders,
    _publish_paper_exchange_command,
    _runtime_order_state_flags,
    _runtime_order_trade_type,
    _runtime_orders_bucket,
    _runtime_orders_store,
    _sync_fill_to_portfolio,
    _sync_handshake_key,
    _upsert_runtime_order,
)
from simulation.bridge.compat_helpers import (  # noqa: F401
    _active_failure_hard_stop_streak,
    _active_sync_gate,
    _apply_active_failure_policy,
    _apply_controller_resume,
    _apply_controller_soft_pause,
    _bridge_for_exchange_event,
    _force_sync_hard_stop,
    _mark_active_failure_recovered,
    _normalize_paper_exchange_mode,
    _paper_command_constraints_metadata,
    _paper_exchange_auto_mode,
    _paper_exchange_mode_for_instance,
    _paper_exchange_mode_for_route,
    _paper_exchange_service_heartbeat_is_fresh,
    _paper_exchange_service_only_for_instance,
    _patch_executor_base,
    _patch_market_data_provider,
    _resolve_controller_for_command,
    enable_framework_paper_compat_fallbacks,
)
from simulation.bridge.hb_event_fire import (  # noqa: F401
    EventSubscriber,
    _EVENT_SUBSCRIBERS,
    _dispatch_to_subscribers,
    _find_controller_for_connector,
    _fire_hb_events,
    register_event_subscriber,
    unregister_event_subscriber,
)
from simulation.bridge.connector_patches import (  # noqa: F401
    _install_paper_stats,
    _install_portfolio_snapshot,
    _patch_connector_balances,
    _patch_connector_open_orders,
    _patch_connector_trading_rules,
)
from simulation.budget_checker import install_budget_checker as _install_budget_checker  # noqa: F401
from simulation.data_feeds import HummingbotDataFeed
from simulation.desk import PaperDesk
from simulation.types import (
    _ZERO,
    InstrumentId,
    InstrumentSpec,
    OrderRejected,
    OrderSide,
    PaperOrderType,
    PositionAction,
)
from services.execution_gateway.gateway import build_paper_execution_command  # noqa: F401

logger = logging.getLogger(__name__)

# CONCURRENCY: shared thread pool for non-blocking Redis I/O.
# Tasks submitted here must not mutate _bridge_state dicts/sets directly.
_REDIS_IO_POOL: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=int(os.getenv("HB_BRIDGE_REDIS_IO_WORKERS", "3")),
    thread_name_prefix="hb_bridge_redis",
)

import atexit as _atexit


def _bridge_shutdown() -> None:
    """Release bridge resources on process exit."""
    from simulation.bridge.bridge_state import _bridge_state
    _bridge_state._close_redis()
    _REDIS_IO_POOL.shutdown(wait=False)


_atexit.register(_bridge_shutdown)

_PAPER_ORDER_TRACE_ENABLED: bool = os.getenv("HB_PAPER_ORDER_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
_PAPER_ORDER_TRACE_COOLDOWN_S: float = max(0.5, float(os.getenv("HB_PAPER_ORDER_TRACE_COOLDOWN_S", "1.0")))
# CONCURRENCY: read-modify-write from main thread only; races benign (worst case: extra/skipped trace log).
_LAST_PAPER_ORDER_TRACE_TS: float = 0.0


def _trace_paper_order(message: str, *args: Any, force: bool = False) -> None:
    global _LAST_PAPER_ORDER_TRACE_TS
    if not _PAPER_ORDER_TRACE_ENABLED:
        return
    now = time.time()
    if not force and (now - _LAST_PAPER_ORDER_TRACE_TS) < _PAPER_ORDER_TRACE_COOLDOWN_S:
        return
    _LAST_PAPER_ORDER_TRACE_TS = now
    logger.warning("PAPER_ORDER_TRACE " + message, *args)


def _resolve_shadow_submit_price(
    strategy: Any,
    desk: PaperDesk,
    instrument_id: InstrumentId,
    connector_name: str,
    trading_pair: str,
    side: OrderSide,
) -> Decimal:
    """Best-effort non-zero price for market orders in shadow mode.

    Paper engine validation enforces min-notional checks. Passing NaN->0 for market
    orders causes deterministic rejections. Use top-of-book (or mid) as a surrogate.
    """
    try:
        engine = getattr(desk, "_engines", {}).get(instrument_id.key)
        book = getattr(engine, "_book", None) if engine is not None else None
        if book is not None:
            top = book.best_ask if side == OrderSide.BUY else book.best_bid
            top_price = getattr(top, "price", None)
            if top_price is not None:
                px = Decimal(str(top_price))
                if px > _ZERO:
                    return px
            mid_price = getattr(book, "mid_price", None)
            if mid_price is not None:
                px = Decimal(str(mid_price))
                if px > _ZERO:
                    return px
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        pass

    try:
        connector = getattr(strategy, "connectors", {}).get(connector_name)
        if connector is not None and hasattr(connector, "get_price_by_type"):
            from hummingbot.core.data_type.common import PriceType as _HBPriceType
            px_any = connector.get_price_by_type(trading_pair, _HBPriceType.MidPrice)
            px = Decimal(str(px_any))
            if px > _ZERO:
                return px
    except Exception:  # connector API: broad catch justified
        pass

    return Decimal("0")


# ---------------------------------------------------------------------------
# Paper Exchange event consumption (core event loop)
# ---------------------------------------------------------------------------

def _consume_paper_exchange_events(strategy: Any) -> None:
    """Consume paper_exchange_event stream and map outcomes to HB callbacks.

    Only `PAPER_EXCHANGE_MODE=active` instances are mapped back into HB events.
    Shadow mode still uses in-process desk callbacks as source of truth.
    """
    r = _get_signal_redis()
    if r is None:
        return
    try:
        import json as _json

        from simulation.types import OrderCanceled as _OrderCanceled
        from simulation.types import OrderFilled as _OrderFilled
        from simulation.types import OrderRejected as _OrderRejected
        from platform_lib.contracts.event_schemas import PaperExchangeEvent
        from platform_lib.contracts.stream_names import PAPER_EXCHANGE_EVENT_STREAM

        _bootstrap_paper_exchange_cursor(strategy, r, PAPER_EXCHANGE_EVENT_STREAM)
        cursor_key = _paper_exchange_cursor_key(strategy)
        result = r.xread(
            {PAPER_EXCHANGE_EVENT_STREAM: _bridge_state.last_paper_exchange_event_id},
            count=200,
            block=1,
        )
        if not result:
            return

        latest_seen_entry_id: str | None = None
        for _stream_name, entries in result:
            for entry_id, data in entries:
                _bridge_state.last_paper_exchange_event_id = str(entry_id)
                latest_seen_entry_id = _bridge_state.last_paper_exchange_event_id
                raw = data.get("payload")
                if not isinstance(raw, str):
                    continue
                try:
                    payload = _orjson.loads(raw) if _orjson else _json.loads(raw)
                    event = PaperExchangeEvent(**payload)
                except (ValueError, TypeError, KeyError):
                    continue

                if event.event_id in _bridge_state.paper_exchange_seen_event_ids:
                    continue
                _bridge_state.paper_exchange_seen_event_ids.add(event.event_id)
                if len(_bridge_state.paper_exchange_seen_event_ids) > 20_000:
                    _bridge_state.paper_exchange_seen_event_ids.clear()

                _ctrl_local, _controller_id_local, local_instance_name = _resolve_controller_for_command(
                    strategy,
                    str(event.connector_name),
                    str(event.trading_pair),
                )
                if _ctrl_local is None:
                    continue

                event_instance_name = str(getattr(event, "instance_name", "") or "").strip()
                resolved_instance_name = str(local_instance_name or event_instance_name).strip()
                if local_instance_name:
                    if not event_instance_name:
                        continue
                    if event_instance_name.lower() != str(local_instance_name).strip().lower():
                        continue

                mode = _paper_exchange_mode_for_instance(resolved_instance_name)
                command = str(event.command or "").strip().lower()
                status = str(event.status).strip().lower()
                reason = str(event.reason or "")
                sync_key = _sync_handshake_key(
                    resolved_instance_name,
                    str(event.connector_name),
                    str(event.trading_pair),
                )
                if command == "sync_state":
                    if status == "processed":
                        _bridge_state.sync_confirmed_keys.add(sync_key)
                        _bridge_state.sync_state_published_keys.discard(sync_key)
                        _bridge_state.sync_timeout_hard_stop_keys.discard(sync_key)
                        _mark_active_failure_recovered(
                            strategy,
                            connector_name=str(event.connector_name),
                            trading_pair=str(event.trading_pair),
                        )
                        resolved_connector_name, _ = _bridge_for_exchange_event(
                            strategy,
                            str(event.connector_name),
                            str(event.trading_pair),
                        )
                        route_connector_name = str(resolved_connector_name or event.connector_name)
                        hydrated_order_ids = _hydrate_runtime_orders_from_state_snapshot(
                            strategy,
                            instance_name=resolved_instance_name,
                            connector_name=route_connector_name,
                            trading_pair=str(event.trading_pair),
                        )
                        canceled_ghosts = _cancel_reconciled_ghost_orders(
                            strategy,
                            controller=_ctrl_local,
                            instance_name=resolved_instance_name,
                            connector_name=route_connector_name,
                            trading_pair=str(event.trading_pair),
                            order_ids=hydrated_order_ids,
                        )
                        if hydrated_order_ids or canceled_ghosts:
                            logger.info(
                                "paper_exchange startup reconcile | instance=%s connector=%s pair=%s hydrated=%d canceled_ghosts=%d",
                                resolved_instance_name,
                                route_connector_name,
                                str(event.trading_pair),
                                len(hydrated_order_ids),
                                canceled_ghosts,
                            )
                        continue
                    if status == "rejected" and mode == "active":
                        if reason.strip().lower() == "expired_command":
                            _bridge_state.sync_state_published_keys.discard(sync_key)
                            _bridge_state.sync_requested_at_ms_by_key.pop(sync_key, None)
                            logger.warning(
                                "paper_exchange sync expired in queue; allowing republish | instance=%s connector=%s pair=%s",
                                resolved_instance_name,
                                str(event.connector_name),
                                str(event.trading_pair),
                            )
                            continue
                        _force_sync_hard_stop(
                            strategy,
                            controller=_ctrl_local,
                            controller_id=_controller_id_local,
                            instance_name=resolved_instance_name,
                            connector_name=str(event.connector_name),
                            trading_pair=str(event.trading_pair),
                            sync_key=sync_key,
                            reason=f"paper_exchange_sync_failed:{reason or 'rejected'}",
                        )
                    continue

                if mode != "active":
                    continue

                resolved_connector_name, bridge = _bridge_for_exchange_event(
                    strategy, str(event.connector_name), str(event.trading_pair)
                )
                if bridge is None or not resolved_connector_name:
                    continue
                instrument_id = bridge.get("instrument_id")
                if instrument_id is None:
                    continue

                timestamp_ns = int(time.time() * 1e9)

                if status == "rejected":
                    reason_norm = reason.strip().lower()
                    if reason_norm in {"stale_market_snapshot", "no_market_snapshot"}:
                        _apply_active_failure_policy(
                            strategy,
                            connector_name=str(event.connector_name),
                            trading_pair=str(event.trading_pair),
                            failure_class="stale_feed",
                            reason=reason_norm,
                        )
                    elif reason_norm in {"expired_command"}:
                        _apply_active_failure_policy(
                            strategy,
                            connector_name=str(event.connector_name),
                            trading_pair=str(event.trading_pair),
                            failure_class="command_backlog",
                            reason=reason_norm,
                        )
                    if not event.order_id:
                        continue
                    _upsert_runtime_order(
                        strategy,
                        connector_name=resolved_connector_name,
                        order_id=str(event.order_id),
                        trading_pair=str(event.trading_pair),
                        state="failed",
                        failure_reason=f"paper_exchange:{reason or 'rejected'}",
                    )
                    reject_event = _OrderRejected(
                        event_id=f"pe-reject-{event.event_id}",
                        timestamp_ns=timestamp_ns,
                        instrument_id=instrument_id,
                        order_id=str(event.order_id),
                        reason=f"paper_exchange:{reason or 'rejected'}",
                        source_bot=resolved_connector_name,
                        instance_name=resolved_instance_name,
                    )
                    _fire_hb_events(strategy, resolved_connector_name, reject_event, _bridge_state)
                    continue

                if status != "processed":
                    continue

                _mark_active_failure_recovered(
                    strategy,
                    connector_name=str(event.connector_name),
                    trading_pair=str(event.trading_pair),
                )

                if command == "cancel_order" and event.order_id:
                    _upsert_runtime_order(
                        strategy,
                        connector_name=resolved_connector_name,
                        order_id=str(event.order_id),
                        trading_pair=str(event.trading_pair),
                        state="canceled",
                    )
                    cancel_event = _OrderCanceled(
                        event_id=f"pe-cancel-{event.event_id}",
                        timestamp_ns=timestamp_ns,
                        instrument_id=instrument_id,
                        order_id=str(event.order_id),
                        source_bot=resolved_connector_name,
                        instance_name=resolved_instance_name,
                    )
                    _fire_hb_events(strategy, resolved_connector_name, cancel_event, _bridge_state)
                    continue

                if command == "submit_order" and event.order_id:
                    metadata = event.metadata if isinstance(event.metadata, dict) else {}
                    order_state = str(metadata.get("order_state", "working")).strip().lower()
                    runtime_state = "working"
                    if order_state in {"filled", "expired", "rejected", "cancelled", "canceled"}:
                        runtime_state = "filled" if order_state == "filled" else order_state
                    elif order_state in {"partially_filled", "partial"}:
                        runtime_state = "partially_filled"
                    _upsert_runtime_order(
                        strategy,
                        connector_name=resolved_connector_name,
                        order_id=str(event.order_id),
                        trading_pair=str(event.trading_pair),
                        side=str(metadata.get("side", "")).lower() if metadata else None,
                        order_type=str(metadata.get("order_type", "")).lower() if metadata else None,
                        amount=metadata.get("amount_base"),
                        price=metadata.get("price"),
                        state=runtime_state,
                    )
                    if order_state == "expired":
                        reject_event = _OrderRejected(
                            event_id=f"pe-expired-{event.event_id}",
                            timestamp_ns=timestamp_ns,
                            instrument_id=instrument_id,
                            order_id=str(event.order_id),
                            reason=f"paper_exchange:{reason or 'expired'}",
                            source_bot=resolved_connector_name,
                            instance_name=resolved_instance_name,
                        )
                        _fire_hb_events(strategy, resolved_connector_name, reject_event, _bridge_state)
                        continue
                    if order_state in {"partially_filled", "filled"}:
                        try:
                            fill_price = Decimal(str(metadata.get("fill_price", metadata.get("price", "0"))))
                            fill_qty = Decimal(str(metadata.get("fill_amount_base", metadata.get("amount_base", "0"))))
                            fill_fee = Decimal(str(metadata.get("fill_fee_quote", "0")))
                            total_qty = Decimal(str(metadata.get("amount_base", "0")))
                        except Exception:
                            fill_price = Decimal("0")
                            fill_qty = Decimal("0")
                            fill_fee = Decimal("0")
                            total_qty = Decimal("0")
                        if fill_price > _ZERO and fill_qty > _ZERO:
                            remaining = Decimal("0")
                            if order_state == "partially_filled" and total_qty > _ZERO:
                                remaining = max(_ZERO, total_qty - fill_qty)
                            is_maker_text = str(metadata.get("is_maker", "0")).strip().lower()
                            is_maker = is_maker_text in {"1", "true", "yes", "y", "on"}
                            from simulation.types import OrderFilled as _OrderFilled
                            fill_event = _OrderFilled(
                                event_id=f"pe-fill-{event.event_id}",
                                timestamp_ns=timestamp_ns,
                                instrument_id=instrument_id,
                                order_id=str(event.order_id),
                                fill_price=fill_price,
                                fill_quantity=fill_qty,
                                fee=fill_fee,
                                is_maker=is_maker,
                                remaining_quantity=remaining,
                                source_bot=resolved_connector_name,
                                instance_name=resolved_instance_name,
                            )
                            _sync_fill_to_portfolio(
                                strategy, instrument_id,
                                side_str=str(metadata.get("side", "buy")).lower(),
                                fill_price=fill_price, fill_qty=fill_qty, fill_fee=fill_fee,
                                position_action_str=str(metadata.get("position_action", "")),
                                position_mode_str=str(metadata.get("position_mode", "ONEWAY")),
                                now_ns=timestamp_ns,
                            )
                            _fire_hb_events(strategy, resolved_connector_name, fill_event, _bridge_state)
                    continue

                if command in {"order_fill", "fill", "fill_order", "market_fill"} and event.order_id:
                    metadata = event.metadata if isinstance(event.metadata, dict) else {}
                    order_state = str(metadata.get("order_state", "partially_filled")).strip().lower()
                    runtime_state = "partially_filled" if order_state in {"partial", "partially_filled"} else "filled"
                    _upsert_runtime_order(
                        strategy,
                        connector_name=resolved_connector_name,
                        order_id=str(event.order_id),
                        trading_pair=str(event.trading_pair),
                        side=str(metadata.get("side", "")).lower() if metadata else None,
                        order_type=str(metadata.get("order_type", "")).lower() if metadata else None,
                        amount=metadata.get("amount_base"),
                        price=metadata.get("price"),
                        state=runtime_state,
                    )
                    try:
                        fill_price = Decimal(str(metadata.get("fill_price", metadata.get("price", "0"))))
                        fill_qty = Decimal(str(metadata.get("fill_amount_base", metadata.get("fill_quantity", "0"))))
                        fill_fee = Decimal(str(metadata.get("fill_fee_quote", metadata.get("fee", "0"))))
                        remaining = Decimal(str(metadata.get("remaining_amount_base", metadata.get("remaining_quantity", "0"))))
                    except Exception:
                        fill_price = Decimal("0")
                        fill_qty = Decimal("0")
                        fill_fee = Decimal("0")
                        remaining = Decimal("0")
                    if fill_price <= _ZERO or fill_qty <= _ZERO:
                        continue
                    is_maker_text = str(metadata.get("is_maker", "0")).strip().lower()
                    is_maker = is_maker_text in {"1", "true", "yes", "y", "on"}
                    from simulation.types import OrderFilled as _OrderFilled
                    fill_event = _OrderFilled(
                        event_id=f"pe-fill-lifecycle-{event.event_id}",
                        timestamp_ns=timestamp_ns,
                        instrument_id=instrument_id,
                        order_id=str(event.order_id),
                        fill_price=fill_price,
                        fill_quantity=fill_qty,
                        fee=fill_fee,
                        is_maker=is_maker,
                        remaining_quantity=max(_ZERO, remaining),
                        source_bot=resolved_connector_name,
                        instance_name=resolved_instance_name,
                    )
                    pa_str = str(metadata.get("position_action", "") or event.position_action or "")
                    pm_str = str(metadata.get("position_mode", "") or event.position_mode or "ONEWAY")
                    _sync_fill_to_portfolio(
                        strategy, instrument_id,
                        side_str=str(metadata.get("side", "buy")).lower(),
                        fill_price=fill_price, fill_qty=fill_qty, fill_fee=fill_fee,
                        position_action_str=pa_str,
                        position_mode_str=pm_str,
                        now_ns=timestamp_ns,
                    )
                    _fire_hb_events(strategy, resolved_connector_name, fill_event, _bridge_state)
        if latest_seen_entry_id is not None:
            try:
                r.set(cursor_key, latest_seen_entry_id)
            except Exception:
                logger.debug("paper_exchange cursor persist failed", exc_info=True)
    except Exception as exc:
        logger.warning("paper_exchange event consume failed (non-critical): %s", exc)


# ---------------------------------------------------------------------------
# Bridge installation
# ---------------------------------------------------------------------------

def install_paper_desk_bridge(
    strategy: Any,
    desk: PaperDesk,
    connector_name: str,
    instrument_id: InstrumentId,
    trading_pair: str,
    instrument_spec: InstrumentSpec | None = None,
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
            except (AttributeError, TypeError, KeyError):
                pass

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
                from simulation.data_feeds import NullDataFeed
                feed = NullDataFeed()
            desk.register_instrument(spec, feed)

        equity = desk.portfolio.balance(instrument_id.quote_asset)
        if equity <= _ZERO:
            equity = Decimal("500")

        if connector is not None:
            _install_budget_checker(connector, equity)

        _install_order_delegation(strategy, desk, connector_name, instrument_id)

        if connector is not None:
            _patch_connector_balances(connector, desk, instrument_id)

        if connector is not None:
            _install_paper_stats(connector, desk, instrument_id)

        if connector is not None:
            _patch_connector_open_orders(connector, desk, instrument_id)

        if connector is not None:
            _patch_connector_trading_rules(connector, desk, instrument_id)

        if connector is not None:
            _install_portfolio_snapshot(connector, desk, instrument_id)

        logger.info(
            "PaperDesk v2 bridge fully installed: %s/%s engine_registered=%s",
            connector_name,
            trading_pair,
            str(instrument_id.key in getattr(desk, "_engines", {})),
        )
        return True

    except Exception as exc:
        logger.error("PaperDesk bridge install failed: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Order delegation
# ---------------------------------------------------------------------------

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

    def _patched_order(
        self,
        order_side: OrderSide,
        side_str: str,
        close_position_action: PositionAction,
        original_fn,
        conn_name,
        trading_pair,
        amount,
        order_type,
        price=Decimal("NaN"),
        position_action=None,
        **kwargs,
    ):
        resolved_conn_name, bridge = _bridge_for_exchange_event(self, conn_name, trading_pair)
        if bridge is not None:
            route_connector_name = str(resolved_conn_name or conn_name)
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            mode = _paper_exchange_mode_for_route(self, route_connector_name, trading_pair)
            order_type_text = _order_type_text(order_type)
            force_trace = "MARKET" in order_type_text or str(position_action or "").strip() != ""
            _trace_paper_order(
                "stage=bridge_%s_enter connector=%%s pair=%%s mode=%%s amount=%%s price=%%s order_type=%%s position_action=%%s" % side_str,
                route_connector_name, trading_pair, mode,
                str(amount), str(price), order_type_text, str(position_action or ""),
                force=force_trace,
            )
            if force_trace:
                logger.warning(
                    "PAPER_ROUTE_PROBE stage=bridge_%s_enter connector=%s pair=%s mode=%s amount=%s order_type=%s",
                    side_str, route_connector_name, trading_pair, mode, str(amount), order_type_text,
                )
            if mode == "active":
                normalized_position_action = _normalize_position_action(position_action, order_side)
                position_mode = str(
                    getattr(
                        getattr(
                            _find_controller_for_connector(self, route_connector_name, trading_pair=str(trading_pair or "")),
                            "config", None,
                        ),
                        "position_mode", "ONEWAY",
                    ) or "ONEWAY"
                ).upper()
                sync_ready, sync_reason = _active_sync_gate(self, route_connector_name, trading_pair)
                generated_order_id = _active_submit_order_id(
                    self, connector_name=route_connector_name, trading_pair=trading_pair,
                    side=side_str, order_type=order_type, amount=amount, price=price,
                )
                _upsert_runtime_order(
                    self, connector_name=route_connector_name, order_id=generated_order_id,
                    trading_pair=trading_pair, side=side_str, order_type=order_type,
                    amount=amount, price=price, state="pending_create",
                )
                if not sync_ready:
                    _upsert_runtime_order(self, connector_name=route_connector_name,
                                          order_id=generated_order_id, state="failed", failure_reason=sync_reason)
                    reject_event = OrderRejected(
                        event_id=f"pe-sync-reject-{generated_order_id}",
                        timestamp_ns=int(time.time() * 1e9), instrument_id=_iid,
                        order_id=generated_order_id, reason=sync_reason, source_bot=route_connector_name,
                    )
                    _fire_hb_events(self, route_connector_name, reject_event, _bridge_state)
                    _trace_paper_order(
                        "stage=bridge_%s_sync_reject connector=%%s pair=%%s order_id=%%s reason=%%s" % side_str,
                        route_connector_name, trading_pair, generated_order_id, sync_reason, force=True,
                    )
                    return generated_order_id

                publish_entry_id = _publish_paper_exchange_command(
                    self, connector_name=route_connector_name, trading_pair=trading_pair,
                    command="submit_order", order_id=generated_order_id, side=side_str,
                    order_type=order_type, amount_base=amount, price=price,
                    metadata={
                        "bridge_method": side_str, "compat_adapter": "active",
                        "position_action": normalized_position_action.value,
                        "position_mode": position_mode,
                        "reduce_only": "1" if normalized_position_action == close_position_action else "0",
                        **_paper_command_constraints_metadata(self, route_connector_name, trading_pair),
                    },
                )
                if publish_entry_id is None:
                    _upsert_runtime_order(self, connector_name=route_connector_name,
                                          order_id=generated_order_id, state="failed",
                                          failure_reason="paper_exchange_command_publish_failed")
                    reject_event = OrderRejected(
                        event_id=f"pe-local-reject-{generated_order_id}",
                        timestamp_ns=int(time.time() * 1e9), instrument_id=_iid,
                        order_id=generated_order_id, reason="paper_exchange_command_publish_failed",
                        source_bot=route_connector_name,
                    )
                    _fire_hb_events(self, route_connector_name, reject_event, _bridge_state)
                    _trace_paper_order(
                        "stage=bridge_%s_publish_failed connector=%%s pair=%%s order_id=%%s" % side_str,
                        route_connector_name, trading_pair, generated_order_id, force=True,
                    )
                else:
                    _trace_paper_order(
                        "stage=bridge_%s_published connector=%%s pair=%%s order_id=%%s stream_entry_id=%%s" % side_str,
                        route_connector_name, trading_pair, generated_order_id, str(publish_entry_id),
                        force=force_trace,
                    )
                return generated_order_id

            _price = price if price == price else _resolve_shadow_submit_price(
                self, _desk, _iid, route_connector_name, trading_pair, order_side,
            )
            normalized_position_action = _normalize_position_action(position_action, order_side)
            position_mode = str(
                getattr(
                    getattr(
                        _find_controller_for_connector(self, route_connector_name, trading_pair=str(trading_pair or "")),
                        "config", None,
                    ),
                    "position_mode", "ONEWAY",
                ) or "ONEWAY"
            ).upper()
            event = _desk.submit_order(
                _iid, order_side, _hb_order_type_to_v2(order_type),
                Decimal(str(_price)), Decimal(str(amount)),
                source_bot=route_connector_name,
                position_action=normalized_position_action,
                position_mode=position_mode,
            )
            if force_trace:
                logger.warning(
                    "PAPER_ROUTE_PROBE stage=bridge_%s_submit connector=%s pair=%s order_id=%s event=%s reason=%s",
                    side_str, route_connector_name, trading_pair,
                    str(getattr(event, "order_id", "") or ""),
                    type(event).__name__, str(getattr(event, "reason", "") or ""),
                )
            _publish_paper_exchange_command(
                self, connector_name=route_connector_name, trading_pair=trading_pair,
                command="submit_order",
                order_id=str(getattr(event, "order_id", "") or "") or None,
                side=side_str, order_type=order_type, amount_base=amount, price=_price,
                metadata={
                    "bridge_method": side_str, "compat_adapter": "shadow",
                    "position_action": normalized_position_action.value,
                    "position_mode": position_mode,
                    "reduce_only": "1" if normalized_position_action == close_position_action else "0",
                    **_paper_command_constraints_metadata(self, route_connector_name, trading_pair),
                },
            )
            _trace_paper_order(
                "stage=bridge_%s_desk_submit connector=%%s pair=%%s order_id=%%s event=%%s reason=%%s" % side_str,
                route_connector_name, trading_pair,
                str(getattr(event, "order_id", "") or ""),
                type(event).__name__, str(getattr(event, "reason", "") or ""),
                force=force_trace or type(event).__name__ != "OrderAccepted",
            )
            _fire_hb_events(self, route_connector_name, event, _bridge_state)
            return getattr(event, "order_id", None)
        return original_fn(conn_name, trading_pair, amount, order_type, price, position_action=position_action, **kwargs)

    def _patched_buy(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None, **kwargs):
        return _patched_order(
            self, OrderSide.BUY, "buy", PositionAction.CLOSE_SHORT, original_buy,
            conn_name, trading_pair, amount, order_type, price, position_action, **kwargs,
        )

    def _patched_sell(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None, **kwargs):
        return _patched_order(
            self, OrderSide.SELL, "sell", PositionAction.CLOSE_LONG, original_sell,
            conn_name, trading_pair, amount, order_type, price, position_action, **kwargs,
        )

    def _patched_cancel(self, conn_name, trading_pair, order_id, *args, **kwargs):
        resolved_conn_name, bridge = _bridge_for_exchange_event(self, conn_name, trading_pair)
        if bridge is not None:
            route_connector_name = str(resolved_conn_name or conn_name)
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            mode = _paper_exchange_mode_for_route(self, route_connector_name, trading_pair)
            if mode == "active":
                sync_ready, sync_reason = _active_sync_gate(self, route_connector_name, trading_pair)
                if not sync_ready:
                    if order_id:
                        _upsert_runtime_order(
                            self,
                            connector_name=route_connector_name,
                            order_id=str(order_id),
                            state="failed",
                            failure_reason=sync_reason,
                        )
                        reject_event = OrderRejected(
                            event_id=f"pe-sync-reject-cancel-{order_id}",
                            timestamp_ns=int(time.time() * 1e9),
                            instrument_id=_iid,
                            order_id=str(order_id),
                            reason=sync_reason,
                            source_bot=route_connector_name,
                        )
                        _fire_hb_events(self, route_connector_name, reject_event, _bridge_state)
                    return

                cancel_command_event_id = _active_cancel_command_event_id(
                    self,
                    connector_name=route_connector_name,
                    trading_pair=trading_pair,
                    order_id=str(order_id or ""),
                )
                publish_entry_id = _publish_paper_exchange_command(
                    self,
                    connector_name=route_connector_name,
                    trading_pair=trading_pair,
                    command="cancel_order",
                    order_id=str(order_id) if order_id else None,
                    metadata={"bridge_method": "cancel", "compat_adapter": "active"},
                    command_event_id=cancel_command_event_id,
                )
                if publish_entry_id is None and order_id:
                    _upsert_runtime_order(
                        self,
                        connector_name=route_connector_name,
                        order_id=str(order_id),
                        state="failed",
                        failure_reason="paper_exchange_command_publish_failed",
                    )
                    reject_event = OrderRejected(
                        event_id=f"pe-local-reject-cancel-{order_id}",
                        timestamp_ns=int(time.time() * 1e9),
                        instrument_id=_iid,
                        order_id=str(order_id),
                        reason="paper_exchange_command_publish_failed",
                        source_bot=route_connector_name,
                    )
                    _fire_hb_events(self, route_connector_name, reject_event, _bridge_state)
                elif order_id:
                    _upsert_runtime_order(
                        self,
                        connector_name=route_connector_name,
                        order_id=str(order_id),
                        state="pending_cancel",
                    )
                return

            event = _desk.cancel_order(_iid, order_id)
            _publish_paper_exchange_command(
                self,
                connector_name=route_connector_name,
                trading_pair=trading_pair,
                command="cancel_order",
                order_id=str(order_id) if order_id else None,
                metadata={"bridge_method": "cancel", "compat_adapter": "shadow"},
            )
            from simulation.types import CancelRejected as _CancelRejected
            if event and not isinstance(event, _CancelRejected):
                _fire_hb_events(self, route_connector_name, event, _bridge_state)
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


# ---------------------------------------------------------------------------
# Tick orchestration
# ---------------------------------------------------------------------------

def drive_desk_tick(
    strategy: Any,
    desk: PaperDesk,
    now_ns: int | None = None,
) -> None:
    """Call from strategy on_tick() to drive the desk.

    Drives all engines, then converts fill/cancel/reject events into
    HB events and fires them on the correct controller. This is what
    makes fills appear in fills.csv and the metrics pipeline.
    """
    started = time.perf_counter()

    _t_io = time.perf_counter()
    _fut_sig = _REDIS_IO_POOL.submit(_consume_signals, strategy, _bridge_state)
    _fut_guard = _REDIS_IO_POOL.submit(_check_hard_stop_transitions, strategy, _bridge_state)
    _fut_pe = _REDIS_IO_POOL.submit(_consume_paper_exchange_events, strategy)
    _fut_ml = _REDIS_IO_POOL.submit(_consume_ml_features, strategy, _bridge_state)
    if _run_adverse_inference is not None:
        _fut_adverse = _REDIS_IO_POOL.submit(_run_adverse_inference, strategy, _bridge_state)
    else:
        _fut_adverse = None

    for label, fut in [
        ("signal_consumption", _fut_sig),
        ("guard_state_check", _fut_guard),
        ("paper_exchange_events", _fut_pe),
        ("ml_features", _fut_ml),
        ("adverse_inference", _fut_adverse),
    ]:
        if fut is None:
            continue
        try:
            fut.result(timeout=0.5)
        except TimeoutError:
            _LATENCY_TRACKER.observe("bridge_io_timeout_count", 1)
            logger.warning("%s timed out after 0.5s", label)
        except Exception as exc:
            logger.warning("%s failed (non-critical): %s", label, exc)
    _LATENCY_TRACKER.observe("bridge_parallel_io_ms", (time.perf_counter() - _t_io) * 1000.0)

    try:
        bridges: dict = getattr(strategy, "_paper_desk_v2_bridges", {})
        _t_sync = time.perf_counter()
        for conn_name, bridge in bridges.items():
            bridge_iid = bridge.get("instrument_id")
            trading_pair = str(getattr(bridge_iid, "trading_pair", "") or "")
            if trading_pair:
                _ensure_sync_state_command(strategy, conn_name, trading_pair)
        _LATENCY_TRACKER.observe("bridge_sync_state_ms", (time.perf_counter() - _t_sync) * 1000.0)

        _t_desk = time.perf_counter()
        all_events = desk.tick(now_ns)
        desk_tick_ms = (time.perf_counter() - _t_desk) * 1000.0
        _LATENCY_TRACKER.observe("bridge_desk_tick_only_ms", desk_tick_ms)
        if all_events and any(type(ev).__name__ == "OrderFilled" for ev in all_events):
            _LATENCY_TRACKER.observe("fill_io_ms", desk_tick_ms)
        _LATENCY_TRACKER.observe("hb_bridge_desk_tick_ms", (time.perf_counter() - started) * 1000.0)
        _LATENCY_TRACKER.flush(
            extra={
                "bridges": len(getattr(strategy, "_paper_desk_v2_bridges", {}) or {}),
                "desk_events": len(all_events or []),
            }
        )
        if not all_events:
            return
        _t_fire = time.perf_counter()
        for event in all_events:
            event_iid = getattr(event, "instrument_id", None)
            if event_iid is None:
                continue
            if hasattr(event, "order_id"):
                _trace_paper_order(
                    "stage=desk_tick_event event=%s order_id=%s source_bot=%s",
                    type(event).__name__,
                    str(getattr(event, "order_id", "") or ""),
                    str(getattr(event, "source_bot", "") or ""),
                    force=type(event).__name__ in {"OrderRejected", "OrderFilled"},
                )
                order_id = str(getattr(event, "order_id", "") or "")
                if order_id.startswith("paper_v2_") and type(event).__name__ in {"OrderAccepted", "OrderRejected", "OrderFilled", "OrderCanceled"}:
                    logger.warning(
                        "PAPER_ROUTE_PROBE stage=desk_tick_event event=%s order_id=%s source_bot=%s reason=%s",
                        type(event).__name__,
                        order_id,
                        str(getattr(event, "source_bot", "") or ""),
                        str(getattr(event, "reason", "") or ""),
                    )
            for conn_name, bridge in bridges.items():
                bridge_iid = bridge.get("instrument_id")
                if bridge_iid and bridge_iid == event_iid:
                    _fire_hb_events(strategy, conn_name, event, _bridge_state)
                    break
        _LATENCY_TRACKER.observe("bridge_fire_hb_events_ms", (time.perf_counter() - _t_fire) * 1000.0)
    except Exception as exc:
        _LATENCY_TRACKER.observe("hb_bridge_desk_tick_ms", (time.perf_counter() - started) * 1000.0)
        _LATENCY_TRACKER.flush(extra={"last_error": type(exc).__name__})
        logger.error("drive_desk_tick failed: %s", exc, exc_info=True)
