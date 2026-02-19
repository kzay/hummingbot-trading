from __future__ import annotations

import time

from services.common.models import RedisSettings, ServiceSettings
from services.contracts.event_schemas import ExecutionIntentEvent, RiskDecisionEvent
from services.contracts.stream_names import (
    DEFAULT_CONSUMER_GROUP,
    EXECUTION_INTENT_STREAM,
    RISK_DECISION_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient


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

    while True:
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

            if decision.approved:
                predicted_return = 0.0
                confidence = 0.0
                try:
                    predicted_return = float(decision.metadata.get("predicted_return", "0"))
                    confidence = float(decision.metadata.get("confidence", "0"))
                except Exception:
                    pass
                if "model_version" in decision.metadata:
                    if predicted_return > 0:
                        action = "set_target_base_pct"
                        target_base = min(0.75, 0.50 + (confidence * 0.20))
                    elif predicted_return < 0:
                        action = "set_target_base_pct"
                        target_base = max(0.25, 0.50 - (confidence * 0.20))
                    else:
                        action = "resume"
                        target_base = None
                else:
                    action = "resume"
                    target_base = None
            else:
                action = "soft_pause"
                target_base = None

            intent = ExecutionIntentEvent(
                producer=svc_cfg.producer_name,
                correlation_id=decision.event_id,
                instance_name=decision.instance_name,
                controller_id="epp_v2_4",
                action=action,
                target_base_pct=target_base,
                expires_at_ms=int(time.time() * 1000) + 60_000,
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
            client.ack(RISK_DECISION_STREAM, group, entry_id)
        time.sleep(0.05)


if __name__ == "__main__":
    run()

