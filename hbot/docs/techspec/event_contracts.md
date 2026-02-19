# Event Contracts

## Purpose
Specify event schemas, stream names, and compatibility expectations.

## Scope
Redis stream payload contracts for market, signal, risk, intent, audit, dead-letter.

## Contract Families
- Envelope fields:
  - `schema_version`, `event_type`, `event_id`, `correlation_id`, `producer`, `timestamp_ms`
- Domain events:
  - `MarketSnapshotEvent`
  - `StrategySignalEvent`
  - `MlSignalEvent`
  - `RiskDecisionEvent`
  - `ExecutionIntentEvent`
  - `AuditEvent`

## Stream Names
- `hb.market_data.v1`
- `hb.signal.v1`
- `hb.ml_signal.v1`
- `hb.risk_decision.v1`
- `hb.execution_intent.v1`
- `hb.audit.v1`
- `hb.dead_letter.v1`

## Compatibility Rules
- Additive schema changes only in v1.
- Breaking changes require new stream/version suffix.
- `event_id` is the idempotency key.
- `correlation_id` threads chain across derived events.

## Failure Modes
- Invalid payload -> dead-letter stream.
- Expired intents -> dead-letter with reason.

## Source of Truth
- `hbot/services/contracts/event_schemas.py`
- `hbot/services/contracts/stream_names.py`

## Owner
- Engineering/Platform
- Last-updated: 2026-02-19

