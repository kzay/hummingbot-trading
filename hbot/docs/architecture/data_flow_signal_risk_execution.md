# Data Flow: Signal -> Risk -> Execution

## Purpose
Detail event lifecycle and decision propagation.

## Flow
```mermaid
flowchart LR
  md[hb.market_data.v1] --> sig[signal_service]
  sig --> ml["hb.ml_signal.v1 or hb.signal.v1"]
  ml --> risk[hb.risk_decision.v1]
  risk --> coord[coordination_service]
  coord --> intent[hb.execution_intent.v1]
  intent --> hb[HBIntentConsumer]
  hb --> audit[hb.audit.v1]
  hb --> dead[hb.dead_letter.v1]
```

## Sequencing Rules
- Every derived event sets `correlation_id` = upstream `event_id`.
- Risk decisions must include explicit reason codes.
- Intents must include expiry (`expires_at_ms`).

## Local Enforcement
- HB validates connector readiness and intent bounds before applying.
- Rejections are auditable.

## Failure Modes
- Stream lag -> stale signal rejection.
- Intent expiry -> dead-letter.
- Bus outage -> external-intent soft-pause path.

## Owner
- Engineering/Platform
- Last-updated: 2026-02-19

