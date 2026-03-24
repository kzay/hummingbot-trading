"""Paper exchange mode detection, HB framework compatibility, and failure policy.

Contains:
- Mode normalization / detection / resolution
- Paper-exchange constraint metadata extraction
- Controller routing & bridge resolution helpers
- Active-mode failure policy (soft-pause, hard-stop escalation)
- HB framework compatibility patches (MarketDataProvider, ExecutorBase)
"""
from __future__ import annotations

import json as _json_mod
import logging
import os
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from simulation.bridge.bridge_state import (
    _bridge_state,
    _get_signal_redis,
)
from simulation.bridge.bridge_utils import (
    _canonical_name,
    _instance_env_suffix,
    _parse_env_bool,
)
from simulation.bridge.hb_event_fire import _find_controller_for_connector
from simulation.types import OrderRejected, OrderSide, PositionAction

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constraint metadata
# ---------------------------------------------------------------------------

def _paper_command_constraints_metadata(strategy: Any, connector_name: str, trading_pair: str) -> dict[str, str]:
    def _decimal_text(value: Any) -> str:
        try:
            text = str(value)
        except Exception:
            return ""
        return text if text not in {"", "None"} else ""

    rule = None
    try:
        get_trading_rules = getattr(strategy, "get_trading_rules", None)
        if callable(get_trading_rules):
            rules = get_trading_rules(connector_name)
            if isinstance(rules, dict):
                rule = rules.get(trading_pair)
    except Exception:
        rule = None
    if rule is None:
        try:
            connectors = getattr(strategy, "connectors", {})
            connector = connectors.get(connector_name) if isinstance(connectors, dict) else None
            rules = getattr(connector, "trading_rules", {}) if connector is not None else {}
            if isinstance(rules, dict):
                rule = rules.get(trading_pair)
        except Exception:
            rule = None
    if rule is None:
        return {}

    metadata: dict[str, str] = {}
    for key, attrs in (
        ("min_quantity", ("min_order_size", "min_base_amount", "min_amount")),
        ("size_increment", ("min_base_amount_increment", "min_order_size_increment", "amount_step")),
        ("price_increment", ("min_price_increment", "min_price_tick_size", "price_step", "min_price_step")),
        ("min_notional", ("min_notional_size", "min_notional", "min_order_value")),
    ):
        for attr in attrs:
            text = _decimal_text(getattr(rule, attr, None))
            if text and text not in {"0", "0.0", "0E-8"}:
                metadata[key] = text
                break
    return metadata


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

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


def _paper_exchange_service_only_for_instance(instance_name: str) -> bool:
    global_value = _parse_env_bool(os.getenv("PAPER_EXCHANGE_SERVICE_ONLY", "false"), default=False)
    suffix = _instance_env_suffix(instance_name)
    override_key = f"PAPER_EXCHANGE_SERVICE_ONLY_{suffix}" if suffix else ""
    if override_key and override_key in os.environ:
        return _parse_env_bool(os.getenv(override_key, ""), default=global_value)
    return global_value


def _paper_exchange_service_heartbeat_is_fresh(redis_client: Any) -> bool:
    stream_name = str(
        os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1")
    ).strip() or "hb.paper_exchange.heartbeat.v1"
    max_age_ms = max(
        1_000,
        int(float(os.getenv("PAPER_EXCHANGE_AUTO_MAX_HEARTBEAT_AGE_MS", "15000"))),
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
    cache_ms = max(0, int(float(os.getenv("PAPER_EXCHANGE_AUTO_CACHE_MS", "5000"))))
    instance_key = f"{instance_name or 'default'!s}|strict:{1 if strict_service_only else 0}"
    now_ms = int(time.time() * 1000)
    last_updated_ms = int(
        _bridge_state.paper_exchange_auto_mode_updated_ms_by_instance.get(instance_key, 0) or 0
    )
    cached_mode = str(_bridge_state.paper_exchange_auto_mode_by_instance.get(instance_key, "") or "")
    if cached_mode and cache_ms > 0 and (now_ms - last_updated_ms) <= cache_ms:
        return cached_mode

    fallback_mode = _normalize_paper_exchange_mode(
        os.getenv("PAPER_EXCHANGE_AUTO_FALLBACK", "shadow"),
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


def _paper_exchange_mode_for_instance(instance_name: str) -> str:
    strict_service_only = _paper_exchange_service_only_for_instance(instance_name)
    default_mode = _normalize_paper_exchange_mode(
        os.getenv("PAPER_EXCHANGE_MODE", "disabled"),
        default="disabled",
        allow_auto=True,
    )
    suffix = _instance_env_suffix(instance_name)
    override_key = f"PAPER_EXCHANGE_MODE_{suffix}" if suffix else ""
    override_mode = (
        _normalize_paper_exchange_mode(
            os.getenv(override_key, ""),
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


# ---------------------------------------------------------------------------
# Controller routing / resolution
# ---------------------------------------------------------------------------

def _resolve_controller_for_command(
    strategy: Any,
    connector_name: str,
    trading_pair: str,
) -> tuple[Any | None, str, str]:
    controllers = getattr(strategy, "controllers", {})
    matches: list[tuple[str, Any, str]] = []
    target_connector = _canonical_name(str(connector_name or ""))
    if isinstance(controllers, dict):
        for controller_id, ctrl in controllers.items():
            cfg = getattr(ctrl, "config", None)
            if cfg is None:
                continue
            cfg_connector = str(getattr(cfg, "connector_name", "") or "")
            cfg_pair = str(getattr(cfg, "trading_pair", "") or "")
            if _canonical_name(cfg_connector) == target_connector and (not trading_pair or cfg_pair == str(trading_pair)):
                instance_name = str(getattr(cfg, "instance_name", "") or controller_id)
                matches.append((str(controller_id), ctrl, instance_name))
    if len(matches) == 1:
        controller_id, ctrl, instance_name = matches[0]
        return ctrl, controller_id, instance_name
    if len(matches) > 1:
        logger.warning(
            "Ambiguous controller command route for connector=%s pair=%s; dropping command/event mapping",
            str(connector_name),
            str(trading_pair),
        )
        return None, "", ""
    ctrl = _find_controller_for_connector(
        strategy,
        connector_name,
        trading_pair=str(trading_pair or ""),
    )
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
) -> tuple[str | None, dict[str, object] | None]:
    bridges = getattr(strategy, "_paper_desk_v2_bridges", {})
    if not isinstance(bridges, dict):
        return None, None

    bridge = bridges.get(connector_name)
    if isinstance(bridge, dict):
        iid = bridge.get("instrument_id")
        iid_pair = str(getattr(iid, "trading_pair", "") or "")
        if not trading_pair or iid_pair == trading_pair:
            return connector_name, bridge

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


# ---------------------------------------------------------------------------
# Re-exported from paper_exchange_protocol (canonical location)
# ---------------------------------------------------------------------------

from simulation.bridge.paper_exchange_protocol import (  # noqa: F401
    _get_runtime_order_for_executor,
    _runtime_orders_bucket,
    _runtime_orders_store,
)


# ---------------------------------------------------------------------------
# Active-mode failure policy
# ---------------------------------------------------------------------------

def _active_failure_hard_stop_streak() -> int:
    try:
        parsed = int(float(os.getenv("PAPER_EXCHANGE_FAILURE_HARD_STOP_STREAK", "3")))
    except Exception:
        parsed = 3
    return max(2, parsed)


def _apply_controller_soft_pause(controller: Any | None, reason: str) -> None:
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


def _apply_controller_resume(controller: Any | None, reason: str) -> None:
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


def _force_sync_hard_stop(
    strategy: Any,
    *,
    controller: Any | None,
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
        from platform_lib.contracts.event_identity import validate_event_identity as _validate_event_identity
        from platform_lib.contracts.event_schemas import AuditEvent
        from platform_lib.contracts.stream_names import AUDIT_STREAM, STREAM_RETENTION_MAXLEN

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
            audit_payload = audit.model_dump()
            identity_ok, identity_reason = _validate_event_identity(audit_payload)
            if not identity_ok:
                logger.warning(
                    "paper_exchange sync hard-stop audit dropped by identity preflight reason=%s",
                    identity_reason,
                )
                return
            r.xadd(
                AUDIT_STREAM,
                {"payload": _orjson.dumps(audit_payload, default=str).decode() if _orjson else _json_mod.dumps(audit_payload, default=str)},
                maxlen=STREAM_RETENTION_MAXLEN.get(AUDIT_STREAM, 100_000),
                approximate=True,
            )
    except Exception:
        logger.debug("paper_exchange sync hard-stop audit publish failed", exc_info=True)


def _apply_active_failure_policy(
    strategy: Any,
    *,
    connector_name: str,
    trading_pair: str,
    failure_class: str,
    reason: str,
) -> str:
    from simulation.bridge.paper_exchange_protocol import _sync_handshake_key

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
    from simulation.bridge.paper_exchange_protocol import _sync_handshake_key

    controller, _controller_id, instance_name = _resolve_controller_for_command(strategy, connector_name, trading_pair)
    sync_key = _sync_handshake_key(instance_name, connector_name, trading_pair)
    previous_streak = int(_bridge_state.active_failure_streak_by_key.pop(sync_key, 0))
    if previous_streak > 0:
        _apply_controller_resume(controller, f"paper_exchange_recovered:streak={previous_streak}")


def _active_sync_gate(strategy: Any, connector_name: str, trading_pair: str) -> tuple[bool, str]:
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

    from simulation.bridge.paper_exchange_protocol import _sync_handshake_key, _ensure_sync_state_command

    sync_key = _sync_handshake_key(instance_name, connector_name, trading_pair)
    if sync_key in _bridge_state.sync_confirmed_keys:
        return True, "sync_confirmed"

    _ensure_sync_state_command(strategy, connector_name, trading_pair)

    now_ms = int(time.time() * 1000)
    requested_at_ms = _bridge_state.sync_requested_at_ms_by_key.get(sync_key, now_ms)
    timeout_ms = max(1_000, int(float(os.getenv("PAPER_EXCHANGE_SYNC_TIMEOUT_MS", "30000"))))
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


# ---------------------------------------------------------------------------
# HB framework compatibility patches
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
        from hummingbot.data_feed.market_data_provider import MarketDataProvider as _MDP  # type: ignore[import-untyped]
    except Exception:
        return  # MDP not available in this runtime — skip patch
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
        from hummingbot.strategy_v2.executors.executor_base import ExecutorBase as _EB  # type: ignore[import-untyped]
    except Exception:
        return  # ExecutorBase not available in this runtime — skip patch

    if not getattr(_EB, "_epp_v2_trading_rules_fallback_enabled", False):
        def _extract_rule(obj, pair):
            if obj is None:
                return None
            try:
                for attr in ("trading_rules", "_trading_rules"):
                    rules = getattr(obj, attr, None)
                    if isinstance(rules, dict) and pair in rules:
                        return rules[pair]
            except (AttributeError, TypeError):
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
            except (AttributeError, TypeError, KeyError):
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
