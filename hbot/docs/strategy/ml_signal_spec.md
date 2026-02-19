# ML Signal Specification

## Purpose
Define how ML predictions are transformed into trading intents with risk controls.

## Scope
MVP runtime support:
- `sklearn_joblib`
- `custom_python`

Phase-2 target:
- ONNX runtime adapter.

## Signal Contract
- Event: `MlSignalEvent`
- Key fields:
  - `model_id`, `model_version`, `runtime`
  - `predicted_return`, `confidence`
  - `feature_hash`, `inference_latency_ms`, `signal_age_ms`

## Inference Pipeline
1. Consume `hb.market_data.v1`.
2. Build deterministic feature vector (`v1`).
3. Run inference.
4. Publish `hb.ml_signal.v1` when thresholds pass.

## Risk Gate Interface
- Minimum confidence: `ML_CONFIDENCE_MIN`.
- Maximum signal age: `ML_MAX_SIGNAL_AGE_MS`.
- Predicted return outlier cap: `RISK_MAX_ABS_PREDICTED_RETURN`.

## Intent Mapping
- Approved positive prediction -> `set_target_base_pct` upward tilt.
- Approved negative prediction -> `set_target_base_pct` downward tilt.
- Rejected decision -> `soft_pause`.

## Source of Truth
- `hbot/services/signal_service/*`
- `hbot/services/risk_service/main.py`
- `hbot/services/coordination_service/main.py`

## Owner
- ML/Research + Platform
- Last-updated: 2026-02-19

