# Day 25 - PostgreSQL Operational Store v1

## Scope
- Add PostgreSQL to runtime with persistence and health checks.
- Provision Grafana PostgreSQL datasource for desk analytics.

## Implemented
- Compose runtime:
  - `compose/docker-compose.yml`
  - new services:
    - `postgres` (profile `ops`)
    - optional `pgadmin` (profile `ops-tools`)
  - new volume:
    - `postgres-data`
- Grafana datasource provisioning:
  - `monitoring/grafana/provisioning/datasources/datasource.yml`
  - added datasource `PostgreSQL Ops` (`uid=postgres-ops`)
- Ops documentation:
  - `docs/ops/postgres_ops_store_v1.md`

## Validation
- Compose config validates with new services/profiles.
- Postgres starts healthy under `ops` profile.
- SQL sanity query executes successfully.
- Evidence artifact:
  - `reports/ops_db/postgres_sanity_latest.json`

## Result
- Desk now has a persistent operational SQL backend ready for Day 26 writer ingestion and Postgres-backed panels.
