# Day 40 - ClickHouse Event Analytics Store (2026-02-22)

## Objective
- Add a high-volume event analytics store for event-store JSONL.
- Wire Grafana to query ClickHouse directly.

## Implemented
- Compose services (`ops` profile):
  - `clickhouse`
  - `clickhouse-ingest`
- Ingestion runtime:
  - `services/clickhouse_ingest/main.py`
  - stateful offsets and periodic health artifacts.
- Grafana datasource:
  - `ClickHouse Events` (`uid: clickhouse-events`)
  - provisioned in `monitoring/grafana/provisioning/datasources/datasource.yml`
- Ops policy doc:
  - `docs/ops/clickhouse_event_analytics_v1.md`

## Validation
- Syntax:
  - `python -m py_compile services/clickhouse_ingest/main.py`
- Dry run:
  - `python services/clickhouse_ingest/main.py --once --dry-run`

## Expected Evidence
- `reports/clickhouse_ingest/latest.json`
- `reports/clickhouse_ingest/state.json`

## Outcome
- Day 40 baseline delivered: ClickHouse runtime + JSONL ingestion + Grafana datasource for event analytics.
