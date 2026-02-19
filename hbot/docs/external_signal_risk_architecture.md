# External Signal/Risk Architecture

This document describes the hybrid architecture where external services generate and gate signals, while Hummingbot remains the final execution safety authority.

## Design Goals

- Keep exchange connectivity centralized in Hummingbot.
- Decouple signal and risk processes from bot runtime.
- Enable multi-bot coordination with replayable event history.
- Preserve local Hummingbot safety controls as last-resort protection.

## Components

- **Hummingbot bridge**
  - Publishes market/controller snapshots.
  - Consumes approved execution intents.
  - Rejects intents failing local safety checks.
- **Signal service**
  - Consumes market snapshots, emits normalized signals.
  - Optional ML mode emits `hb.ml_signal.v1` with model metadata and confidence.
- **Risk service**
  - Consumes signals, emits approve/reject decisions.
- **Coordination service**
  - Converts approved decisions into execution intents.
- **Redis Streams**
  - Message transport, replay source, and audit trace.

## Streams

- `hb.market_data.v1`
- `hb.signal.v1`
- `hb.ml_signal.v1`
- `hb.risk_decision.v1`
- `hb.execution_intent.v1`
- `hb.audit.v1`
- `hb.dead_letter.v1`

## Safety Model

- External stack controls policy-level decisions.
- Hummingbot enforces connector readiness and local guardrails.
- If bus connectivity degrades, Hummingbot can soft-pause new intent handling.
- Global stop can still be triggered locally via local kill switches.

## Startup

```bash
cd hbot/compose
docker compose --env-file ../env/.env --profile multi --profile external up -d
```

## ML Runtime (MVP)

Phase 1 supports:

- `ML_RUNTIME=sklearn_joblib`
- `ML_RUNTIME=custom_python`

Model source options:

- `ML_MODEL_SOURCE=local` with `ML_MODEL_URI=/workspace/hbot/models/current/model.joblib`
- `ML_MODEL_SOURCE=http` or presigned URL (`https://...`) through `ML_MODEL_URI`
- `s3://` URI supported when `boto3` credentials are available in the signal-service runtime

Recommended rollout:

1. Enable ML publishing in shadow mode (`ML_ENABLED=true`) while keeping intent consumption conservative.
2. Observe `hb.ml_signal.v1` confidence/latency.
3. Enforce risk thresholds (`ML_CONFIDENCE_MIN`, `ML_MAX_SIGNAL_AGE_MS`) before scaling.

## Troubleshooting

- **No events published**
  - Verify `EXT_SIGNAL_RISK_ENABLED=true`.
  - Check `REDIS_HOST/PORT` reachability from bot containers.
- **Intents not applied**
  - Check `hb.dead_letter.v1` reasons for local authority rejects.
- **Frequent pause/resume toggles**
  - Review risk threshold env vars (`RISK_MAX_ABS_SIGNAL`).
- **ML signals rejected too often**
  - Lower `ML_CONFIDENCE_MIN` carefully and verify model calibration first.
- **No ML events on stream**
  - Check `ML_MODEL_URI`, model readability, and signal-service logs for loader errors.

