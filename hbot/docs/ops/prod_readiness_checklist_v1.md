# Production Readiness Checklist v1 (Option 4 Stack)

## Purpose
Provide an objective “prod readiness” scorecard for each service in the desk stack across: reliability, performance, QA, security, and operations.

## Readiness Levels
- **L0 (Prototype)**: works manually; weak reproducibility/ops.
- **L1 (Desk-Soak)**: safe enough for controlled soak with operator supervision.
- **L2 (Semi-Pro Prod)**: reproducible builds + alerts + recovery procedures; low-touch ops.
- **L3 (Institutional)**: strong SLAs, formal QA, advanced resilience and governance.

## Core Criteria (apply to every service)
### Build & Reproducibility
- [ ] Pinned dependencies (lockfile) and deterministic builds
- [ ] No `pip install` at container start (immutable image)
- [ ] Versioned image tags referenced in release manifest

### Runtime Reliability
- [ ] Healthcheck defined (liveness + readiness)
- [ ] Restart policy appropriate; startup time bounded
- [ ] Backoff/retry behavior for external deps
- [ ] Resource limits set (CPU/mem) and observed

### Observability
- [ ] Key metrics exported (Prometheus) incl. freshness/lag
- [ ] Structured logs; error rate measurable
- [ ] Alerts defined for stale/failed/lag conditions

### Data Integrity & Idempotency
- [ ] Idempotent ingestion/writes (no duplicate amplification on restart)
- [ ] Clear source-of-truth definition for outputs
- [ ] Retention policy defined for outputs/artifacts

### Security & Access
- [ ] Secrets not logged; principle of least privilege
- [ ] Key rotation procedure exists
- [ ] Network exposure minimized (bind to localhost where possible)

### QA & Change Control
- [ ] Unit tests for core logic (where applicable)
- [ ] Integration test or replay/regression gate
- [ ] Promotion gate blocks on critical failures

## Service-by-Service Scorecard (Day 27)
Status is evidence-backed from current artifacts and runtime topology.

| Service / Component | Current Level | Biggest Gaps (Top 3) | Evidence |
|---|---:|---|---|
| Hummingbot bots (`bot1`, `bot4`) | L1 | no formal per-bot SLO alerts; connector/paper parity noise; incomplete fill activity for blotter validation | `docs/ops/release_manifest_20260221.md`, `reports/parity/latest.json` |
| Redis (Streams bus) | L1 | backup/restore drill incomplete; durability SLO not enforced by gate; retention pressure policy not auto-checked | `docs/ops/bus_durability_policy.md` |
| `signal-service` | L1 | Redis-ping healthcheck is connectivity-only (not process liveness); no service-specific error-rate metric/alert; no output freshness SLO | `compose/docker-compose.yml` |
| `risk-service` | L1 | Redis-ping healthcheck is connectivity-only; no explicit deny/latency SLO alert; no output freshness SLO | `compose/docker-compose.yml` |
| `coordination-service` | L1 | Redis-ping healthcheck is connectivity-only; policy/SLO not explicit; no dedicated freshness/lag alert | `compose/docker-compose.yml` |
| `event-store-service` | L1.5 | JSONL growth/rotation control; healthcheck is freshness-based (events JSONL mtime) not process liveness; freshness SLO not yet strict-blocking in all paths | `reports/event_store/integrity_20260222.json`, `reports/event_store/day2_gate_eval_latest.json` |
| `reconciliation-service` | L1.5 | warnings still recurrent; healthcheck is report-freshness-based (not process liveness); accounting checks still v1 scope | `reports/reconciliation/latest.json` |
| `shadow-parity-service` | L1.5 | insufficient data paths tolerated too often; healthcheck is report-freshness-based; parity freshness alert ownership not explicit | `reports/parity/latest.json` |
| `portfolio-risk-service` | L1.5 | concentration brief cleared (status=ok); healthcheck is report-freshness-based; action SLO/false-positive budget not defined; kill-switch review checklist missing | `reports/portfolio_risk/latest.json` |
| `exchange-snapshot-service` | L1.5 | healthcheck is report-freshness-based (not process liveness); snapshot cadence SLO not explicit; history currently thin for trend analytics | `reports/exchange_snapshots/latest.json` |
| Promotion gates | L2 | CI automation not formalized; strict mode not mandatory in every release; stale-input fail-closed policy needs tightening | `reports/promotion_gates/latest.json`, `docs/validation/promotion_gate_contract.md` |
| Monitoring stack (Prometheus/Grafana/Loki/Alertmanager) | L2 | some ownership gaps on new alerts; dashboard-to-SLO mapping incomplete; periodic alert fire-drill cadence not formalized | `monitoring/prometheus/alert_rules.yml`, `docs/ops/runbooks.md` |
| Postgres + `ops-db-writer` | L1.5 | backup-restore drill pending; writer healthcheck present (report-freshness-based); fill table validation limited (fills rows = 0) | `reports/ops_db/postgres_sanity_latest.json`, `reports/ops_db_writer/latest.json` |

## SLO and Alert Ownership Matrix (Day 27 Baseline)
Owner role defaults to Desk Ops until reassigned.

| Domain | Baseline SLO | Alert Trigger | Owner | Evidence |
|---|---|---|---|---|
| Reconciliation freshness | latest report age <= 10 min | stale/missing reconciliation report | Desk Ops | `reports/reconciliation/latest.json` |
| Parity freshness | latest parity age <= 10 min | stale/missing parity report | Desk Ops | `reports/parity/latest.json` |
| Portfolio risk freshness/action | latest risk report age <= 5 min; critical actions reviewed <= 5 min | stale risk report or `status=critical` | Desk Ops | `reports/portfolio_risk/latest.json` |
| Event-store integrity | integrity report age <= 15 min, missing correlation = 0 | stale integrity or missing correlation > 0 | Desk Ops | `reports/event_store/integrity_20260222.json` |
| Promotion gate viability | latest gate run PASS before promotion | any critical gate fail | Desk Ops | `reports/promotion_gates/latest.json` |
| Ops DB writer ingestion | writer report age <= 10 min, status=pass | stale writer report or ingestion fail | Desk Ops | `reports/ops_db_writer/latest.json` |

## Day 27 Decision Checkpoint
- Current desk stack readiness: **L1.5 overall (Desk-Soak+)**.
- Not yet Semi-Pro Prod (L2) because healthchecks are freshness/connectivity-based (not process liveness), SLO ownership is incomplete, and promotion gate is currently FAIL (event store integrity stale).
- Promotion gate pipeline quality is strongest area and remains the backbone for safe incremental hardening.

## Update Protocol
When a service changes, update:
- target level (L0–L3),
- the top 3 gaps,
- and add a single evidence link (report path, gate output, or runbook section).

