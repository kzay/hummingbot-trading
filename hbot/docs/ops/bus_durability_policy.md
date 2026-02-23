# Bus Durability Policy (Day 18)

## Purpose
Define Redis Streams durability posture, acceptable data loss policy, and recovery procedure for control-plane events.

## Current Runtime Configuration
- Bus: Redis Streams on `redis:7.2-alpine`
- Persistence: AOF enabled (`redis-server --appendonly yes`)
- Consumer groups:
  - shared control-plane group: `hb_group_v1`
  - event-store dedicated group: `hb_event_store_v1`
- Event-store source/ingest delta checks:
  - `scripts/utils/event_store_count_check.py`
  - `reports/event_store/source_compare_*.json`

## Durability Risks
- Redis is a single logical bus process in current topology.
- No explicit stream `MAXLEN` truncation policy configured -> growth risk if left unmanaged.
- AOF reduces restart loss risk but does not replace backup discipline.
- Consumer lag can create temporary visibility gaps if monitoring is stale.

## Acceptable Data Loss Policy
- `hb.execution_intent.v1`: **zero acceptable loss**
- `hb.audit.v1`: **zero acceptable loss**
- `hb.risk_decision.v1`: **zero acceptable loss**
- `hb.market_data.v1` / `hb.signal.v1` / `hb.ml_signal.v1`:
  - small bounded replayable loss tolerated if downstream safety signals remain intact.

## Recovery Verification Contract
After any Redis restart, pass all:
1. `missing_correlation_count == 0` in latest integrity artifact.
2. Produced vs ingested delta since baseline within tolerance (`<= 5` by default).
3. Day2 evaluator still reports structural checks as pass (elapsed-window may remain NO-GO by design).

Verification command:
- `python scripts/release/run_bus_recovery_check.py --label post_restart`
- Optional legacy strict absolute-delta mode:
  - `python scripts/release/run_bus_recovery_check.py --label post_restart --enforce-absolute-delta --max-delta 5`

Artifacts:
- `reports/bus_recovery/latest.json`
- `reports/bus_recovery/bus_recovery_<label>_<timestamp>.json`

## Backup / Restore (Desk Incident Story)
- Before risky maintenance:
  - capture latest durability snapshots (`integrity`, `source_compare`, day2 gate).
- For Redis persistence protection:
  - keep append-only persistence enabled.
  - ensure Redis volume (`redis-data`) is retained across container recreation.
- After restore/restart:
  - run bus recovery check and gate checks before resuming promotion actions.

## Optional Future Path (If Redis Becomes Bottleneck)
- Candidate: Redpanda/Kafka-compatible OSS event bus.
- Trigger conditions:
  - sustained high consumer lag,
  - unacceptable stream growth/retention pressure,
  - inability to meet zero-loss policy for critical streams.
- Migration should preserve:
  - event schema contracts,
  - consumer-group semantics,
  - audit/intent durability guarantees.

## Day 18 Drill Evidence
- Pre restart (v2 check): `reports/bus_recovery/bus_recovery_pre_restart_v2_20260222T021215Z.json` (`status=pass`)
- Post restart (v2 check): `reports/bus_recovery/bus_recovery_post_restart_v2_20260222T021306Z.json` (`status=pass`)
- Note:
  - absolute produced-vs-ingested historical backlog remains high and is tracked separately from restart-regression checks.
