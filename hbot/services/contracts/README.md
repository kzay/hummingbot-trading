# Event Contracts (v1)

This folder defines the canonical event contracts for the external Signal/Risk architecture.

## Streams

- `hb.market_data.v1`
- `hb.signal.v1`
- `hb.ml_signal.v1`
- `hb.risk_decision.v1`
- `hb.execution_intent.v1`
- `hb.audit.v1`
- `hb.dead_letter.v1`

## Envelope

All events include:

- `schema_version`
- `event_type`
- `event_id` (globally unique)
- `correlation_id` (optional trace chain)
- `producer`
- `timestamp_ms`

## Replay and Idempotency Rules

- Consumers must treat `event_id` as idempotency key.
- Producers should include `correlation_id` when derived from upstream event.
- Execution intents with expired `expires_at_ms` must be rejected and pushed to dead-letter stream.

## Retention

Retention policy defaults are defined in `stream_names.py`.

