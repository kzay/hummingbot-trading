from __future__ import annotations

import os
import time

from services.common.models import RedisSettings, ServiceSettings
from services.contracts.event_schemas import MarketSnapshotEvent, MlSignalEvent, StrategySignalEvent
from services.contracts.stream_names import (
    DEFAULT_CONSUMER_GROUP,
    MARKET_DATA_STREAM,
    ML_SIGNAL_STREAM,
    SIGNAL_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient
from services.signal_service.feature_builder import build_features
from services.signal_service.inference_engine import run_inference
from services.signal_service.model_loader import load_model


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
    consumer = f"signal-{svc_cfg.instance_name}"
    client.create_group(MARKET_DATA_STREAM, group)
    ml_enabled = os.getenv("ML_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    ml_runtime = os.getenv("ML_RUNTIME", "sklearn_joblib")
    ml_model_uri = os.getenv("ML_MODEL_URI", "")
    ml_custom_class_path = os.getenv("ML_CUSTOM_CLASS_PATH", "")
    ml_model_refresh_sec = int(os.getenv("ML_MODEL_REFRESH_SEC", "300"))
    ml_confidence_min = float(os.getenv("ML_CONFIDENCE_MIN", "0.60"))
    ml_inference_timeout_ms = int(os.getenv("ML_INFERENCE_TIMEOUT_MS", "200"))
    ml_horizon_s = int(os.getenv("ML_HORIZON_S", "60"))
    ml_feature_set = os.getenv("ML_FEATURE_SET", "v1")
    ml_http_timeout_sec = int(os.getenv("ML_S3_HTTP_TIMEOUT_SEC", "10"))

    loaded_model = None
    next_reload_ts = 0.0

    while True:
        if ml_enabled and (loaded_model is None or time.time() >= next_reload_ts):
            try:
                loaded_model = load_model(
                    runtime=ml_runtime,
                    model_uri=ml_model_uri,
                    custom_class_path=ml_custom_class_path,
                    timeout_sec=ml_http_timeout_sec,
                )
                next_reload_ts = time.time() + ml_model_refresh_sec
            except Exception:
                loaded_model = None
                next_reload_ts = time.time() + min(10, ml_model_refresh_sec)

        entries = client.read_group(
            stream=MARKET_DATA_STREAM,
            group=group,
            consumer=consumer,
            count=20,
            block_ms=svc_cfg.poll_ms,
        )
        for entry_id, payload in entries:
            try:
                market = MarketSnapshotEvent(**payload)
            except Exception:
                client.ack(MARKET_DATA_STREAM, group, entry_id)
                continue

            if ml_enabled and loaded_model is not None and ml_model_uri:
                try:
                    feature_vector, feature_map, feature_hash = build_features(market, ml_feature_set)
                    predicted_return, confidence, latency_ms = run_inference(loaded_model, feature_vector, feature_map)
                    if latency_ms <= ml_inference_timeout_ms and confidence >= ml_confidence_min:
                        ml_signal = MlSignalEvent(
                            producer=svc_cfg.producer_name,
                            correlation_id=market.event_id,
                            instance_name=market.instance_name,
                            controller_id=market.controller_id,
                            trading_pair=market.trading_pair,
                            model_id=loaded_model.model_id,
                            model_version=loaded_model.model_version,
                            runtime=loaded_model.runtime,  # type: ignore[arg-type]
                            horizon_s=ml_horizon_s,
                            predicted_return=predicted_return,
                            confidence=confidence,
                            feature_hash=feature_hash,
                            inference_latency_ms=latency_ms,
                            signal_age_ms=max(0, int(time.time() * 1000) - market.timestamp_ms),
                            metadata={"state": market.state, "feature_set": ml_feature_set},
                        )
                        client.xadd(
                            ML_SIGNAL_STREAM,
                            ml_signal.model_dump(),
                            maxlen=STREAM_RETENTION_MAXLEN.get(ML_SIGNAL_STREAM),
                        )
                except Exception:
                    pass
            else:
                imbalance = market.target_base_pct - market.base_pct
                signal = StrategySignalEvent(
                    producer=svc_cfg.producer_name,
                    correlation_id=market.event_id,
                    instance_name=market.instance_name,
                    signal_name="inventory_rebalance",
                    signal_value=float(imbalance),
                    confidence=min(1.0, abs(float(imbalance)) * 10),
                    metadata={"controller_id": market.controller_id, "state": market.state},
                )
                client.xadd(
                    SIGNAL_STREAM,
                    signal.model_dump(),
                    maxlen=STREAM_RETENTION_MAXLEN.get(SIGNAL_STREAM),
                )
            client.ack(MARKET_DATA_STREAM, group, entry_id)
        time.sleep(0.05)


if __name__ == "__main__":
    run()

