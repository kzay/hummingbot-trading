from __future__ import annotations

import os
import time

from services.common.models import RedisSettings, ServiceSettings
from services.contracts.event_schemas import MlSignalEvent, RiskDecisionEvent, StrategySignalEvent
from services.contracts.stream_names import (
    DEFAULT_CONSUMER_GROUP,
    ML_SIGNAL_STREAM,
    RISK_DECISION_STREAM,
    SIGNAL_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient


def evaluate_ml_signal(
    signal: MlSignalEvent,
    confidence_min: float,
    max_signal_age_ms: int,
    max_abs_predicted_return: float,
) -> tuple[bool, str]:
    reasons = []
    if signal.confidence < confidence_min:
        reasons.append("ml_low_confidence")
    if signal.signal_age_ms > max_signal_age_ms:
        reasons.append("ml_stale_signal")
    if abs(signal.predicted_return) > max_abs_predicted_return:
        reasons.append("ml_predicted_return_outlier")
    approved = len(reasons) == 0
    reason = "approved_ml" if approved else ",".join(reasons)
    return approved, reason


def run() -> None:
    redis_cfg = RedisSettings()
    svc_cfg = ServiceSettings()
    max_abs_signal = float(os.getenv("RISK_MAX_ABS_SIGNAL", "0.25"))
    ml_enabled = os.getenv("ML_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    ml_confidence_min = float(os.getenv("ML_CONFIDENCE_MIN", "0.60"))
    ml_max_signal_age_ms = int(os.getenv("ML_MAX_SIGNAL_AGE_MS", "3000"))
    ml_max_abs_predicted_return = float(os.getenv("RISK_MAX_ABS_PREDICTED_RETURN", "0.05"))

    client = RedisStreamClient(
        host=redis_cfg.host,
        port=redis_cfg.port,
        db=redis_cfg.db,
        password=redis_cfg.password or None,
        enabled=redis_cfg.enabled,
    )
    group = svc_cfg.consumer_group or DEFAULT_CONSUMER_GROUP
    consumer = f"risk-{svc_cfg.instance_name}"
    source_stream = ML_SIGNAL_STREAM if ml_enabled else SIGNAL_STREAM
    client.create_group(source_stream, group)

    while True:
        entries = client.read_group(
            stream=source_stream,
            group=group,
            consumer=consumer,
            count=20,
            block_ms=svc_cfg.poll_ms,
        )
        for entry_id, payload in entries:
            if ml_enabled:
                try:
                    signal = MlSignalEvent(**payload)
                except Exception:
                    client.ack(source_stream, group, entry_id)
                    continue
                approved, reason = evaluate_ml_signal(
                    signal=signal,
                    confidence_min=ml_confidence_min,
                    max_signal_age_ms=ml_max_signal_age_ms,
                    max_abs_predicted_return=ml_max_abs_predicted_return,
                )
                decision = RiskDecisionEvent(
                    producer=svc_cfg.producer_name,
                    correlation_id=signal.event_id,
                    instance_name=signal.instance_name,
                    approved=approved,
                    reason=reason,
                    max_notional_quote=1000.0 if approved else 0.0,
                    min_spread_pct=0.0025,
                    metadata={
                        "signal_name": "ml_signal",
                        "model_id": signal.model_id,
                        "model_version": signal.model_version,
                        "confidence": str(signal.confidence),
                        "predicted_return": str(signal.predicted_return),
                    },
                )
            else:
                try:
                    signal = StrategySignalEvent(**payload)
                except Exception:
                    client.ack(source_stream, group, entry_id)
                    continue
                approved = abs(signal.signal_value) <= max_abs_signal
                reason = "approved" if approved else "signal_threshold_block"
                decision = RiskDecisionEvent(
                    producer=svc_cfg.producer_name,
                    correlation_id=signal.event_id,
                    instance_name=signal.instance_name,
                    approved=approved,
                    reason=reason,
                    max_notional_quote=1000.0 if approved else 0.0,
                    min_spread_pct=0.0025,
                    metadata={"signal_name": signal.signal_name},
                )
            client.xadd(
                RISK_DECISION_STREAM,
                decision.model_dump(),
                maxlen=STREAM_RETENTION_MAXLEN.get(RISK_DECISION_STREAM),
            )
            client.ack(source_stream, group, entry_id)
        time.sleep(0.05)


if __name__ == "__main__":
    run()

