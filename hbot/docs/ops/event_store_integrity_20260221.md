# Event Store Integrity Snapshot - 2026-02-21

## Phase
Day 2 - Event Store Foundation

## Plan Executed
1. Implement append-only event store service scaffold.
2. Enforce correlation ID normalization (`correlation_id` fallback to `event_id`).
3. Run one-shot ingestion and capture integrity metrics.

## Runtime Evidence
- Service scaffold:
  - `hbot/services/event_store/main.py`
- Compose wiring:
  - `hbot/compose/docker-compose.yml` (`event-store-service` under `external` profile)
- Schema baseline:
  - `hbot/docs/architecture/event_schema_v1.md`
- Consumer-group topology hardening:
  - `event-store-service` moved to dedicated group `hb_event_store_v1`
  - avoids message contention with other services using `hb_group_v1`

## Integrity Output
- Integrity file:
  - `hbot/reports/event_store/integrity_20260221.json`
- Event file:
  - `hbot/reports/event_store/events_20260221.jsonl`
- Source comparison snapshot:
  - `hbot/reports/event_store/source_compare_20260221T153854Z.json`
  - `hbot/reports/event_store/source_compare_20260221T154204Z.json` (periodic monitor)
  - `hbot/reports/event_store/source_compare_20260221T183304Z.json` (baseline-aware)
  - `hbot/reports/event_store/baseline_counts.json`
  - `hbot/reports/event_store/source_compare_20260221T185002Z.json` (post topology fix)
  - `hbot/reports/event_store/day2_gate_eval_latest.json`
  - Gate monitor automation:
    - `hbot/scripts/utils/day2_gate_monitor.py`
    - compose service: `day2-gate-monitor` (external profile)

### Snapshot values
- `total_events`: 202
- `events_by_stream.hb.market_data.v1`: 38
- `events_by_stream.hb.signal.v1`: 18
- `events_by_stream.hb.risk_decision.v1`: 49
- `events_by_stream.hb.execution_intent.v1`: 96
- `events_by_stream.hb.audit.v1`: 1
- `missing_correlation_count`: 0

## Controlled Seed for Validation
- A controlled audit event was seeded to `hb.audit.v1` to verify ingestion path.
- Ingested event confirms `correlation_id` normalization:
  - input had empty `correlation_id`
  - stored output has `correlation_id == event_id`

## Day 2 Status
- Event schema finalized: DONE
- Append-only store running: DONE
- Correlation IDs present end-to-end (ingest contract): DONE
- 24h ingestion run: PENDING
- Source count tolerance over sustained window: IN_PROGRESS
  - Baseline-aware comparison added:
    - `delta_produced_minus_ingested_since_baseline` computed per stream
    - current baseline snapshot shows delta 0 at baseline creation point (expected)
  - Automated periodic snapshot monitor is active:
    - service: `event-store-monitor` (external profile)
    - current test interval: 60 seconds
  - Post topology fix verification:
    - `delta_produced_minus_ingested_since_baseline` within tolerance
    - current max absolute delta: 2 (allowed: 5)
  - Gate evaluator:
    - `go=false` currently only because elapsed window < 24h
    - latest automated gate check: `max_delta_observed=1` (threshold 5), `missing_correlation=0`

## Next Actions
- Keep `event-store-service` running for 24h observation window.
- Generate periodic count deltas by stream automatically (monitor active).
- Close Day 2 when sustained ingestion and tolerance checks pass after full 24h window from baseline reset (`2026-02-21T18:49:31Z`).
