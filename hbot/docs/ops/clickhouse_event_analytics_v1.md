# ClickHouse Event Analytics v1 (Day 40)

## Purpose
Provide a high-volume analytics store for event-store JSONL with low-latency querying in Grafana.

## Components
- Runtime database:
  - `clickhouse` service in `compose/docker-compose.yml` (`ops` profile)
- Ingestion service:
  - `services/clickhouse_ingest/main.py`
  - container: `clickhouse-ingest`
- Grafana datasource:
  - `monitoring/grafana/provisioning/datasources/datasource.yml`
  - datasource uid: `clickhouse-events`

## Ingestion Contract
- Source:
  - `reports/event_store/events_*.jsonl`
- Target:
  - `${CH_DB}.event_store_raw_v1`
- Stateful offsets:
  - `reports/clickhouse_ingest/state.json`
- Health artifacts:
  - `reports/clickhouse_ingest/latest.json`
  - `reports/clickhouse_ingest/clickhouse_ingest_<timestamp>.json`

## Core Table Fields
- `event_ts`
- `event_id`
- `correlation_id`
- `event_type`
- `producer`
- `instance_name`
- `controller_id`
- `source_file`
- `source_line`
- `payload_json`
- `raw_json`

## Notes
- v1 focuses on robust ingestion + datasource wiring.
- Derived marts/aggregations are a follow-up increment.
