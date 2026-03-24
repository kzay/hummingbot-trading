"""Paper Exchange Service Redis protocol layer.

Extracted from hb_bridge.py — contains functions that implement the Redis-backed
command/event protocol between the HB bridge and the external Paper Exchange
service.  Includes:
  - Stream cursor management
  - Active-mode dedup caches (submit, cancel, cancel-all)
  - Runtime order tracking (upsert / prune / hydrate)
  - Command publishing to the ``paper_exchange_command`` Redis stream
  - Sync-state handshake helpers
  - Fill→portfolio settlement
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None  # type: ignore[assignment]

from simulation.bridge.bridge_state import (
    _bridge_state,
    _get_signal_redis,
    _LATENCY_TRACKER,
)
from simulation.bridge.bridge_utils import _canonical_name, _fmt_contract_decimal
from simulation.types import (
    _ZERO,
    InstrumentId,
    OrderSide,
    PositionAction,
)
from services.execution_gateway.gateway import build_paper_execution_command

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stream cursor management
# ---------------------------------------------------------------------------


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

    latest_id: str | None = None
    try:
        latest_entries = redis_client.xrevrange(stream_name, count=1)
        if (
            isinstance(latest_entries, list)
            and len(latest_entries) > 0
            and isinstance(latest_entries[0], (list, tuple))
            and len(latest_entries[0]) >= 1
        ):
            latest_id = str(latest_entries[0][0])
    except (OSError, ConnectionError, TypeError, IndexError):
        latest_id = None

    if latest_id:
        _bridge_state.last_paper_exchange_event_id = latest_id
        try:
            redis_client.set(cursor_key, latest_id)
        except (OSError, ConnectionError):
            pass


# ---------------------------------------------------------------------------
# Sync handshake
# ---------------------------------------------------------------------------


def _sync_handshake_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return f"{str(instance_name or '').strip()}|{_canonical_name(str(connector_name or ''))}|{str(trading_pair or '').strip().upper()}"


# ---------------------------------------------------------------------------
# Active-mode submit dedup
# ---------------------------------------------------------------------------


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
    order_type: Any | None,
    amount: Any | None,
    price: Any | None,
) -> str:
    def _fmt_decimal(value: Any | None) -> str:
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
    order_type: Any | None,
    amount: Any | None,
    price: Any | None,
) -> str:
    import uuid as _uuid_mod

    from simulation.bridge.compat_helpers import _resolve_controller_for_command

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


# ---------------------------------------------------------------------------
# Active-mode cancel dedup
# ---------------------------------------------------------------------------


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
) -> str | None:
    import uuid as _uuid_mod

    from simulation.bridge.compat_helpers import _resolve_controller_for_command

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


# ---------------------------------------------------------------------------
# Active-mode cancel-all dedup
# ---------------------------------------------------------------------------


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
    metadata: dict[str, str] | None = None,
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
    metadata: dict[str, str] | None = None,
) -> str:
    import uuid as _uuid_mod

    from simulation.bridge.compat_helpers import _resolve_controller_for_command

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


# ---------------------------------------------------------------------------
# Runtime order tracking
# ---------------------------------------------------------------------------


def _runtime_orders_store(strategy: Any) -> dict[str, dict[str, Any]]:
    store = getattr(strategy, "_paper_exchange_runtime_orders", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        strategy._paper_exchange_runtime_orders = store
    except (AttributeError, TypeError):
        pass
    return store


def _runtime_orders_bucket(strategy: Any, connector_name: str) -> dict[str, Any]:
    store = _runtime_orders_store(strategy)
    key = str(connector_name or "")
    bucket = store.get(key)
    if isinstance(bucket, dict):
        return bucket
    bucket = {}
    store[key] = bucket
    return bucket


def _runtime_order_trade_type(side: str | None) -> str:
    side_norm = str(side or "").strip().lower()
    return "BUY" if side_norm == "buy" else "SELL"


def _canonical_runtime_order_state(state: str) -> str:
    normalized = str(state or "").strip().lower()
    if normalized == "open":
        return "working"
    if normalized in {"partial", "partially-filled"}:
        return "partially_filled"
    if normalized == "cancelled":
        return "canceled"
    return normalized


def _runtime_order_state_flags(state: str) -> tuple[bool, bool]:
    normalized = _canonical_runtime_order_state(state)
    if normalized in {"filled", "canceled", "cancelled", "failed", "rejected", "expired"}:
        return True, False
    if normalized in {"working", "pending_create", "pending_cancel", "partially_filled"}:
        return False, True
    return False, False


def _upsert_runtime_order(
    strategy: Any,
    *,
    connector_name: str,
    order_id: str,
    trading_pair: str | None = None,
    side: str | None = None,
    order_type: Any | None = None,
    amount: Any | None = None,
    price: Any | None = None,
    state: str | None = None,
    failure_reason: str = "",
) -> Any | None:
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
        state_text = _canonical_runtime_order_state(state)
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


# ---------------------------------------------------------------------------
# State snapshot helpers
# ---------------------------------------------------------------------------


def _paper_exchange_state_snapshot_path() -> str:
    configured = str(os.getenv("PAPER_EXCHANGE_STATE_SNAPSHOT_PATH", "") or "").strip()
    candidates = [
        configured,
        "/home/hummingbot/reports/verification/paper_exchange_state_snapshot_latest.json",
        "/workspace/hbot/reports/verification/paper_exchange_state_snapshot_latest.json",
        "reports/verification/paper_exchange_state_snapshot_latest.json",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if Path(candidate).exists():
                return candidate
        except (OSError, ValueError):
            continue
    return configured or "reports/verification/paper_exchange_state_snapshot_latest.json"


def _active_command_ttl_ms(command: str) -> int:
    command_name = str(command or "").strip().lower()
    base_ttl_ms = max(1_000, int(float(os.getenv("PAPER_EXCHANGE_COMMAND_TTL_MS", "30000"))))
    if command_name == "sync_state":
        sync_timeout_ms = max(1_000, int(float(os.getenv("PAPER_EXCHANGE_SYNC_TIMEOUT_MS", "30000"))))
        return max(
            base_ttl_ms,
            max(300_000, sync_timeout_ms * 4),
        )
    if command_name in {"submit_order", "cancel_order", "cancel_all"}:
        active_ttl_ms = max(
            1_000,
            int(float(os.getenv("PAPER_EXCHANGE_ACTIVE_COMMAND_TTL_MS", "120000"))),
        )
        return max(base_ttl_ms, active_ttl_ms)
    return base_ttl_ms


def _hydrate_runtime_orders_from_state_snapshot(
    strategy: Any,
    *,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
) -> list[str]:
    snapshot_path = _paper_exchange_state_snapshot_path()
    try:
        with open(snapshot_path, encoding="utf-8") as snapshot_file:
            payload = json.load(snapshot_file)
    except Exception as exc:
        logger.warning(
            "paper_exchange state snapshot hydration failed (instance=%s connector=%s pair=%s path=%s error=%s)",
            instance_name,
            connector_name,
            trading_pair,
            snapshot_path,
            exc,
        )
        return []

    orders = payload.get("orders", {})
    if not isinstance(orders, dict):
        return []

    hydrated_order_ids: list[str] = []
    target_instance = str(instance_name or "").strip().lower()
    target_pair = str(trading_pair or "").strip().upper()
    target_connector = _canonical_name(str(connector_name or ""))
    for record in orders.values():
        if not isinstance(record, dict):
            continue
        order_id = str(record.get("order_id", "") or "").strip()
        if not order_id:
            continue
        record_instance = str(record.get("instance_name", "") or "").strip().lower()
        record_connector = _canonical_name(str(record.get("connector_name", "") or ""))
        record_pair = str(record.get("trading_pair", "") or "").strip().upper()
        record_state = str(record.get("state", "working") or "").strip().lower()
        if record_instance != target_instance or record_connector != target_connector or record_pair != target_pair:
            continue
        if record_state in {"filled", "canceled", "cancelled", "failed", "rejected", "expired"}:
            continue
        _upsert_runtime_order(
            strategy,
            connector_name=connector_name,
            order_id=order_id,
            trading_pair=record_pair,
            side=str(record.get("side", "") or "").lower() or None,
            order_type=str(record.get("order_type", "") or "").lower() or None,
            amount=record.get("amount_base"),
            price=record.get("price"),
            state="partially_filled" if record_state in {"partially_filled", "partial"} else "working",
        )
        hydrated_order_ids.append(order_id)
    return hydrated_order_ids


# ---------------------------------------------------------------------------
# Controller order tracking
# ---------------------------------------------------------------------------


def _controller_tracked_order_ids(controller: Any | None) -> set[str] | None:
    if controller is None:
        return None
    executors = getattr(controller, "executors_info", None)
    if not isinstance(executors, list):
        return None
    tracked_ids: set[str] = set()
    for executor in executors:
        order_id = getattr(executor, "order_id", None) or getattr(executor, "id", None)
        if order_id:
            tracked_ids.add(str(order_id))
    return tracked_ids


def _cancel_reconciled_ghost_orders(
    strategy: Any,
    *,
    controller: Any | None,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    order_ids: list[str],
) -> int:
    tracked_ids = _controller_tracked_order_ids(controller)
    if tracked_ids is None:
        return 0

    canceled = 0
    for order_id in order_ids:
        if order_id in tracked_ids:
            continue
        publish_entry_id = _publish_paper_exchange_command(
            strategy,
            connector_name=connector_name,
            trading_pair=trading_pair,
            command="cancel_order",
            order_id=order_id,
            metadata={
                "bridge_method": "startup_reconcile_cancel",
                "compat_adapter": "active",
                "reconcile_reason": "ghost_order",
                "instance_name": instance_name,
            },
        )
        if publish_entry_id is None:
            continue
        _upsert_runtime_order(
            strategy,
            connector_name=connector_name,
            order_id=order_id,
            trading_pair=trading_pair,
            state="pending_cancel",
        )
        canceled += 1
    return canceled


def _get_runtime_order_for_executor(strategy: Any, connector_name: str, order_id: str) -> Any | None:
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


# ---------------------------------------------------------------------------
# Accounting contract metadata
# ---------------------------------------------------------------------------


def _controller_accounting_contract_metadata(controller: Any | None) -> dict[str, str]:
    if controller is None:
        return {}

    out: dict[str, str] = {}
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


# ---------------------------------------------------------------------------
# Command publishing
# ---------------------------------------------------------------------------


def _publish_paper_exchange_command(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    command: str,
    order_id: str | None = None,
    side: str | None = None,
    order_type: Any | None = None,
    amount_base: Any | None = None,
    price: Any | None = None,
    metadata: dict[str, str] | None = None,
    command_event_id: str | None = None,
    ttl_ms_override: int | None = None,
) -> str | None:
    import json as _json
    import uuid as _uuid_mod

    from simulation.bridge.compat_helpers import (
        _apply_active_failure_policy,
        _paper_exchange_mode_for_instance,
        _resolve_controller_for_command,
    )

    started = time.perf_counter()
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
        from platform_lib.contracts.event_identity import validate_event_identity as _validate_event_identity
        from platform_lib.contracts.stream_names import PAPER_EXCHANGE_COMMAND_STREAM, STREAM_RETENTION_MAXLEN

        order_type_raw = getattr(order_type, "name", order_type)
        order_type_value = str(order_type_raw).strip().lower() if order_type_raw is not None else None
        amount_value = float(amount_base) if amount_base is not None else None  # float: serialization-only
        price_value: float | None = None
        if price is not None:
            try:
                # Decimal("NaN") check
                if price == price:
                    price_value = float(price)  # float: serialization-only
            except Exception:
                price_value = None

        ttl_ms = _active_command_ttl_ms(command)
        if ttl_ms_override is not None:
            ttl_ms = max(ttl_ms, int(ttl_ms_override))
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
        event_payload = event.model_dump()
        identity_ok, identity_reason = _validate_event_identity(event_payload)
        if not identity_ok:
            if mode == "active":
                _apply_active_failure_policy(
                    strategy,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    failure_class="service_down",
                    reason=f"command_identity_invalid:{identity_reason}",
                )
            logger.warning(
                "paper_exchange command dropped due to identity contract: %s (command=%s connector=%s pair=%s)",
                identity_reason,
                str(command),
                str(connector_name),
                str(trading_pair),
            )
            return None
        entry_id = r.xadd(
            PAPER_EXCHANGE_COMMAND_STREAM,
            {"payload": _orjson.dumps(event_payload, default=str).decode() if _orjson else _json.dumps(event_payload, default=str)},
            maxlen=STREAM_RETENTION_MAXLEN.get(PAPER_EXCHANGE_COMMAND_STREAM, 100_000),
            approximate=True,
        )
        _LATENCY_TRACKER.observe("hb_bridge_command_publish_ms", (time.perf_counter() - started) * 1000.0)
        _LATENCY_TRACKER.flush(
            extra={
                "mode": mode,
                "command": str(command or ""),
                "service_redis_available": True,
            }
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
        _LATENCY_TRACKER.observe("hb_bridge_command_publish_ms", (time.perf_counter() - started) * 1000.0)
        _LATENCY_TRACKER.flush(
            extra={
                "mode": mode,
                "command": str(command or ""),
                "service_redis_available": r is not None,
                "last_error": type(exc).__name__,
            }
        )
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


# ---------------------------------------------------------------------------
# Sync-state helpers
# ---------------------------------------------------------------------------


def _ensure_sync_state_command(strategy: Any, connector_name: str, trading_pair: str) -> None:
    from simulation.bridge.compat_helpers import (
        _paper_exchange_mode_for_instance,
        _resolve_controller_for_command,
    )

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
        ttl_ms_override=_active_command_ttl_ms("sync_state"),
    )
    if entry_id:
        _bridge_state.sync_state_published_keys.add(sync_key)
        _bridge_state.sync_requested_at_ms_by_key[sync_key] = int(time.time() * 1000)


def _sync_fill_to_portfolio(
    strategy: Any,
    instrument_id: InstrumentId,
    side_str: str,
    fill_price: Decimal,
    fill_qty: Decimal,
    fill_fee: Decimal,
    position_action_str: str,
    position_mode_str: str,
    now_ns: int,
) -> None:
    """Settle an external Paper Exchange fill into PaperDesk v2's portfolio.

    When PAPER_EXCHANGE_MODE=active, fills happen externally.  The portfolio
    must still reflect fees and realized PnL so that ``equity_quote`` (and
    therefore drawdown / daily-loss risk metrics) stay accurate.
    """
    from simulation.desk import PaperDesk

    desk: PaperDesk | None = getattr(strategy, "_paper_desk_v2", None)
    if desk is None:
        return
    portfolio = desk.portfolio
    if portfolio is None:
        return
    spec = desk._specs.get(instrument_id.key)
    if spec is None:
        return
    side = OrderSide.BUY if side_str in {"buy", "BUY"} else OrderSide.SELL
    try:
        pa = PositionAction(position_action_str) if position_action_str else PositionAction.AUTO
    except (ValueError, KeyError):
        pa = PositionAction.AUTO
    pm = position_mode_str.upper() if position_mode_str else "ONEWAY"
    leverage = desk.portfolio._leverage_by_key.get(instrument_id.key, 1)
    try:
        portfolio.settle_fill(
            instrument_id=instrument_id,
            side=side,
            quantity=fill_qty,
            price=fill_price,
            fee=fill_fee,
            source_bot="paper_exchange",
            now_ns=now_ns,
            spec=spec,
            leverage=leverage,
            position_action=pa,
            position_mode=pm,
        )
    except Exception as exc:
        logger.debug("_sync_fill_to_portfolio failed (non-critical): %s", exc)
