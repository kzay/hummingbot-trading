# PostgreSQL Operational Store v1 (Day 25)

## Purpose
Provide a persistent operational datastore for desk analytics and dashboards (blotter/wallet/equity history).

## Runtime Components
- `postgres` service in `compose/docker-compose.yml` (profile: `ops`)
- optional `pgadmin` service (profile: `ops-tools`)
- Grafana datasource provisioning:
  - `monitoring/grafana/provisioning/datasources/datasource.yml`
  - datasource uid: `postgres-ops`

## Environment Contract
- `OPS_DB_HOST` (default `postgres`)
- `OPS_DB_PORT` (default `5432`)
- `OPS_DB_NAME` (default `hbot_ops`)
- `OPS_DB_USER` (default `hbot`)
- `OPS_DB_PASSWORD` (must be overridden outside local dev)
- Optional pgAdmin:
  - `PGADMIN_DEFAULT_EMAIL`
  - `PGADMIN_DEFAULT_PASSWORD`

## Startup
1. Start database:
   - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml up -d postgres`
2. Check health:
   - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml ps postgres`
3. Optional pgAdmin:
   - `docker compose --env-file env/.env --profile ops --profile ops-tools -f compose/docker-compose.yml up -d pgadmin`

## Sanity Query
Run a basic SQL check:
- `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml exec -T postgres psql -U ${OPS_DB_USER:-hbot} -d ${OPS_DB_NAME:-hbot_ops} -c "select now() as ts_utc;"`

## Backup/Restore (Minimum)
- Backup (logical dump):
  - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml exec -T postgres pg_dump -U ${OPS_DB_USER:-hbot} ${OPS_DB_NAME:-hbot_ops} > reports/ops_db/postgres_dump_latest.sql`
- Restore (manual, controlled):
  - `psql` restore into an empty/recovery DB during maintenance window.

## Retention and Access
- Persistence volume: `postgres-data` (survives container restart/recreate).
- Access model:
  - write path: `ops-db-writer` service (`services/ops_db_writer/main.py`).
  - Grafana uses datasource-level credentials for read/query panels.

## Rollback
- Stop `ops` profile services:
  - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml down`
- Monitoring stack remains functional without Postgres-backed panels.
