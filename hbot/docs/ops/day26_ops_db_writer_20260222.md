# Day 26 - Ops DB Writer v1

## Scope
- Implement periodic ingestion of CSV/JSON operational artifacts into Postgres with idempotent upserts.
- Add first Grafana panels backed by Postgres tables.

## Implemented
- New service:
  - `services/ops_db_writer/main.py`
  - supports periodic mode and `--once` mode
  - writes evidence to `reports/ops_db_writer/latest.json`
- Schema/migration:
  - `services/ops_db_writer/schema_v1.sql`
  - tables:
    - `bot_snapshot_minute`, `bot_daily`, `fills`
    - `exchange_snapshot`
    - `reconciliation_report`, `parity_report`, `portfolio_risk_report`
    - `promotion_gate_run`
- Compose wiring:
  - `compose/docker-compose.yml`
  - service: `ops-db-writer` (profile `ops`, depends on healthy `postgres`)
- Runtime dependency for DB client:
  - `compose/images/control_plane/requirements-control-plane.txt` adds `psycopg==3.2.13`
- First Postgres-driven dashboard:
  - `monitoring/grafana/dashboards/ops_db_overview.json`
  - panels:
    - blotter table (last 100 fills)
    - wallet equity history (Postgres)
    - drawdown curve (Postgres)

## Validation
- Build updated control-plane image with `psycopg`.
- Run `ops-db-writer --once` against live Postgres.
- Verify row counts exist in key tables.
- Evidence:
  - `reports/ops_db_writer/ops_db_writer_20260222T032501Z.json` (`status=pass`)
  - row counts after ingest:
    - `bot_snapshot_minute=794`
    - `bot_daily=3`
    - `fills=0`
    - `exchange_snapshot=4`
    - `reconciliation_report=1`
    - `parity_report=1`
    - `portfolio_risk_report=1`
    - `promotion_gate_run=45`

## Result
- Ops DB writer now ingests and upserts desk operational data into Postgres.
- Grafana can query Postgres-backed blotter/wallet/drawdown panels without CSV inspection.
