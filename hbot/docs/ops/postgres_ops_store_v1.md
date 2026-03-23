# PostgreSQL Operational Store v1 (Day 25)

## Purpose
Provide a persistent operational datastore for desk analytics and dashboards (blotter/wallet/equity history).

## Runtime Components
- `postgres` service in `infra/compose/docker-compose.yml` (profile: `ops`)
- optional `pgadmin` service (profile: `ops-tools`)
- Grafana datasource provisioning:
  - `infra/monitoring/grafana/provisioning/datasources/datasource.yml`
  - datasource uid: `postgres-ops`

## Environment Contract
- `OPS_DB_HOST` (default `postgres`)
- `OPS_DB_PORT` (default `5432`)
- `OPS_DB_NAME` (default `kzay_capital_ops`)
- `OPS_DB_USER` (default `hbot`)
- `OPS_DB_PASSWORD` (must be overridden outside local dev)
- Optional pgAdmin:
  - `PGADMIN_DEFAULT_EMAIL`
  - `PGADMIN_DEFAULT_PASSWORD`

## Startup
1. Start database:
   - `docker compose --env-file infra/env/.env --profile ops -f infra/compose/docker-compose.yml up -d postgres`
2. Check health:
   - `docker compose --env-file infra/env/.env --profile ops -f infra/compose/docker-compose.yml ps postgres`
3. Optional pgAdmin:
   - `docker compose --env-file infra/env/.env --profile ops --profile ops-tools -f infra/compose/docker-compose.yml up -d pgadmin`

## Sanity Query
Run a basic SQL check:
- `docker compose --env-file infra/env/.env --profile ops -f infra/compose/docker-compose.yml exec -T postgres psql -U ${OPS_DB_USER:-kzay_capital} -d ${OPS_DB_NAME:-kzay_capital_ops} -c "select now() as ts_utc;"`

## Backup/Restore + Drill (TS8)
- Automated backup cadence + verification:
  - `python scripts/ops/pg_backup.py --interval-hours ${OPS_DB_BACKUP_INTERVAL_HOURS:-24} --retention-count ${OPS_DB_BACKUP_RETENTION_COUNT:-7}`
  - Evidence: `reports/ops/ops_db_backup_latest.json`
- One-shot backup:
  - `python scripts/ops/pg_backup.py --once`
- Fresh-instance restore drill (canonical tables + parity sidecar validation):
  - `python scripts/ops/ops_db_restore_drill.py`
  - Evidence: `reports/ops/ops_db_restore_drill_latest.json`
- End-to-end drill runner (backup + restore + rollback timing):
  - `python scripts/ops/run_ops_db_drills.py`
  - Evidence: `reports/ops/ops_db_drills_latest.json`
- Rollback drill (`db_primary` -> `csv_compat`):
  - `python scripts/ops/data_plane_rollback_drill.py --env-file infra/env/.env --apply`
  - Evidence: `reports/ops/data_plane_rollback_drill_latest.json`

## Retention and Access
- Persistence volume: `postgres-data` (survives container restart/recreate).
- Access model:
  - write path: `ops-db-writer` service (`services/ops_db_writer/main.py`).
  - Grafana uses datasource-level credentials for read/query panels.

## Rollback
- Fast mode rollback from canonical DB primary to CSV compatibility:
  1. `python scripts/ops/data_plane_rollback_drill.py --env-file infra/env/.env --apply --from-mode db_primary --to-mode csv_compat`
  2. `python scripts/release/run_promotion_gates.py --max-report-age-min 20`
- Stop `ops` profile services when needed:
  - `docker compose --env-file infra/env/.env --profile ops -f infra/compose/docker-compose.yml down`
- Monitoring stack remains functional without Postgres-backed panels.
