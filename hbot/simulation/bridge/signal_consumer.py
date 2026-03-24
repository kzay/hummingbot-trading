"""Signal consumption and HARD_STOP detection for the HB bridge.

Extracted from hb_bridge.py (DEBT-3). Functions receive bridge state
as a parameter to avoid circular imports with hb_bridge.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from platform_lib.contracts.event_identity import validate_event_identity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream name constants
# ---------------------------------------------------------------------------

try:
    from platform_lib.contracts.stream_names import (
        EXECUTION_INTENT_STREAM as _EXECUTION_INTENT_STREAM,
    )
    from platform_lib.contracts.stream_names import (
        ML_FEATURES_STREAM as _ML_FEATURES_STREAM,
    )
    from platform_lib.contracts.stream_names import (
        SIGNAL_STREAM as _SIGNAL_STREAM,
    )
except Exception:
    _SIGNAL_STREAM = "hb.signal.v1"
    _EXECUTION_INTENT_STREAM = "hb.execution_intent.v1"
    _ML_FEATURES_STREAM = "hb.ml_features.v1"

SIGNAL_STREAM = _SIGNAL_STREAM
EXECUTION_INTENT_STREAM = _EXECUTION_INTENT_STREAM
ML_FEATURES_STREAM = _ML_FEATURES_STREAM


def _find_controller_by_instance(strategy: Any, instance_name: str) -> Any:
    """Find the controller whose config.instance_name matches."""
    controllers = getattr(strategy, "controllers", {})
    for _, ctrl in controllers.items():
        cfg = getattr(ctrl, "config", None)
        if cfg and str(getattr(cfg, "instance_name", "")) == instance_name:
            return ctrl
    return None


def _consume_signals(strategy: Any, bridge_state: Any) -> None:
    """Poll SIGNAL_STREAM for new signals and route to controllers.

    Non-blocking (block=0). Only processes ``inventory_rebalance`` signals.
    Redis unavailability is logged as a warning; the tick continues normally.
    """
    r = bridge_state.get_redis()
    if r is None:
        return
    try:
        result = r.xread({SIGNAL_STREAM: bridge_state.last_signal_id}, count=20, block=0)
    except Exception as exc:
        logger.warning("Signal xread failed (Redis may be down): %s", exc)
        return
    if not result:
        return
    import json as _json
    try:
        import orjson as _orjson_sc
    except ImportError:
        _orjson_sc = None  # type: ignore[assignment]
    for _stream_name, entries in result:
        for entry_id, data in entries:
            bridge_state.last_signal_id = entry_id
            try:
                raw = data.get("payload")
                if not isinstance(raw, str):
                    continue
                payload = _orjson_sc.loads(raw) if _orjson_sc else _json.loads(raw)
                signal_name = payload.get("signal_name", "")
                instance_name = payload.get("instance_name", "")
                if not instance_name:
                    continue
                ctrl = _find_controller_by_instance(strategy, instance_name)
                if ctrl is None:
                    continue

                if signal_name == "inventory_rebalance":
                    signal_value = payload.get("signal_value")
                    if signal_value is None:
                        continue
                    try:
                        _sv = float(signal_value)
                        import math as _math_sc
                        if _math_sc.isnan(_sv) or _math_sc.isinf(_sv):
                            logger.warning("Signal rejected: NaN/Inf signal_value=%s for %s", signal_value, instance_name)
                            continue
                    except (TypeError, ValueError):
                        logger.warning("Signal rejected: unparseable signal_value=%s for %s", signal_value, instance_name)
                        continue
                    if hasattr(ctrl, "apply_execution_intent"):
                        ok, msg = ctrl.apply_execution_intent({
                            "action": "set_target_base_pct",
                            "target_base_pct": signal_value,
                        })
                        if ok:
                            logger.info(
                                "Signal routed: inventory_rebalance -> %s (target_base_pct=%s)",
                                instance_name, signal_value,
                            )
                        else:
                            logger.warning("Signal rejected by controller %s: %s", instance_name, msg)

                elif signal_name == "regime_override":
                    metadata = payload.get("metadata", {})
                    if isinstance(metadata, str):
                        try:
                            metadata = _orjson_sc.loads(metadata) if _orjson_sc else _json.loads(metadata)
                        except Exception:
                            metadata = {}
                    regime = str(metadata.get("regime", "")).strip()
                    if not regime:
                        continue
                    if hasattr(ctrl, "apply_execution_intent"):
                        ok, msg = ctrl.apply_execution_intent({
                            "action": "set_regime_override",
                            "regime": regime,
                        })
                        if ok:
                            logger.debug("ML regime override routed: %s -> %s", instance_name, regime)
                        else:
                            logger.debug("ML regime override rejected by %s: %s", instance_name, msg)
            except Exception as exc:
                logger.warning("Signal processing error for entry %s: %s", entry_id, exc)


def _consume_ml_features(strategy: Any, bridge_state: Any) -> None:
    """Poll ML_FEATURES_STREAM for predictions and route to controllers.

    Non-blocking. Only processes events whose ``trading_pair`` matches a
    controller's configured pair and only when ``ml_features_enabled`` is
    set on the controller config.
    """
    r = bridge_state.get_redis()
    if r is None:
        return
    last_id = getattr(bridge_state, "last_ml_features_id", "$")
    try:
        result = r.xread({ML_FEATURES_STREAM: last_id}, count=20, block=0)
    except Exception as exc:
        logger.warning("ML features xread failed: %s", exc)
        return
    if not result:
        return
    import json as _json
    try:
        import orjson as _orjson_ml
    except ImportError:
        _orjson_ml = None  # type: ignore[assignment]
    for _stream_name, entries in result:
        for entry_id, data in entries:
            bridge_state.last_ml_features_id = entry_id
            try:
                raw = data.get("payload")
                if not isinstance(raw, str):
                    continue
                payload = _orjson_ml.loads(raw) if _orjson_ml else _json.loads(raw)
                if payload.get("event_type") != "ml_features":
                    continue
                trading_pair = payload.get("trading_pair", "")
                predictions = payload.get("predictions", {})
                model_versions = payload.get("model_versions", {})
                if not predictions:
                    continue

                controllers = getattr(strategy, "controllers", {})
                for _, ctrl in controllers.items():
                    cfg = getattr(ctrl, "config", None)
                    if cfg is None:
                        continue
                    if not getattr(cfg, "ml_features_enabled", False):
                        continue
                    ctrl_pair = str(getattr(cfg, "trading_pair", ""))
                    if ctrl_pair != trading_pair:
                        continue
                    if not hasattr(ctrl, "apply_execution_intent"):
                        continue

                    confidence_threshold = float(getattr(cfg, "ml_confidence_threshold", 0.5))

                    if "regime" in predictions and getattr(cfg, "ml_regime_override_enabled", False):
                        regime_pred = predictions["regime"]
                        confidence = float(regime_pred.get("confidence", 0))
                        if confidence >= confidence_threshold:
                            ctrl.apply_execution_intent({
                                "action": "set_ml_regime",
                                "regime": str(regime_pred.get("class", "")),
                                "confidence": confidence,
                                "metadata": {"model_version": model_versions.get("regime", "")},
                            })

                    if "direction" in predictions and getattr(cfg, "ml_direction_hint_enabled", False):
                        dir_pred = predictions["direction"]
                        confidence = float(dir_pred.get("confidence", 0))
                        if confidence >= confidence_threshold:
                            pred_class = int(dir_pred.get("class", 0))
                            direction = "long" if pred_class > 0 else ("short" if pred_class < 0 else "neutral")
                            ctrl.apply_execution_intent({
                                "action": "set_ml_direction_hint",
                                "direction": direction,
                                "confidence": confidence,
                            })

                    if "sizing" in predictions and getattr(cfg, "ml_sizing_hint_enabled", False):
                        sizing_pred = predictions["sizing"]
                        value = float(sizing_pred.get("value", 1.0))
                        ctrl.apply_execution_intent({
                            "action": "set_ml_sizing_hint",
                            "multiplier": max(0.1, min(value, 3.0)),
                            "confidence": float(sizing_pred.get("confidence", 0)),
                        })

            except Exception as exc:
                logger.warning("ML feature processing error for entry %s: %s", entry_id, exc)


def _check_hard_stop_transitions(strategy: Any, bridge_state: Any) -> None:
    """Detect first HARD_STOP transition per controller and publish kill_switch intent.

    Only fires once per transition (not on every HARD_STOP tick).
    Redis unavailability is logged; the tick continues normally.
    """
    controllers = getattr(strategy, "controllers", {})
    if not controllers:
        return
    r = bridge_state.get_redis()
    if r is None:
        return
    import json as _json
    try:
        import orjson as _orjson_sc
    except ImportError:
        _orjson_sc = None  # type: ignore[assignment]
    for ctrl_key, ctrl in controllers.items():
        try:
            ops_guard = getattr(ctrl, "_ops_guard", None)
            if ops_guard is None:
                continue
            raw_state = getattr(ops_guard, "state", None)
            if raw_state is None:
                continue
            new_state = raw_state.value if hasattr(raw_state, "value") else str(raw_state)
            prev_state = bridge_state.prev_guard_states.get(ctrl_key)
            bridge_state.prev_guard_states[ctrl_key] = new_state

            if new_state == "hard_stop" and prev_state != "hard_stop":
                cfg = getattr(ctrl, "config", None)
                instance_name = str(getattr(cfg, "instance_name", "") or ctrl_key)
                controller_id = str(
                    getattr(ctrl, "id", "")
                    or getattr(ctrl, "controller_id", "")
                    or ctrl_key
                )
                try:
                    from platform_lib.contracts.event_schemas import ExecutionIntentEvent
                    kill_ttl_ms = 300_000
                    intent = ExecutionIntentEvent(
                        producer="hb_bridge",
                        instance_name=instance_name,
                        controller_id=controller_id,
                        action="kill_switch",
                        expires_at_ms=int(time.time() * 1000) + kill_ttl_ms,
                        metadata={
                            "reason": "hard_stop_transition",
                            "details": "controller entered HARD_STOP",
                        },
                    )
                    payload = intent.model_dump()
                except Exception:
                    import uuid as _uuid_mod
                    payload = {
                        "event_type": "execution_intent",
                        "event_id": str(_uuid_mod.uuid4()),
                        "producer": "hb_bridge",
                        "instance_name": instance_name,
                        "controller_id": controller_id,
                        "action": "kill_switch",
                        "expires_at_ms": int(time.time() * 1000) + 300_000,
                        "metadata": {
                            "reason": "hard_stop_transition",
                            "details": "controller entered HARD_STOP",
                        },
                    }
                try:
                    identity_ok, identity_reason = validate_event_identity(payload)
                    if not identity_ok:
                        logger.warning(
                            "HARD_STOP intent dropped by identity preflight instance=%s reason=%s",
                            instance_name,
                            identity_reason,
                        )
                        continue
                    r.xadd(
                        EXECUTION_INTENT_STREAM,
                        {"payload": _orjson_sc.dumps(payload, default=str).decode() if _orjson_sc else _json.dumps(payload, default=str)},
                        maxlen=50_000,
                        approximate=True,
                    )
                    logger.warning(
                        "HARD_STOP transition detected for %s — kill_switch intent published",
                        instance_name,
                    )
                except Exception as exc:
                    logger.error("Failed to publish kill_switch intent: %s", exc)
        except Exception as exc:
            logger.warning("Guard state check failed for %s: %s", ctrl_key, exc)
