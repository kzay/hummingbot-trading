from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from services.common.models import RedisSettings, ServiceSettings
from services.contracts.event_schemas import ExecutionIntentEvent, RiskDecisionEvent
from services.contracts.stream_names import (
    DEFAULT_CONSUMER_GROUP,
    EXECUTION_INTENT_STREAM,
    RISK_DECISION_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_health(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_policy(path: Path) -> Dict[str, object]:
    policy = _read_json(path)
    if not policy:
        return {
            "enabled_default": False,
            "require_ml_enabled": True,
            "allowed_instances": ["bot1"],
            "target_base_pct": {"neutral": 0.5, "confidence_step": 0.2, "min": 0.25, "max": 0.75},
            "actions": {
                "approved_no_model_version": "resume",
                "approved_with_model_version": "set_target_base_pct",
                "rejected": "soft_pause",
            },
            "conflict_contract": {"intent_ttl_ms": 60_000},
        }
    return policy


def run() -> None:
    redis_cfg = RedisSettings()
    svc_cfg = ServiceSettings()
    client = RedisStreamClient(
        host=redis_cfg.host,
        port=redis_cfg.port,
        db=redis_cfg.db,
        password=redis_cfg.password or None,
        enabled=redis_cfg.enabled,
    )
    group = svc_cfg.consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = f"coord-{svc_cfg.instance_name}"
    client.create_group(RISK_DECISION_STREAM, group)
    policy_path = Path(
        os.getenv(
            "COORD_POLICY_PATH",
            "/workspace/hbot/config/coordination_policy_v1.json" if Path("/.dockerenv").exists() else "config/coordination_policy_v1.json",
        )
    )
    health_path = Path(
        os.getenv(
            "COORD_HEALTH_PATH",
            "/workspace/hbot/reports/coordination/latest.json"
            if Path("/.dockerenv").exists()
            else "reports/coordination/latest.json",
        )
    )
    health_write_sec = max(2, int(os.getenv("COORD_HEALTH_WRITE_SEC", "5")))
    last_health_write = 0.0
    intents_emitted = 0
    decisions_seen = 0

    from services.common.utils import CachedJsonFile
    _default_policy = {
        "enabled_default": False,
        "require_ml_enabled": True,
        "allowed_instances": ["bot1"],
        "target_base_pct": {"neutral": 0.5, "confidence_step": 0.2, "min": 0.25, "max": 0.75},
        "actions": {
            "approved_no_model_version": "resume",
            "approved_with_model_version": "set_target_base_pct",
            "rejected": "soft_pause",
        },
        "conflict_contract": {"intent_ttl_ms": 60_000},
    }
    policy_cache = CachedJsonFile(policy_path, default=_default_policy)

    while True:
        policy = policy_cache.get()
        if not policy:
            policy = dict(_default_policy)
        enabled_default = bool(policy.get("enabled_default", False))
        coord_enabled = _env_bool("COORD_ENABLED", enabled_default)
        require_ml_enabled = _env_bool("COORD_REQUIRE_ML_ENABLED", bool(policy.get("require_ml_enabled", True)))
        ml_enabled = _env_bool("ML_ENABLED", False)
        allowed_instances = policy.get("allowed_instances", [])
        allowed = {str(x) for x in allowed_instances} if isinstance(allowed_instances, list) else set()

        if not coord_enabled:
            state = "suspended_disabled"
        elif require_ml_enabled and not ml_enabled:
            state = "suspended_ml_disabled"
        elif allowed and svc_cfg.instance_name not in allowed:
            state = "suspended_scope"
        else:
            state = "active"

        now = time.time()
        if now - last_health_write >= health_write_sec:
            _write_health(
                health_path,
                {
                    "ts_utc": _utc_now(),
                    "status": "ok",
                    "state": state,
                    "instance_name": svc_cfg.instance_name,
                    "coord_enabled": coord_enabled,
                    "require_ml_enabled": require_ml_enabled,
                    "ml_enabled": ml_enabled,
                    "decisions_seen": decisions_seen,
                    "intents_emitted": intents_emitted,
                    "policy_path": str(policy_path),
                    "allowed_instances": sorted(allowed),
                },
            )
            last_health_write = now

        if state != "active":
            time.sleep(0.2)
            continue

        entries = client.read_group(
            stream=RISK_DECISION_STREAM,
            group=group,
            consumer=consumer,
            count=20,
            block_ms=svc_cfg.poll_ms,
        )
        for entry_id, payload in entries:
            try:
                decision = RiskDecisionEvent(**payload)
            except Exception:
                client.ack(RISK_DECISION_STREAM, group, entry_id)
                continue
            decisions_seen += 1

            target_cfg = policy.get("target_base_pct", {})
            neutral = float(target_cfg.get("neutral", 0.5)) if isinstance(target_cfg, dict) else 0.5
            step = float(target_cfg.get("confidence_step", 0.2)) if isinstance(target_cfg, dict) else 0.2
            min_target = float(target_cfg.get("min", 0.25)) if isinstance(target_cfg, dict) else 0.25
            max_target = float(target_cfg.get("max", 0.75)) if isinstance(target_cfg, dict) else 0.75
            intent_ttl_ms = int(
                policy.get("conflict_contract", {}).get("intent_ttl_ms", 60_000)
                if isinstance(policy.get("conflict_contract"), dict)
                else 60_000
            )
            actions_cfg = policy.get("actions", {})

            if decision.approved:
                predicted_return = 0.0
                confidence = 0.0
                try:
                    predicted_return = float(decision.metadata.get("predicted_return", "0"))
                    confidence = float(decision.metadata.get("confidence", "0"))
                except Exception:
                    pass
                if "model_version" in decision.metadata:
                    action = str(actions_cfg.get("approved_with_model_version", "set_target_base_pct"))
                    if predicted_return > 0:
                        target_base = min(max_target, neutral + (confidence * step))
                    elif predicted_return < 0:
                        target_base = max(min_target, neutral - (confidence * step))
                    else:
                        action = str(actions_cfg.get("approved_no_model_version", "resume"))
                        target_base = None
                else:
                    action = str(actions_cfg.get("approved_no_model_version", "resume"))
                    target_base = None
            else:
                action = str(actions_cfg.get("rejected", "soft_pause"))
                target_base = None

            intent = ExecutionIntentEvent(
                producer=svc_cfg.producer_name,
                correlation_id=decision.event_id,
                instance_name=decision.instance_name,
                controller_id="epp_v2_4",
                action=action,
                target_base_pct=target_base,
                expires_at_ms=int(time.time() * 1000) + intent_ttl_ms,
                metadata={
                    "reason": decision.reason,
                    "model_id": str(decision.metadata.get("model_id", "")),
                    "model_version": str(decision.metadata.get("model_version", "")),
                    "confidence": str(decision.metadata.get("confidence", "")),
                    "predicted_return": str(decision.metadata.get("predicted_return", "")),
                },
            )
            client.xadd(
                EXECUTION_INTENT_STREAM,
                intent.model_dump(),
                maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
            )
            intents_emitted += 1
            client.ack(RISK_DECISION_STREAM, group, entry_id)
        time.sleep(0.05)


if __name__ == "__main__":
    run()

