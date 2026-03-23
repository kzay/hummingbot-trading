## STATUS: IMPLEMENTED

Infra layout consolidation is complete under `hbot/infra/`. Operators should run `docker compose` from `hbot/` using `--env-file infra/env/.env` and `-f infra/compose/docker-compose.yml` (or `cd hbot/infra/compose` with `--env-file ../env/.env` and `-f docker-compose.yml`).

## Scope (as shipped)

- `infra/compose/` — Docker Compose, image build contexts, service definitions
- `infra/monitoring/` — Prometheus, Grafana, Loki, Alertmanager, Promtail
- `infra/env/` — `.env.template` and host-local `.env` (never committed)
- `infra/firewall-rules.sh` — host firewall helper (replaces former `security/` tree)
- `config/` remains at `hbot/` root (application/runtime config, not ops-only)

**Also**: top-level `models/` removed (use `data/ml/models/` per `README.md`); `third_party/` → `docs/legal/`; top-level `backups/` removed (use `scripts/ops/pg_backup.py`, `reports/ops/`, and host archives).

## ADDED Requirements (satisfied)

### Requirement: Compose, monitoring, and env live under `infra/`
The project SHALL expose `infra/compose/`, `infra/monitoring/`, and `infra/env/` under `hbot/infra/`. `config/` remains at `hbot/` root.

### Requirement: Docker Compose resolves paths from `infra/compose/`
Volume mounts, build contexts, `env_file` references, and documented CLI examples SHALL resolve correctly from `infra/compose/docker-compose.yml`.

### Requirement: Shell and Python tooling use updated infra paths
Scripts and automation SHALL reference `infra/env/.env`, `infra/compose/`, and `infra/monitoring/` instead of legacy top-level `compose/`, `env/`, and `monitoring/`.

### Requirement: Cursor rules and documentation reflect the layout
Workspace layout documentation SHALL reference `infra/` paths for compose, env, and monitoring.
