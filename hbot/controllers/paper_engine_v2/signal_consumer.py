"""Signal consumption and HARD_STOP detection for the HB bridge.

Extracted from hb_bridge.py (DEBT-3). Functions receive bridge state
as a parameter to avoid circular imports with hb_bridge.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream name constants
# ---------------------------------------------------------------------------

try:
    from services.contracts.stream_names import (
        SIGNAL_STREAM as _SIGNAL_STREAM,
        EXECUTION_INTENT_STREAM as _EXECUTION_INTENT_STREAM,
    )
except Exception:
    _SIGNAL_STREAM = "hb.signal.v1"
    _EXECUTION_INTENT_STREAM = "hb.execution_intent.v1"

SIGNAL_STREAM = _SIGNAL_STREAM
EXECUTION_INTENT_STREAM = _EXECUTION_INTENT_STREAM


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
    for _stream_name, entries in result:
        for entry_id, data in entries:
            bridge_state.last_signal_id = entry_id
            try:
                raw = data.get("payload")
                if not isinstance(raw, str):
                    continue
                payload = _json.loads(raw)
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
                            import json as _j
                            metadata = _j.loads(metadata)
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
                    from services.contracts.event_schemas import ExecutionIntentEvent
                    intent = ExecutionIntentEvent(
                        producer="hb_bridge",
                        instance_name=instance_name,
                        controller_id=controller_id,
                        action="kill_switch",
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
                        "metadata": {
                            "reason": "hard_stop_transition",
                            "details": "controller entered HARD_STOP",
                        },
                    }
                try:
                    r.xadd(
                        EXECUTION_INTENT_STREAM,
                        {"payload": _json.dumps(payload, default=str)},
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
