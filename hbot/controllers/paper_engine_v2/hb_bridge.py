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
from types import MethodType, SimpleNamespace
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from controllers.paper_engine_v2.data_feeds import HummingbotDataFeed
from controllers.paper_engine_v2.desk import PaperDesk
from controllers.paper_engine_v2.signal_consumer import _find_controller_by_instance
from controllers.paper_engine_v2.types import (
    EngineEvent,
    InstrumentId,
    InstrumentSpec,
    OrderCanceled,
    OrderFilled,
    OrderRejected,
    OrderSide,
    PaperOrderType,
    PositionAction,
    _ZERO,
)

from controllers.paper_engine_v2.hb_event_fire import (
    EventSubscriber,
    _EVENT_SUBSCRIBERS,
    register_event_subscriber,
    unregister_event_subscriber,
    _dispatch_to_subscribers,
    _find_controller_for_connector,
    _fire_hb_events,
    _fire_cancel_event,
    _fire_reject_event,
)
from services.execution_gateway.gateway import build_paper_execution_command

logger = logging.getLogger(__name__)

_PAPER_ORDER_TRACE_ENABLED: bool = os.getenv("HB_PAPER_ORDER_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
_PAPER_ORDER_TRACE_COOLDOWN_S: float = max(0.5, float(os.getenv("HB_PAPER_ORDER_TRACE_COOLDOWN_S", "1.0")))
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


def _order_type_text(order_type: Any) -> str:
    return str(getattr(order_type, "name", order_type) or "").upper()


def _normalize_position_action(position_action: Any, side: OrderSide) -> PositionAction:
    if isinstance(position_action, PositionAction):
        return position_action
    text = str(getattr(position_action, "name", position_action) or "").strip().lower()
    if text in {"open_long", "open"} and side == OrderSide.BUY:
        return PositionAction.OPEN_LONG
    if text in {"close_short", "close"} and side == OrderSide.BUY:
        return PositionAction.CLOSE_SHORT
    if text in {"open_short", "open"} and side == OrderSide.SELL:
        return PositionAction.OPEN_SHORT
    if text in {"close_long", "close"} and side == OrderSide.SELL:
        return PositionAction.CLOSE_LONG
    return PositionAction.AUTO


def _normalize_position_action_hint(position_action: Any) -> Optional[PositionAction]:
    if position_action is None:
        return None
    if isinstance(position_action, PositionAction):
        return position_action
    text = str(getattr(position_action, "name", position_action) or "").strip().lower()
    mapping = {
        "open_long": PositionAction.OPEN_LONG,
        "close_long": PositionAction.CLOSE_LONG,
        "open_short": PositionAction.OPEN_SHORT,
        "close_short": PositionAction.CLOSE_SHORT,
        "auto": PositionAction.AUTO,
    }
    return mapping.get(text)


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
    except Exception:
        pass

    try:
        connector = getattr(strategy, "connectors", {}).get(connector_name)
        if connector is not None and hasattr(connector, "get_price_by_type"):
            from hummingbot.core.data_type.common import PriceType as _HBPriceType
            px_any = connector.get_price_by_type(trading_pair, _HBPriceType.MidPrice)
            px = Decimal(str(px_any))
            if px > _ZERO:
                return px
    except Exception:
        pass

    return Decimal("0")


_CANONICAL_CACHE: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# BridgeState — holds all mutable state that was previously module-level.
# Testable, resettable, multi-bot safe.
# ---------------------------------------------------------------------------

class BridgeState:
    """Encapsulates all mutable bridge state (Redis, signal cursor, guard state, ML model).

    A single process-wide instance ``_bridge_state`` replaces the former
    module-level globals. Tests can call ``reset()`` instead of reaching into
    six separate module attributes.
    """

    __slots__ = (
        "redis_client", "redis_init_done", "last_signal_id",
        "prev_guard_states", "adverse_model", "adverse_model_path",
        "adverse_model_loaded", "sync_state_published_keys",
        "paper_exchange_mode_warned_instances",
        "paper_exchange_auto_mode_by_instance",
        "paper_exchange_auto_mode_updated_ms_by_instance",
        "last_paper_exchange_event_id", "paper_exchange_seen_event_ids",
        "paper_exchange_cursor_initialized",
        "sync_requested_at_ms_by_key", "sync_confirmed_keys",
        "sync_timeout_hard_stop_keys",
        "active_failure_streak_by_key",
        "active_submit_order_cache",
        "active_cancel_command_cache",
        "active_cancel_all_command_cache",
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.redis_client: Optional[Any] = None
        self.redis_init_done: bool = False
        self.last_signal_id: str = "0-0"
        self.prev_guard_states: Dict[str, str] = {}
        self.adverse_model: Optional[Any] = None
        self.adverse_model_path: str = ""
        self.adverse_model_loaded: bool = False
        self.sync_state_published_keys: Set[str] = set()
        self.paper_exchange_mode_warned_instances: Set[str] = set()
        self.paper_exchange_auto_mode_by_instance: Dict[str, str] = {}
        self.paper_exchange_auto_mode_updated_ms_by_instance: Dict[str, int] = {}
        self.last_paper_exchange_event_id: str = "0-0"
        self.paper_exchange_seen_event_ids: Set[str] = set()
        self.paper_exchange_cursor_initialized: bool = False
        self.sync_requested_at_ms_by_key: Dict[str, int] = {}
        self.sync_confirmed_keys: Set[str] = set()
        self.sync_timeout_hard_stop_keys: Set[str] = set()
        self.active_failure_streak_by_key: Dict[str, int] = {}
        self.active_submit_order_cache: Dict[str, Tuple[str, float]] = {}
        self.active_cancel_command_cache: Dict[str, Tuple[str, float]] = {}
        self.active_cancel_all_command_cache: Dict[str, Tuple[str, float]] = {}

    def get_redis(self) -> Optional[Any]:
        """Lazy-init a Redis client for signal consumption. Returns None when unavailable."""
        if self.redis_init_done:
            return self.redis_client
        self.redis_init_done = True
        try:
            import redis as _redis_lib
            import os as _os
            host = _os.environ.get("REDIS_HOST", "")
            if not host:
                return None
            self.redis_client = _redis_lib.Redis(
                host=host,
                port=int(_os.environ.get("REDIS_PORT", "6379")),
                db=int(_os.environ.get("REDIS_DB", "0")),
                password=_os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                socket_keepalive=True,
            )
            logger.info("Signal consumer Redis client initialized (%s)", host)
            return self.redis_client
        except Exception as exc:
            logger.warning("Signal consumer Redis init failed: %s", exc)
            return None


_bridge_state = BridgeState()


def _get_signal_redis() -> Optional[Any]:
    """Lazy-init a Redis client for signal consumption. Returns None when unavailable."""
    return _bridge_state.get_redis()


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


def _instance_env_suffix(instance_name: str) -> str:
    raw = str(instance_name or "").strip().upper()
    return "".join(ch if ch.isalnum() else "_" for ch in raw)


def _normalize_paper_exchange_mode(
    raw_mode: str,
    *,
    default: str = "disabled",
    allow_auto: bool = False,
) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in {"disabled", "shadow", "active"}:
        return mode
    if allow_auto and mode == "auto":
        return mode
    return str(default or "").strip().lower()


def _parse_env_bool(raw_value: str, *, default: bool = False) -> bool:
    value = str(raw_value or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _paper_exchange_service_only_for_instance(instance_name: str) -> bool:
    import os as _os

    global_value = _parse_env_bool(_os.getenv("PAPER_EXCHANGE_SERVICE_ONLY", "false"), default=False)
    suffix = _instance_env_suffix(instance_name)
    override_key = f"PAPER_EXCHANGE_SERVICE_ONLY_{suffix}" if suffix else ""
    if override_key and override_key in _os.environ:
        return _parse_env_bool(_os.getenv(override_key, ""), default=global_value)
    return global_value


def _paper_exchange_service_heartbeat_is_fresh(redis_client: Any) -> bool:
    import os as _os

    stream_name = str(
        _os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1")
    ).strip() or "hb.paper_exchange.heartbeat.v1"
    max_age_ms = max(
        1_000,
        int(float(_os.getenv("PAPER_EXCHANGE_AUTO_MAX_HEARTBEAT_AGE_MS", "15000"))),
    )
    try:
        rows = redis_client.xrevrange(stream_name, count=1)
    except Exception:
        return False
    if not isinstance(rows, list) or len(rows) == 0:
        return False
    first = rows[0]
    if not isinstance(first, (list, tuple)) or len(first) < 1:
        return False
    try:
        entry_ms = int(str(first[0]).split("-", 1)[0])
    except Exception:
        return False
    now_ms = int(time.time() * 1000)
    age_ms = now_ms - entry_ms
    return age_ms >= 0 and age_ms <= max_age_ms


def _paper_exchange_auto_mode(instance_name: str, *, strict_service_only: bool = False) -> str:
    import os as _os

    cache_ms = max(0, int(float(_os.getenv("PAPER_EXCHANGE_AUTO_CACHE_MS", "5000"))))
    instance_key = f"{str(instance_name or 'default')}|strict:{1 if strict_service_only else 0}"
    now_ms = int(time.time() * 1000)
    last_updated_ms = int(
        _bridge_state.paper_exchange_auto_mode_updated_ms_by_instance.get(instance_key, 0) or 0
    )
    cached_mode = str(_bridge_state.paper_exchange_auto_mode_by_instance.get(instance_key, "") or "")
    if cached_mode and cache_ms > 0 and (now_ms - last_updated_ms) <= cache_ms:
        return cached_mode

    fallback_mode = _normalize_paper_exchange_mode(
        _os.getenv("PAPER_EXCHANGE_AUTO_FALLBACK", "shadow"),
        default="shadow",
        allow_auto=False,
    )
    redis_client = _get_signal_redis()
    resolved_mode = (
        "active"
        if (redis_client is not None and _paper_exchange_service_heartbeat_is_fresh(redis_client))
        else ("active" if strict_service_only else fallback_mode)
    )
    _bridge_state.paper_exchange_auto_mode_by_instance[instance_key] = resolved_mode
    _bridge_state.paper_exchange_auto_mode_updated_ms_by_instance[instance_key] = now_ms
    return resolved_mode


def _paper_exchange_cursor_key(strategy: Any) -> str:
    """Return per-instance Redis key used to persist event-stream cursor."""
    instance_name = "default"
    controllers = getattr(strategy, "controllers", {})
    if isinstance(controllers, dict):
        for ctrl in controllers.values():
            cfg = getattr(ctrl, "config", None)
            if cfg is None:
                continue
            candidate = str(getattr(cfg, "instance_name", "") or "").strip()
            if candidate:
                instance_name = candidate
                break
    return f"paper_exchange:last_event_id:{instance_name}"


def _bootstrap_paper_exchange_cursor(strategy: Any, redis_client: Any, stream_name: str) -> None:
    """Initialize stream cursor once per process, preferring persisted offset.

    If no persisted cursor exists, start from the latest stream entry to avoid
    replaying historical events on process restarts.
    """
    if _bridge_state.paper_exchange_cursor_initialized:
        return
    _bridge_state.paper_exchange_cursor_initialized = True

    cursor_key = _paper_exchange_cursor_key(strategy)
    try:
        saved_cursor = redis_client.get(cursor_key)
    except Exception:
        saved_cursor = None

    if isinstance(saved_cursor, bytes):
        try:
            saved_cursor = saved_cursor.decode("utf-8")
        except Exception:
            saved_cursor = None

    if isinstance(saved_cursor, str) and "-" in saved_cursor:
        _bridge_state.last_paper_exchange_event_id = saved_cursor
        return

    latest_id: Optional[str] = None
    try:
        latest_entries = redis_client.xrevrange(stream_name, count=1)
        if (
            isinstance(latest_entries, list)
            and len(latest_entries) > 0
            and isinstance(latest_entries[0], (list, tuple))
            and len(latest_entries[0]) >= 1
        ):
            latest_id = str(latest_entries[0][0])
    except Exception:
        latest_id = None

    if latest_id:
        _bridge_state.last_paper_exchange_event_id = latest_id
        try:
            redis_client.set(cursor_key, latest_id)
        except Exception:
            pass


def _paper_exchange_mode_for_instance(instance_name: str) -> str:
    import os as _os

    strict_service_only = _paper_exchange_service_only_for_instance(instance_name)
    default_mode = _normalize_paper_exchange_mode(
        _os.getenv("PAPER_EXCHANGE_MODE", "disabled"),
        default="disabled",
        allow_auto=True,
    )
    suffix = _instance_env_suffix(instance_name)
    override_key = f"PAPER_EXCHANGE_MODE_{suffix}" if suffix else ""
    override_mode = (
        _normalize_paper_exchange_mode(
            _os.getenv(override_key, ""),
            default="",
            allow_auto=True,
        )
        if override_key
        else ""
    )
    mode = override_mode or default_mode or "disabled"
    if mode == "auto":
        resolved_mode = _paper_exchange_auto_mode(
            instance_name,
            strict_service_only=strict_service_only,
        )
    else:
        resolved_mode = _normalize_paper_exchange_mode(mode, default="disabled", allow_auto=False)
    if strict_service_only and resolved_mode in {"disabled", "shadow"}:
        return "active"
    return resolved_mode


def _resolve_controller_for_command(
    strategy: Any,
    connector_name: str,
    trading_pair: str,
) -> Tuple[Optional[Any], str, str]:
    controllers = getattr(strategy, "controllers", {})
    if isinstance(controllers, dict):
        for controller_id, ctrl in controllers.items():
            cfg = getattr(ctrl, "config", None)
            if cfg is None:
                continue
            cfg_connector = str(getattr(cfg, "connector_name", "") or "")
            cfg_pair = str(getattr(cfg, "trading_pair", "") or "")
            if cfg_connector == str(connector_name) and (not trading_pair or cfg_pair == str(trading_pair)):
                instance_name = str(getattr(cfg, "instance_name", "") or controller_id)
                return ctrl, str(controller_id), instance_name
    ctrl = _find_controller_for_connector(strategy, connector_name)
    if ctrl is None:
        return None, "", ""
    cfg = getattr(ctrl, "config", None)
    instance_name = str(getattr(cfg, "instance_name", "") or "")
    controller_id = str(getattr(ctrl, "id", "") or getattr(ctrl, "controller_id", "") or "")
    return ctrl, controller_id, instance_name


def _paper_exchange_mode_for_route(strategy: Any, connector_name: str, trading_pair: str) -> str:
    _ctrl, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    return _paper_exchange_mode_for_instance(instance_name)


def _bridge_for_exchange_event(
    strategy: Any, connector_name: str, trading_pair: str
) -> Tuple[Optional[str], Optional[Dict[str, object]]]:
    bridges = getattr(strategy, "_paper_desk_v2_bridges", {})
    if not isinstance(bridges, dict):
        return None, None

    # Fast path: exact connector key hit.
    bridge = bridges.get(connector_name)
    if isinstance(bridge, dict):
        iid = bridge.get("instrument_id")
        iid_pair = str(getattr(iid, "trading_pair", "") or "")
        if not trading_pair or iid_pair == trading_pair:
            return connector_name, bridge

    # Fallback: canonical connector + pair match.
    target_canonical = _canonical_name(str(connector_name))
    for conn_name, candidate in bridges.items():
        if not isinstance(candidate, dict):
            continue
        iid = candidate.get("instrument_id")
        iid_pair = str(getattr(iid, "trading_pair", "") or "")
        if trading_pair and iid_pair != trading_pair:
            continue
        if _canonical_name(str(conn_name)) == target_canonical:
            return str(conn_name), candidate

    return None, None


def _sync_handshake_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return f"{str(instance_name or '').strip()}|{_canonical_name(str(connector_name or ''))}|{str(trading_pair or '').strip().upper()}"


def _active_submit_retry_ttl_s() -> float:
    import os as _os

    try:
        ttl = float(_os.getenv("PAPER_EXCHANGE_SUBMIT_RETRY_TTL_S", "1.0"))
    except Exception:
        ttl = 1.0
    return max(0.0, ttl)


def _active_submit_fingerprint(
    *,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    side: str,
    order_type: Optional[Any],
    amount: Optional[Any],
    price: Optional[Any],
) -> str:
    def _fmt_decimal(value: Optional[Any]) -> str:
        if value is None:
            return ""
        try:
            parsed = Decimal(str(value))
            if parsed.is_nan():
                return "nan"
            return format(parsed.normalize(), "f")
        except Exception:
            return str(value)

    order_type_text = str(getattr(order_type, "name", order_type) or "").strip().lower()
    return "|".join(
        [
            str(instance_name or "").strip().lower(),
            _canonical_name(str(connector_name or "")),
            str(trading_pair or "").strip().upper(),
            str(side or "").strip().lower(),
            order_type_text,
            _fmt_decimal(amount),
            _fmt_decimal(price),
        ]
    )


def _active_submit_order_id(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    side: str,
    order_type: Optional[Any],
    amount: Optional[Any],
    price: Optional[Any],
) -> str:
    import uuid as _uuid_mod

    _ctrl, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    fingerprint = _active_submit_fingerprint(
        instance_name=instance_name,
        connector_name=connector_name,
        trading_pair=trading_pair,
        side=side,
        order_type=order_type,
        amount=amount,
        price=price,
    )
    now = time.time()
    ttl_s = _active_submit_retry_ttl_s()

    cache = _bridge_state.active_submit_order_cache
    if cache:
        prune_after = max(1.0, ttl_s * 3.0)
        stale_keys = [k for k, (_oid, ts) in cache.items() if (now - float(ts)) > prune_after]
        for key in stale_keys:
            cache.pop(key, None)

    if ttl_s > 0.0:
        cached = cache.get(fingerprint)
        if cached is not None:
            cached_order_id, cached_ts = cached
            order_id_text = str(cached_order_id or "").strip()
            if order_id_text and (now - float(cached_ts)) <= ttl_s:
                runtime_order = _get_runtime_order_for_executor(strategy, connector_name, order_id_text)
                runtime_state = str(getattr(runtime_order, "current_state", "") or "").strip().lower() if runtime_order else ""
                if runtime_order is None or runtime_state in {
                    "pending_create", "open", "pending_cancel", "partial", "failed", "rejected",
                }:
                    return order_id_text
            else:
                cache.pop(fingerprint, None)

    order_id = f"pe-{_uuid_mod.uuid4().hex[:16]}"
    cache[fingerprint] = (order_id, now)
    return order_id


def _active_cancel_retry_ttl_s() -> float:
    import os as _os

    try:
        ttl = float(_os.getenv("PAPER_EXCHANGE_CANCEL_RETRY_TTL_S", "1.0"))
    except Exception:
        ttl = 1.0
    return max(0.0, ttl)


def _active_cancel_fingerprint(
    *,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    order_id: str,
) -> str:
    return "|".join(
        [
            str(instance_name or "").strip().lower(),
            _canonical_name(str(connector_name or "")),
            str(trading_pair or "").strip().upper(),
            str(order_id or "").strip(),
        ]
    )


def _active_cancel_command_event_id(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    order_id: str,
) -> Optional[str]:
    import uuid as _uuid_mod

    order_key = str(order_id or "").strip()
    if not order_key:
        return None
    _ctrl, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    fingerprint = _active_cancel_fingerprint(
        instance_name=instance_name,
        connector_name=connector_name,
        trading_pair=trading_pair,
        order_id=order_key,
    )
    now = time.time()
    ttl_s = _active_cancel_retry_ttl_s()

    cache = _bridge_state.active_cancel_command_cache
    if cache:
        prune_after = max(1.0, ttl_s * 3.0)
        stale_keys = [k for k, (_event_id, ts) in cache.items() if (now - float(ts)) > prune_after]
        for key in stale_keys:
            cache.pop(key, None)

    if ttl_s > 0.0:
        cached = cache.get(fingerprint)
        if cached is not None:
            cached_event_id, cached_ts = cached
            event_id_text = str(cached_event_id or "").strip()
            if event_id_text and (now - float(cached_ts)) <= ttl_s:
                return event_id_text
            cache.pop(fingerprint, None)

    command_event_id = f"pe-cancel-{_uuid_mod.uuid4().hex}"
    cache[fingerprint] = (command_event_id, now)
    return command_event_id


def _active_cancel_all_retry_ttl_s() -> float:
    import os as _os

    try:
        ttl = float(_os.getenv("PAPER_EXCHANGE_CANCEL_ALL_RETRY_TTL_S", "1.0"))
    except Exception:
        ttl = 1.0
    return max(0.0, ttl)


def _active_cancel_all_fingerprint(
    *,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    metadata: Optional[Dict[str, str]] = None,
) -> str:
    meta = metadata or {}
    operator = str(meta.get("operator", "")).strip()
    reason = str(meta.get("reason", "")).strip()
    change_ticket = str(meta.get("change_ticket", "")).strip()
    return "|".join(
        [
            str(instance_name or "").strip().lower(),
            _canonical_name(str(connector_name or "")),
            str(trading_pair or "").strip().upper(),
            operator,
            reason,
            change_ticket,
        ]
    )


def _active_cancel_all_command_event_id(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    metadata: Optional[Dict[str, str]] = None,
) -> str:
    import uuid as _uuid_mod

    _ctrl, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    fingerprint = _active_cancel_all_fingerprint(
        instance_name=instance_name,
        connector_name=connector_name,
        trading_pair=trading_pair,
        metadata=metadata,
    )
    now = time.time()
    ttl_s = _active_cancel_all_retry_ttl_s()

    cache = _bridge_state.active_cancel_all_command_cache
    if cache:
        prune_after = max(1.0, ttl_s * 3.0)
        stale_keys = [k for k, (_event_id, ts) in cache.items() if (now - float(ts)) > prune_after]
        for key in stale_keys:
            cache.pop(key, None)

    if ttl_s > 0.0:
        cached = cache.get(fingerprint)
        if cached is not None:
            cached_event_id, cached_ts = cached
            event_id_text = str(cached_event_id or "").strip()
            if event_id_text and (now - float(cached_ts)) <= ttl_s:
                return event_id_text
            cache.pop(fingerprint, None)

    command_event_id = f"pe-cancel-all-{_uuid_mod.uuid4().hex}"
    cache[fingerprint] = (command_event_id, now)
    return command_event_id


def _runtime_orders_store(strategy: Any) -> Dict[str, Dict[str, Any]]:
    store = getattr(strategy, "_paper_exchange_runtime_orders", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        setattr(strategy, "_paper_exchange_runtime_orders", store)
    except Exception:
        pass
    return store


def _runtime_orders_bucket(strategy: Any, connector_name: str) -> Dict[str, Any]:
    store = _runtime_orders_store(strategy)
    key = str(connector_name or "")
    bucket = store.get(key)
    if isinstance(bucket, dict):
        return bucket
    bucket = {}
    store[key] = bucket
    return bucket


def _runtime_order_trade_type(side: Optional[str]) -> str:
    side_norm = str(side or "").strip().lower()
    return "BUY" if side_norm == "buy" else "SELL"


def _runtime_order_state_flags(state: str) -> Tuple[bool, bool]:
    normalized = str(state or "").strip().lower()
    if normalized in {"filled", "canceled", "cancelled", "failed", "rejected", "expired"}:
        return True, False
    if normalized in {"open", "pending_create", "pending_cancel", "partial"}:
        return False, True
    return False, False


def _upsert_runtime_order(
    strategy: Any,
    *,
    connector_name: str,
    order_id: str,
    trading_pair: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[Any] = None,
    amount: Optional[Any] = None,
    price: Optional[Any] = None,
    state: Optional[str] = None,
    failure_reason: str = "",
) -> Optional[Any]:
    order_key = str(order_id or "").strip()
    if not order_key:
        return None
    now = time.time()
    bucket = _runtime_orders_bucket(strategy, connector_name)
    order = bucket.get(order_key)
    if order is None:
        order = SimpleNamespace(
            client_order_id=order_key,
            order_id=order_key,
            exchange_order_id=None,
            trading_pair=str(trading_pair or ""),
            trade_type=_runtime_order_trade_type(side),
            order_type=str(getattr(order_type, "name", order_type) or "").upper(),
            amount=Decimal(str(amount)) if amount is not None else Decimal("0"),
            price=Decimal(str(price)) if price is not None else Decimal("0"),
            current_state="pending_create",
            is_done=False,
            is_open=True,
            creation_timestamp=now,
            last_update_timestamp=now,
            executed_amount_base=Decimal("0"),
            executed_amount_quote=Decimal("0"),
            cumulative_fee_paid=Decimal("0"),
            failure_reason="",
            source="paper_exchange_service",
        )
        bucket[order_key] = order
    else:
        if trading_pair is not None:
            order.trading_pair = str(trading_pair)
        if side is not None:
            order.trade_type = _runtime_order_trade_type(side)
        if order_type is not None:
            order.order_type = str(getattr(order_type, "name", order_type) or "").upper()
        if amount is not None:
            order.amount = Decimal(str(amount))
        if price is not None:
            order.price = Decimal(str(price))
        order.last_update_timestamp = now

    if state is not None:
        state_text = str(state).strip().lower()
        is_done, is_open = _runtime_order_state_flags(state_text)
        order.current_state = state_text
        order.is_done = bool(is_done)
        order.is_open = bool(is_open)
        order.last_update_timestamp = now
    if failure_reason:
        order.failure_reason = str(failure_reason)
    return order


def _prune_runtime_orders(strategy: Any, *, done_ttl_sec: float = 120.0) -> None:
    store = _runtime_orders_store(strategy)
    now = time.time()
    for connector_name in list(store.keys()):
        bucket = store.get(connector_name)
        if not isinstance(bucket, dict):
            continue
        for order_id in list(bucket.keys()):
            order = bucket.get(order_id)
            if order is None:
                continue
            is_done = bool(getattr(order, "is_done", False))
            updated_ts = float(getattr(order, "last_update_timestamp", now))
            if is_done and (now - updated_ts) > float(done_ttl_sec):
                bucket.pop(order_id, None)
        if not bucket:
            store.pop(connector_name, None)


def _get_runtime_order_for_executor(strategy: Any, connector_name: str, order_id: str) -> Optional[Any]:
    if strategy is None:
        return None
    _prune_runtime_orders(strategy)
    order_key = str(order_id or "").strip()
    if not order_key:
        return None

    store = _runtime_orders_store(strategy)
    direct_bucket = store.get(str(connector_name or ""))
    if isinstance(direct_bucket, dict):
        direct = direct_bucket.get(order_key)
        if direct is not None:
            return direct

    target_canonical = _canonical_name(str(connector_name or ""))
    for key, bucket in store.items():
        if not isinstance(bucket, dict):
            continue
        if _canonical_name(str(key)) != target_canonical:
            continue
        order = bucket.get(order_key)
        if order is not None:
            return order
    return None


def _force_sync_hard_stop(
    strategy: Any,
    *,
    controller: Optional[Any],
    controller_id: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    sync_key: str,
    reason: str,
) -> None:
    if sync_key in _bridge_state.sync_timeout_hard_stop_keys:
        return
    _bridge_state.sync_timeout_hard_stop_keys.add(sync_key)

    try:
        ops_guard = getattr(controller, "_ops_guard", None)
        if ops_guard is not None and hasattr(ops_guard, "force_hard_stop"):
            ops_guard.force_hard_stop(str(reason))
            logger.error(
                "paper_exchange sync hard-stop forced | instance=%s controller=%s connector=%s pair=%s reason=%s",
                instance_name,
                controller_id,
                connector_name,
                trading_pair,
                reason,
            )
    except Exception as exc:
        logger.warning("paper_exchange sync hard-stop escalation failed: %s", exc)

    try:
        import json as _json
        from services.contracts.event_schemas import AuditEvent
        from services.contracts.stream_names import AUDIT_STREAM, STREAM_RETENTION_MAXLEN

        r = _get_signal_redis()
        if r is not None:
            audit = AuditEvent(
                producer="hb.paper_engine_v2",
                instance_name=instance_name or connector_name,
                severity="error",
                category="paper_exchange_sync",
                message="active_mode_sync_hard_stop",
                metadata={
                    "reason": str(reason),
                    "controller_id": str(controller_id),
                    "connector_name": str(connector_name),
                    "trading_pair": str(trading_pair),
                },
            )
            r.xadd(
                AUDIT_STREAM,
                {"payload": _json.dumps(audit.model_dump(), default=str)},
                maxlen=STREAM_RETENTION_MAXLEN.get(AUDIT_STREAM, 100_000),
                approximate=True,
            )
    except Exception:
        logger.debug("paper_exchange sync hard-stop audit publish failed", exc_info=True)


def _active_failure_hard_stop_streak() -> int:
    import os as _os

    try:
        parsed = int(float(_os.getenv("PAPER_EXCHANGE_FAILURE_HARD_STOP_STREAK", "3")))
    except Exception:
        parsed = 3
    return max(2, parsed)


def _apply_controller_soft_pause(controller: Optional[Any], reason: str) -> None:
    if controller is None:
        return
    try:
        if hasattr(controller, "apply_execution_intent"):
            controller.apply_execution_intent({"action": "soft_pause", "metadata": {"reason": str(reason)}})
            return
    except Exception:
        logger.debug("paper_exchange soft-pause intent apply failed", exc_info=True)
    try:
        if hasattr(controller, "set_external_soft_pause"):
            controller.set_external_soft_pause(True, str(reason))
    except Exception:
        logger.debug("paper_exchange soft-pause fallback failed", exc_info=True)


def _apply_controller_resume(controller: Optional[Any], reason: str) -> None:
    if controller is None:
        return
    try:
        if hasattr(controller, "apply_execution_intent"):
            controller.apply_execution_intent({"action": "resume", "metadata": {"reason": str(reason)}})
            return
    except Exception:
        logger.debug("paper_exchange resume intent apply failed", exc_info=True)
    try:
        if hasattr(controller, "set_external_soft_pause"):
            controller.set_external_soft_pause(False, "")
    except Exception:
        logger.debug("paper_exchange resume fallback failed", exc_info=True)


def _apply_active_failure_policy(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    failure_class: str,
    reason: str,
) -> str:
    controller, controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    sync_key = _sync_handshake_key(instance_name, connector_name, trading_pair)
    current_streak = int(_bridge_state.active_failure_streak_by_key.get(sync_key, 0))
    next_streak = current_streak + 1
    _bridge_state.active_failure_streak_by_key[sync_key] = next_streak

    hard_stop_streak = _active_failure_hard_stop_streak()
    failure_class_norm = str(failure_class or "").strip().lower() or "unknown"
    reason_norm = str(reason or "").strip().lower() or "unknown"
    if next_streak >= hard_stop_streak:
        hard_stop_reason = f"paper_exchange_recovery_loop:{failure_class_norm}:{reason_norm}"
        _force_sync_hard_stop(
            strategy,
            controller=controller,
            controller_id=controller_id,
            instance_name=instance_name,
            connector_name=connector_name,
            trading_pair=trading_pair,
            sync_key=sync_key,
            reason=hard_stop_reason,
        )
        return "hard_stop"

    soft_pause_reason = f"paper_exchange_soft_pause:{failure_class_norm}:{reason_norm}"
    _apply_controller_soft_pause(controller, soft_pause_reason)
    logger.warning(
        "paper_exchange active failure policy soft-pause | instance=%s connector=%s pair=%s class=%s reason=%s streak=%s",
        instance_name,
        connector_name,
        trading_pair,
        failure_class_norm,
        reason_norm,
        next_streak,
    )
    return "soft_pause"


def _mark_active_failure_recovered(strategy: Any, *, connector_name: str, trading_pair: str) -> None:
    controller, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    sync_key = _sync_handshake_key(instance_name, connector_name, trading_pair)
    previous_streak = int(_bridge_state.active_failure_streak_by_key.pop(sync_key, 0))
    if previous_streak > 0:
        _apply_controller_resume(controller, f"paper_exchange_recovered:streak={previous_streak}")


def _active_sync_gate(strategy: Any, connector_name: str, trading_pair: str) -> Tuple[bool, str]:
    import os as _os

    mode = _paper_exchange_mode_for_route(strategy, connector_name, trading_pair)
    if mode != "active":
        return True, "not_active_mode"

    controller, controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    if instance_name and instance_name not in _bridge_state.paper_exchange_mode_warned_instances:
        logger.info(
            "paper_exchange active sync gate enabled | instance=%s connector=%s pair=%s",
            instance_name,
            connector_name,
            trading_pair,
        )
        _bridge_state.paper_exchange_mode_warned_instances.add(instance_name)
    sync_key = _sync_handshake_key(instance_name, connector_name, trading_pair)
    if sync_key in _bridge_state.sync_confirmed_keys:
        return True, "sync_confirmed"

    _ensure_sync_state_command(strategy, connector_name, trading_pair)

    now_ms = int(time.time() * 1000)
    requested_at_ms = _bridge_state.sync_requested_at_ms_by_key.get(sync_key, now_ms)
    timeout_ms = max(1_000, int(float(_os.getenv("PAPER_EXCHANGE_SYNC_TIMEOUT_MS", "30000"))))
    if now_ms - requested_at_ms >= timeout_ms:
        _force_sync_hard_stop(
            strategy,
            controller=controller,
            controller_id=controller_id,
            instance_name=instance_name,
            connector_name=connector_name,
            trading_pair=trading_pair,
            sync_key=sync_key,
            reason="paper_exchange_sync_timeout",
        )
        return False, "paper_exchange_sync_timeout"
    return False, "paper_exchange_sync_pending"


def _fmt_contract_decimal(value: Any) -> str:
    try:
        if value is None:
            return ""
        parsed = Decimal(str(value))
        if parsed.is_nan():
            return ""
        return format(parsed, "f")
    except Exception:
        return ""


def _controller_accounting_contract_metadata(controller: Optional[Any]) -> Dict[str, str]:
    if controller is None:
        return {}

    out: Dict[str, str] = {}
    maker_fee = _fmt_contract_decimal(getattr(controller, "_maker_fee_pct", None))
    taker_fee = _fmt_contract_decimal(getattr(controller, "_taker_fee_pct", None))
    funding_rate = _fmt_contract_decimal(getattr(controller, "_funding_rate", None))
    fee_source = str(getattr(controller, "_fee_source", "") or "").strip()

    cfg = getattr(controller, "config", None)
    leverage_text = _fmt_contract_decimal(getattr(cfg, "leverage", None))

    margin_mode = ""
    try:
        portfolio = getattr(controller, "_portfolio", None)
        portfolio_cfg = getattr(portfolio, "_config", None)
        margin_mode = str(getattr(portfolio_cfg, "margin_model_type", "") or "").strip().lower()
    except Exception:
        margin_mode = ""
    if margin_mode not in {"leveraged", "standard"}:
        margin_mode = "leveraged"

    if maker_fee:
        out["maker_fee_pct"] = maker_fee
    if taker_fee:
        out["taker_fee_pct"] = taker_fee
    if funding_rate:
        out["funding_rate"] = funding_rate
    if fee_source:
        out["fee_source"] = fee_source
    if leverage_text:
        out["leverage"] = leverage_text
    out["margin_mode"] = margin_mode
    out["accounting_contract_version"] = "paper_exchange_v1"
    return out


def _publish_paper_exchange_command(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    command: str,
    order_id: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[Any] = None,
    amount_base: Optional[Any] = None,
    price: Optional[Any] = None,
    metadata: Optional[Dict[str, str]] = None,
    command_event_id: Optional[str] = None,
) -> Optional[str]:
    import json as _json
    import os as _os
    import uuid as _uuid_mod

    _ctrl, controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    mode = _paper_exchange_mode_for_instance(instance_name)
    if mode not in {"shadow", "active"}:
        return None

    r = _get_signal_redis()
    if r is None:
        if mode == "active":
            _apply_active_failure_policy(
                strategy,
                connector_name=connector_name,
                trading_pair=trading_pair,
                failure_class="service_down",
                reason="redis_unavailable",
            )
        return None

    try:
        from services.contracts.stream_names import PAPER_EXCHANGE_COMMAND_STREAM, STREAM_RETENTION_MAXLEN

        order_type_raw = getattr(order_type, "name", order_type)
        order_type_value = str(order_type_raw).strip().lower() if order_type_raw is not None else None
        amount_value = float(amount_base) if amount_base is not None else None
        price_value: Optional[float] = None
        if price is not None:
            try:
                # Decimal("NaN") check
                if price == price:
                    price_value = float(price)
            except Exception:
                price_value = None

        ttl_ms = max(1_000, int(float(_os.getenv("PAPER_EXCHANGE_COMMAND_TTL_MS", "30000"))))
        command_meta = {
            "source": "hb_bridge_active_adapter" if mode == "active" else "hb_bridge_shadow_adapter",
            "paper_exchange_mode": mode,
            "controller_id": controller_id,
        }
        command_meta.update(_controller_accounting_contract_metadata(_ctrl))
        command_producer = "hb_bridge_active_adapter" if mode == "active" else "hb_bridge_shadow_adapter"
        if metadata:
            for key, value in metadata.items():
                command_meta[str(key)] = str(value)

        resolved_command_event_id = str(command_event_id or "").strip() or None
        if resolved_command_event_id is None and mode == "active" and str(command or "").strip().lower() == "cancel_all":
            resolved_command_event_id = _active_cancel_all_command_event_id(
                strategy,
                connector_name=connector_name,
                trading_pair=trading_pair,
                metadata=command_meta,
            )

        event = build_paper_execution_command(
            event_id=resolved_command_event_id or str(_uuid_mod.uuid4()),
            producer=command_producer,
            instance_name=instance_name or str(connector_name),
            command=command,
            connector_name=str(connector_name),
            trading_pair=str(trading_pair),
            order_id=str(order_id) if order_id else None,
            side=side.lower() if isinstance(side, str) else None,
            order_type=order_type_value,
            amount_base=amount_value,
            price=price_value,
            reduce_only=str(command_meta.get("reduce_only", "")).strip().lower() in {"1", "true", "yes"},
            position_action=str(command_meta.get("position_action", "") or "").strip().lower() or None,
            position_mode=str(command_meta.get("position_mode", "") or "").strip().upper() or None,
            ttl_ms=ttl_ms,
            metadata=command_meta,
        )
        entry_id = r.xadd(
            PAPER_EXCHANGE_COMMAND_STREAM,
            {"payload": _json.dumps(event.model_dump(), default=str)},
            maxlen=STREAM_RETENTION_MAXLEN.get(PAPER_EXCHANGE_COMMAND_STREAM, 100_000),
            approximate=True,
        )
        if entry_id is None and mode == "active":
            _apply_active_failure_policy(
                strategy,
                connector_name=connector_name,
                trading_pair=trading_pair,
                failure_class="service_down",
                reason="command_publish_failed",
            )
        return entry_id
    except Exception as exc:
        if mode == "active":
            _apply_active_failure_policy(
                strategy,
                connector_name=connector_name,
                trading_pair=trading_pair,
                failure_class="service_down",
                reason=f"command_publish_exception:{type(exc).__name__}",
            )
        logger.debug("paper_exchange command publish failed: %s", exc, exc_info=True)
        return None


def _ensure_sync_state_command(strategy: Any, connector_name: str, trading_pair: str) -> None:
    _ctrl, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    mode = _paper_exchange_mode_for_instance(instance_name)
    if mode not in {"shadow", "active"}:
        return
    sync_key = _sync_handshake_key(instance_name, connector_name, trading_pair)
    if sync_key in _bridge_state.sync_confirmed_keys:
        return
    if sync_key in _bridge_state.sync_state_published_keys:
        _bridge_state.sync_requested_at_ms_by_key.setdefault(sync_key, int(time.time() * 1000))
        return
    entry_id = _publish_paper_exchange_command(
        strategy,
        connector_name=connector_name,
        trading_pair=trading_pair,
        command="sync_state",
        metadata={"sync_reason": "bridge_startup"},
    )
    if entry_id:
        _bridge_state.sync_state_published_keys.add(sync_key)
        _bridge_state.sync_requested_at_ms_by_key[sync_key] = int(time.time() * 1000)


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
        from services.contracts.event_schemas import PaperExchangeEvent
        from controllers.paper_engine_v2.types import OrderCanceled as _OrderCanceled
        from controllers.paper_engine_v2.types import OrderFilled as _OrderFilled
        from controllers.paper_engine_v2.types import OrderRejected as _OrderRejected
        from services.contracts.stream_names import PAPER_EXCHANGE_EVENT_STREAM

        _bootstrap_paper_exchange_cursor(strategy, r, PAPER_EXCHANGE_EVENT_STREAM)
        cursor_key = _paper_exchange_cursor_key(strategy)
        result = r.xread({PAPER_EXCHANGE_EVENT_STREAM: _bridge_state.last_paper_exchange_event_id}, count=200, block=0)
        if not result:
            return

        latest_seen_entry_id: Optional[str] = None
        for _stream_name, entries in result:
            for entry_id, data in entries:
                _bridge_state.last_paper_exchange_event_id = str(entry_id)
                latest_seen_entry_id = _bridge_state.last_paper_exchange_event_id
                raw = data.get("payload")
                if not isinstance(raw, str):
                    continue
                try:
                    payload = _json.loads(raw)
                    event = PaperExchangeEvent(**payload)
                except Exception:
                    continue

                if event.event_id in _bridge_state.paper_exchange_seen_event_ids:
                    continue
                _bridge_state.paper_exchange_seen_event_ids.add(event.event_id)
                if len(_bridge_state.paper_exchange_seen_event_ids) > 20_000:
                    # Keep memory bounded; stream-id cursor still prevents replay in normal flow.
                    _bridge_state.paper_exchange_seen_event_ids.clear()

                mode = _paper_exchange_mode_for_instance(str(event.instance_name))
                command = str(event.command or "").strip().lower()
                status = str(event.status).strip().lower()
                reason = str(event.reason or "")
                sync_key = _sync_handshake_key(
                    str(event.instance_name), str(event.connector_name), str(event.trading_pair)
                )
                if command == "sync_state":
                    if status == "processed":
                        _bridge_state.sync_confirmed_keys.add(sync_key)
                        _bridge_state.sync_timeout_hard_stop_keys.discard(sync_key)
                        _mark_active_failure_recovered(
                            strategy,
                            connector_name=str(event.connector_name),
                            trading_pair=str(event.trading_pair),
                        )
                        continue
                    if status == "rejected" and mode == "active":
                        controller, controller_id, instance_name = _resolve_controller_for_command(
                            strategy, str(event.connector_name), str(event.trading_pair)
                        )
                        _force_sync_hard_stop(
                            strategy,
                            controller=controller,
                            controller_id=controller_id,
                            instance_name=instance_name,
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
                    )
                    _fire_hb_events(strategy, resolved_connector_name, cancel_event, _bridge_state)
                    continue

                if command == "submit_order" and event.order_id:
                    metadata = event.metadata if isinstance(event.metadata, dict) else {}
                    order_state = str(metadata.get("order_state", "working")).strip().lower()
                    runtime_state = "open"
                    if order_state in {"filled", "expired", "rejected", "cancelled", "canceled"}:
                        runtime_state = "filled" if order_state == "filled" else order_state
                    elif order_state in {"partially_filled", "partial"}:
                        runtime_state = "partial"
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
                            )
                            _fire_hb_events(strategy, resolved_connector_name, fill_event, _bridge_state)
                    continue

                if command in {"order_fill", "fill", "fill_order"} and event.order_id:
                    metadata = event.metadata if isinstance(event.metadata, dict) else {}
                    order_state = str(metadata.get("order_state", "partially_filled")).strip().lower()
                    runtime_state = "partial" if order_state in {"partial", "partially_filled"} else "filled"
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
                        fill_qty = Decimal(str(metadata.get("fill_amount_base", "0")))
                        fill_fee = Decimal(str(metadata.get("fill_fee_quote", "0")))
                        remaining = Decimal(str(metadata.get("remaining_amount_base", "0")))
                    except Exception:
                        fill_price = Decimal("0")
                        fill_qty = Decimal("0")
                        fill_fee = Decimal("0")
                        remaining = Decimal("0")
                    if fill_price <= _ZERO or fill_qty <= _ZERO:
                        continue
                    is_maker_text = str(metadata.get("is_maker", "0")).strip().lower()
                    is_maker = is_maker_text in {"1", "true", "yes", "y", "on"}
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
            runtime_order = _get_runtime_order_for_executor(getattr(self, "strategy", None), connector_name, order_id)
            if runtime_order is not None:
                return runtime_order
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

        if connector is not None:
            _install_budget_checker(connector, equity)

        _install_order_delegation(strategy, desk, connector_name, instrument_id)

        if connector is not None:
            _patch_connector_balances(connector, desk, instrument_id)

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
            mode = _paper_exchange_mode_for_route(self, conn_name, trading_pair)
            order_type_text = _order_type_text(order_type)
            force_trace = "MARKET" in order_type_text or str(position_action or "").strip() != ""
            _trace_paper_order(
                "stage=bridge_buy_enter connector=%s pair=%s mode=%s amount=%s price=%s order_type=%s position_action=%s",
                conn_name,
                trading_pair,
                mode,
                str(amount),
                str(price),
                order_type_text,
                str(position_action or ""),
                force=force_trace,
            )
            if force_trace:
                logger.warning(
                    "PAPER_ROUTE_PROBE stage=bridge_buy_enter connector=%s pair=%s mode=%s amount=%s order_type=%s",
                    conn_name,
                    trading_pair,
                    mode,
                    str(amount),
                    order_type_text,
                )
            if mode == "active":
                normalized_position_action = _normalize_position_action(position_action, OrderSide.BUY)
                position_mode = str(getattr(getattr(_find_controller_for_connector(self, conn_name), "config", None), "position_mode", "ONEWAY") or "ONEWAY").upper()
                sync_ready, sync_reason = _active_sync_gate(self, conn_name, trading_pair)
                generated_order_id = _active_submit_order_id(
                    self,
                    connector_name=conn_name,
                    trading_pair=trading_pair,
                    side="buy",
                    order_type=order_type,
                    amount=amount,
                    price=price,
                )
                _upsert_runtime_order(
                    self,
                    connector_name=conn_name,
                    order_id=generated_order_id,
                    trading_pair=trading_pair,
                    side="buy",
                    order_type=order_type,
                    amount=amount,
                    price=price,
                    state="pending_create",
                )
                if not sync_ready:
                    _upsert_runtime_order(
                        self,
                        connector_name=conn_name,
                        order_id=generated_order_id,
                        state="failed",
                        failure_reason=sync_reason,
                    )
                    reject_event = OrderRejected(
                        event_id=f"pe-sync-reject-{generated_order_id}",
                        timestamp_ns=int(time.time() * 1e9),
                        instrument_id=_iid,
                        order_id=generated_order_id,
                        reason=sync_reason,
                        source_bot=conn_name,
                    )
                    _fire_hb_events(self, conn_name, reject_event, _bridge_state)
                    _trace_paper_order(
                        "stage=bridge_buy_sync_reject connector=%s pair=%s order_id=%s reason=%s",
                        conn_name,
                        trading_pair,
                        generated_order_id,
                        sync_reason,
                        force=True,
                    )
                    return generated_order_id

                publish_entry_id = _publish_paper_exchange_command(
                    self,
                    connector_name=conn_name,
                    trading_pair=trading_pair,
                    command="submit_order",
                    order_id=generated_order_id,
                    side="buy",
                    order_type=order_type,
                    amount_base=amount,
                    price=price,
                    metadata={
                        "bridge_method": "buy",
                        "compat_adapter": "active",
                        "position_action": normalized_position_action.value,
                        "position_mode": position_mode,
                        "reduce_only": "1" if normalized_position_action == PositionAction.CLOSE_SHORT else "0",
                    },
                )
                if publish_entry_id is None:
                    _upsert_runtime_order(
                        self,
                        connector_name=conn_name,
                        order_id=generated_order_id,
                        state="failed",
                        failure_reason="paper_exchange_command_publish_failed",
                    )
                    reject_event = OrderRejected(
                        event_id=f"pe-local-reject-{generated_order_id}",
                        timestamp_ns=int(time.time() * 1e9),
                        instrument_id=_iid,
                        order_id=generated_order_id,
                        reason="paper_exchange_command_publish_failed",
                        source_bot=conn_name,
                    )
                    _fire_hb_events(self, conn_name, reject_event, _bridge_state)
                    _trace_paper_order(
                        "stage=bridge_buy_publish_failed connector=%s pair=%s order_id=%s",
                        conn_name,
                        trading_pair,
                        generated_order_id,
                        force=True,
                    )
                else:
                    _trace_paper_order(
                        "stage=bridge_buy_published connector=%s pair=%s order_id=%s stream_entry_id=%s",
                        conn_name,
                        trading_pair,
                        generated_order_id,
                        str(publish_entry_id),
                        force=force_trace,
                    )
                return generated_order_id

            _price = price if price == price else _resolve_shadow_submit_price(
                self,
                _desk,
                _iid,
                conn_name,
                trading_pair,
                OrderSide.BUY,
            )
            normalized_position_action = _normalize_position_action(position_action, OrderSide.BUY)
            position_mode = str(getattr(getattr(_find_controller_for_connector(self, conn_name), "config", None), "position_mode", "ONEWAY") or "ONEWAY").upper()
            event = _desk.submit_order(
                _iid, OrderSide.BUY, _hb_order_type_to_v2(order_type),
                Decimal(str(_price)), Decimal(str(amount)),
                source_bot=conn_name,
                position_action=normalized_position_action,
                position_mode=position_mode,
            )
            if force_trace:
                logger.warning(
                    "PAPER_ROUTE_PROBE stage=bridge_buy_submit connector=%s pair=%s order_id=%s event=%s reason=%s",
                    conn_name,
                    trading_pair,
                    str(getattr(event, "order_id", "") or ""),
                    type(event).__name__,
                    str(getattr(event, "reason", "") or ""),
                )
            _publish_paper_exchange_command(
                self,
                connector_name=conn_name,
                trading_pair=trading_pair,
                command="submit_order",
                order_id=str(getattr(event, "order_id", "") or "") or None,
                side="buy",
                order_type=order_type,
                amount_base=amount,
                price=_price,
                metadata={
                    "bridge_method": "buy",
                    "compat_adapter": "shadow",
                    "position_action": normalized_position_action.value,
                    "position_mode": position_mode,
                    "reduce_only": "1" if normalized_position_action == PositionAction.CLOSE_SHORT else "0",
                },
            )
            _trace_paper_order(
                "stage=bridge_buy_desk_submit connector=%s pair=%s order_id=%s event=%s reason=%s",
                conn_name,
                trading_pair,
                str(getattr(event, "order_id", "") or ""),
                type(event).__name__,
                str(getattr(event, "reason", "") or ""),
                force=force_trace or type(event).__name__ != "OrderAccepted",
            )
            _fire_hb_events(self, conn_name, event, _bridge_state)
            return getattr(event, "order_id", None)
        return original_buy(conn_name, trading_pair, amount, order_type, price, position_action=position_action, **kwargs)

    def _patched_sell(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None, **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(conn_name)
        if bridge is not None:
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            mode = _paper_exchange_mode_for_route(self, conn_name, trading_pair)
            order_type_text = _order_type_text(order_type)
            force_trace = "MARKET" in order_type_text or str(position_action or "").strip() != ""
            _trace_paper_order(
                "stage=bridge_sell_enter connector=%s pair=%s mode=%s amount=%s price=%s order_type=%s position_action=%s",
                conn_name,
                trading_pair,
                mode,
                str(amount),
                str(price),
                order_type_text,
                str(position_action or ""),
                force=force_trace,
            )
            if force_trace:
                logger.warning(
                    "PAPER_ROUTE_PROBE stage=bridge_sell_enter connector=%s pair=%s mode=%s amount=%s order_type=%s",
                    conn_name,
                    trading_pair,
                    mode,
                    str(amount),
                    order_type_text,
                )
            if mode == "active":
                normalized_position_action = _normalize_position_action(position_action, OrderSide.SELL)
                position_mode = str(getattr(getattr(_find_controller_for_connector(self, conn_name), "config", None), "position_mode", "ONEWAY") or "ONEWAY").upper()
                sync_ready, sync_reason = _active_sync_gate(self, conn_name, trading_pair)
                generated_order_id = _active_submit_order_id(
                    self,
                    connector_name=conn_name,
                    trading_pair=trading_pair,
                    side="sell",
                    order_type=order_type,
                    amount=amount,
                    price=price,
                )
                _upsert_runtime_order(
                    self,
                    connector_name=conn_name,
                    order_id=generated_order_id,
                    trading_pair=trading_pair,
                    side="sell",
                    order_type=order_type,
                    amount=amount,
                    price=price,
                    state="pending_create",
                )
                if not sync_ready:
                    _upsert_runtime_order(
                        self,
                        connector_name=conn_name,
                        order_id=generated_order_id,
                        state="failed",
                        failure_reason=sync_reason,
                    )
                    reject_event = OrderRejected(
                        event_id=f"pe-sync-reject-{generated_order_id}",
                        timestamp_ns=int(time.time() * 1e9),
                        instrument_id=_iid,
                        order_id=generated_order_id,
                        reason=sync_reason,
                        source_bot=conn_name,
                    )
                    _fire_hb_events(self, conn_name, reject_event, _bridge_state)
                    _trace_paper_order(
                        "stage=bridge_sell_sync_reject connector=%s pair=%s order_id=%s reason=%s",
                        conn_name,
                        trading_pair,
                        generated_order_id,
                        sync_reason,
                        force=True,
                    )
                    return generated_order_id

                publish_entry_id = _publish_paper_exchange_command(
                    self,
                    connector_name=conn_name,
                    trading_pair=trading_pair,
                    command="submit_order",
                    order_id=generated_order_id,
                    side="sell",
                    order_type=order_type,
                    amount_base=amount,
                    price=price,
                    metadata={
                        "bridge_method": "sell",
                        "compat_adapter": "active",
                        "position_action": normalized_position_action.value,
                        "position_mode": position_mode,
                        "reduce_only": "1" if normalized_position_action == PositionAction.CLOSE_LONG else "0",
                    },
                )
                if publish_entry_id is None:
                    _upsert_runtime_order(
                        self,
                        connector_name=conn_name,
                        order_id=generated_order_id,
                        state="failed",
                        failure_reason="paper_exchange_command_publish_failed",
                    )
                    reject_event = OrderRejected(
                        event_id=f"pe-local-reject-{generated_order_id}",
                        timestamp_ns=int(time.time() * 1e9),
                        instrument_id=_iid,
                        order_id=generated_order_id,
                        reason="paper_exchange_command_publish_failed",
                        source_bot=conn_name,
                    )
                    _fire_hb_events(self, conn_name, reject_event, _bridge_state)
                    _trace_paper_order(
                        "stage=bridge_sell_publish_failed connector=%s pair=%s order_id=%s",
                        conn_name,
                        trading_pair,
                        generated_order_id,
                        force=True,
                    )
                else:
                    _trace_paper_order(
                        "stage=bridge_sell_published connector=%s pair=%s order_id=%s stream_entry_id=%s",
                        conn_name,
                        trading_pair,
                        generated_order_id,
                        str(publish_entry_id),
                        force=force_trace,
                    )
                return generated_order_id

            _price = price if price == price else _resolve_shadow_submit_price(
                self,
                _desk,
                _iid,
                conn_name,
                trading_pair,
                OrderSide.SELL,
            )
            normalized_position_action = _normalize_position_action(position_action, OrderSide.SELL)
            position_mode = str(getattr(getattr(_find_controller_for_connector(self, conn_name), "config", None), "position_mode", "ONEWAY") or "ONEWAY").upper()
            event = _desk.submit_order(
                _iid, OrderSide.SELL, _hb_order_type_to_v2(order_type),
                Decimal(str(_price)), Decimal(str(amount)),
                source_bot=conn_name,
                position_action=normalized_position_action,
                position_mode=position_mode,
            )
            if force_trace:
                logger.warning(
                    "PAPER_ROUTE_PROBE stage=bridge_sell_submit connector=%s pair=%s order_id=%s event=%s reason=%s",
                    conn_name,
                    trading_pair,
                    str(getattr(event, "order_id", "") or ""),
                    type(event).__name__,
                    str(getattr(event, "reason", "") or ""),
                )
            _publish_paper_exchange_command(
                self,
                connector_name=conn_name,
                trading_pair=trading_pair,
                command="submit_order",
                order_id=str(getattr(event, "order_id", "") or "") or None,
                side="sell",
                order_type=order_type,
                amount_base=amount,
                price=_price,
                metadata={
                    "bridge_method": "sell",
                    "compat_adapter": "shadow",
                    "position_action": normalized_position_action.value,
                    "position_mode": position_mode,
                    "reduce_only": "1" if normalized_position_action == PositionAction.CLOSE_LONG else "0",
                },
            )
            _trace_paper_order(
                "stage=bridge_sell_desk_submit connector=%s pair=%s order_id=%s event=%s reason=%s",
                conn_name,
                trading_pair,
                str(getattr(event, "order_id", "") or ""),
                type(event).__name__,
                str(getattr(event, "reason", "") or ""),
                force=force_trace or type(event).__name__ != "OrderAccepted",
            )
            _fire_hb_events(self, conn_name, event, _bridge_state)
            return getattr(event, "order_id", None)
        return original_sell(conn_name, trading_pair, amount, order_type, price, position_action=position_action, **kwargs)

    def _patched_cancel(self, conn_name, trading_pair, order_id, *args, **kwargs):
        bridge = getattr(self, "_paper_desk_v2_bridges", {}).get(conn_name)
        if bridge is not None:
            _desk: PaperDesk = bridge["desk"]
            _iid: InstrumentId = bridge["instrument_id"]
            mode = _paper_exchange_mode_for_route(self, conn_name, trading_pair)
            if mode == "active":
                sync_ready, sync_reason = _active_sync_gate(self, conn_name, trading_pair)
                if not sync_ready:
                    if order_id:
                        _upsert_runtime_order(
                            self,
                            connector_name=conn_name,
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
                            source_bot=conn_name,
                        )
                        _fire_hb_events(self, conn_name, reject_event, _bridge_state)
                    return

                cancel_command_event_id = _active_cancel_command_event_id(
                    self,
                    connector_name=conn_name,
                    trading_pair=trading_pair,
                    order_id=str(order_id or ""),
                )
                publish_entry_id = _publish_paper_exchange_command(
                    self,
                    connector_name=conn_name,
                    trading_pair=trading_pair,
                    command="cancel_order",
                    order_id=str(order_id) if order_id else None,
                    metadata={"bridge_method": "cancel", "compat_adapter": "active"},
                    command_event_id=cancel_command_event_id,
                )
                if publish_entry_id is None and order_id:
                    _upsert_runtime_order(
                        self,
                        connector_name=conn_name,
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
                        source_bot=conn_name,
                    )
                    _fire_hb_events(self, conn_name, reject_event, _bridge_state)
                elif order_id:
                    _upsert_runtime_order(
                        self,
                        connector_name=conn_name,
                        order_id=str(order_id),
                        state="pending_cancel",
                    )
                return

            event = _desk.cancel_order(_iid, order_id)
            _publish_paper_exchange_command(
                self,
                connector_name=conn_name,
                trading_pair=trading_pair,
                command="cancel_order",
                order_id=str(order_id) if order_id else None,
                metadata={"bridge_method": "cancel", "compat_adapter": "shadow"},
            )
            if event:
                _fire_hb_events(self, conn_name, event, _bridge_state)
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
        if not hasattr(connector, "_paper_desk_v2"):
            connector._paper_desk_v2 = desk
        if not hasattr(connector, "_paper_desk_v2_instrument_id"):
            connector._paper_desk_v2_instrument_id = iid

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
            return True

        def _paper_position_obj(position_action: Any = None):
            resolved_action = _normalize_position_action_hint(position_action)
            pos = desk.portfolio.get_position(iid, position_action=resolved_action)
            amount = pos.quantity
            entry_price = pos.avg_entry_price
            if resolved_action in {PositionAction.OPEN_LONG, PositionAction.CLOSE_LONG}:
                amount = pos.long_quantity
                entry_price = pos.long_avg_entry_price
            elif resolved_action in {PositionAction.OPEN_SHORT, PositionAction.CLOSE_SHORT}:
                amount = -pos.short_quantity
                entry_price = pos.short_avg_entry_price
            return SimpleNamespace(
                trading_pair=iid.trading_pair,
                amount=amount,
                entry_price=entry_price,
            )

        def _patched_get_position(self, trading_pair: Optional[str] = None, *args, **kwargs):
            try:
                if trading_pair and str(trading_pair) != str(iid.trading_pair):
                    orig = getattr(self, "_epp_v2_orig_get_position", None)
                    return orig(trading_pair, *args, **kwargs) if callable(orig) else None
                position_action = kwargs.get("position_action") or kwargs.get("position_side")
                return _paper_position_obj(position_action)
            except Exception:
                orig = getattr(self, "_epp_v2_orig_get_position", None)
                return orig(trading_pair, *args, **kwargs) if callable(orig) else None

        def _patched_account_positions(self, *args, **kwargs):
            try:
                net_pos = desk.portfolio.get_position(iid)
                return {
                    iid.trading_pair: {
                        "amount": net_pos.quantity,
                        "long_amount": net_pos.long_quantity,
                        "short_amount": -net_pos.short_quantity,
                    }
                }
            except Exception:
                orig = getattr(self, "_epp_v2_orig_account_positions", None)
                return orig(*args, **kwargs) if callable(orig) else {}

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
        _consume_signals(strategy)
    except Exception as exc:
        logger.warning("Signal consumption failed (non-critical): %s", exc)
    try:
        _check_hard_stop_transitions(strategy)
    except Exception as exc:
        logger.warning("Guard state check failed (non-critical): %s", exc)
    try:
        _run_adverse_inference(strategy)
    except Exception as exc:
        logger.warning("Adverse inference failed (non-critical): %s", exc)
    try:
        bridges: Dict = getattr(strategy, "_paper_desk_v2_bridges", {})
        for conn_name, bridge in bridges.items():
            bridge_iid = bridge.get("instrument_id")
            trading_pair = str(getattr(bridge_iid, "trading_pair", "") or "")
            if trading_pair:
                _ensure_sync_state_command(strategy, conn_name, trading_pair)

        _consume_paper_exchange_events(strategy)

        all_events = desk.tick(now_ns)
        if not all_events:
            return
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
    except Exception as exc:
        logger.error("drive_desk_tick failed: %s", exc, exc_info=True)
