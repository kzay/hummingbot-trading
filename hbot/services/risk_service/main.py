from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from services.common.graceful_shutdown import ShutdownHandler
from services.common.logging_config import configure_logging
from services.common.models import RedisSettings, ServiceSettings
from services.contracts.event_schemas import (
    AuditEvent,
    MlSignalEvent,
    RiskDecisionEvent,
    StrategySignalEvent,
)
from services.contracts.stream_names import (
    AUDIT_STREAM,
    DEFAULT_CONSUMER_GROUP,
    ML_SIGNAL_STREAM,
    RISK_DECISION_STREAM,
    SIGNAL_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient

configure_logging()

_REPORTS_DIR = Path(os.environ.get(
    "REPORTS_ROOT",
    str(Path(__file__).resolve().parents[2] / "reports" / "risk_service"),
))


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


def _write_latest(report: dict) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def run() -> None:
    shutdown = ShutdownHandler()
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

    decisions_total = 0
    decisions_approved = 0
    decisions_rejected = 0
    last_decision_ts = ""

    while not shutdown.requested:
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

            decisions_total += 1
            if approved:
                decisions_approved += 1
            else:
                decisions_rejected += 1
            last_decision_ts = datetime.now(timezone.utc).isoformat()

            if not approved:
                audit = AuditEvent(
                    producer=svc_cfg.producer_name,
                    instance_name=decision.instance_name,
                    severity="warning",
                    category="risk_decision",
                    message=f"Signal rejected: {reason}",
                    metadata=decision.metadata,
                )
                client.xadd(
                    AUDIT_STREAM,
                    audit.model_dump(),
                    maxlen=STREAM_RETENTION_MAXLEN.get(AUDIT_STREAM),
                )

        _write_latest({
            "service": "risk_service",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "ml_enabled": ml_enabled,
            "source_stream": source_stream,
            "decisions_total": decisions_total,
            "decisions_approved": decisions_approved,
            "decisions_rejected": decisions_rejected,
            "last_decision_ts": last_decision_ts,
            "redis_connected": client.enabled,
        })
        time.sleep(0.05)

    shutdown.log_exit()


if __name__ == "__main__":
    run()
