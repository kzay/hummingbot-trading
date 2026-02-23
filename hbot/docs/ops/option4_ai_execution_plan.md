# Option 4 AI Execution Plan (Rolling, Day 1–21)

## Objective
Execute a semi-pro desk hardening path with:
- `Hummingbot` kept as live execution engine
- External reliability layers added for validation, reconciliation, and portfolio risk
- Free/open-source-first tooling only

## Scope and Constraints
- Do not rewrite core strategy this week.
- Prioritize reliability, observability, and safety over feature expansion.
- Every change must include:
  - rollback step
  - verification step
  - risk impact note

## Baseline Context
- Strategy/controller: `hbot/controllers/epp_v2_4.py`
- Paper/sim adapter: `hbot/controllers/paper_engine.py`
- Ops guardrails: `hbot/controllers/ops_guard.py`
- Deployment/orchestration: `hbot/compose/docker-compose.yml`
- Validation docs: `hbot/docs/validation/validation_plan.md`, `hbot/docs/validation/release_gates.md`
- Monitoring exporter: `hbot/services/bot_metrics_exporter.py`

## Parallel Tracks (Run Daily)
This 7-day plan is intentionally multi-track. The “Day N” sections below are the primary reliability path, but we must also run validation and dev-productivity work in parallel.

### Track R - Reliability (Primary)
- Event capture → reconciliation → parity → portfolio risk → promotion gates → soak.

### Track V - Validation (Backtesting + Paper Trading)
Goal: reduce “it worked live once” risk by adding repeatable, versioned validation evidence.

- Backtesting (regression-oriented, not optimization):
  - Use fixed assumptions (fees, slippage, latency budget) and document them.
  - Focus on detecting behavioral regressions in controller/risk/intent pipelines, not maximizing returns.
  - Output an artifacted report (JSON + short markdown) with config hash + dataset window + metrics.
- Paper trading:
  - Treat paper smoke and paper soak as required pre-promotion gates (see Day 6).
  - Use the existing smoke matrix called out in `hbot/docs/validation/validation_plan.md` and `hbot/docs/validation/release_gates.md`.

### Track D - Local Dev Productivity (Open-Source Only)
Goal: shorten iteration time and reduce “works on one machine” drift.

- Standardize a one-command local bring-up (compose profiles + preflight).
- Add a small set of deterministic “developer checks” that run fast (format/lint/tests + minimal smoke).
- Prefer containerized local dependencies so Windows hosts stay clean.

## Open-Source External Services We Can Use (Optional, Compose-Friendly)
These are optional building blocks to improve repeatability, observability, and local validation. Start minimal; add only when a clear pain point exists.

- Event/log pipelines:
  - **Redpanda** (Kafka-compatible) or **Kafka**: durable bus for event-store/replay/shadow tooling.
  - **NATS**: lightweight pub/sub for internal signals (if Kafka is overkill).
- Storage/query:
  - **PostgreSQL**: reconciliation/parity snapshots + gate history + incident timeline (simple queries).
  - **ClickHouse**: high-volume event analytics when JSONL becomes too slow to query.
  - **MinIO** (S3-compatible): store artifacts (reports, snapshots, datasets) with retention policies.
- Observability:
  - **OpenTelemetry Collector** + **Jaeger/Tempo**: trace correlation across services (beyond logs).
  - (Already present in stack) Prometheus/Grafana/Loki/Alertmanager.
- Workflow/automation:
  - **Prefect** (OSS): scheduled jobs (recon, parity, gate runner) with retries and visible run history.

---

## Day 1 - Baseline Freeze and Safety Guardrails

### Tasks
- Freeze current production baseline (image tag, active config set, risk thresholds).
- Create release manifest with exact runtime inputs.
- Verify hard-stop and soft-pause paths are operational.
- Confirm monitoring stack health and alert delivery path.
- Track V (paper baseline): ensure paper smoke configs are present and runnable per `hbot/docs/validation/validation_plan.md`.
- Track D (dev baseline): document the “one command” to bring up required services + bots + external profile.

### Deliverables
- `docs/ops/release_manifest_YYYYMMDD.md`
- `docs/ops/baseline_verification_YYYYMMDD.md`

### Done Criteria
- Reproducible startup from manifest.
- One tested hard-stop scenario recorded.
- Paper smoke can be launched from a clean workspace using documented commands (even if it’s not run for long yet).

---

## Day 2 - Event Store Foundation

### Tasks
- Define canonical event schema:
  - order created/cancelled/failed
  - fills
  - risk decisions
  - state snapshots
- Implement append-only event store service.
- Add correlation IDs for traceability.
- Validate event completeness vs source logs.
- Track V (replay seed): capture one known-good short window (e.g., 30-60 minutes) of events as a replayable dataset for regression checks.

### Deliverables
- `docs/architecture/event_schema_v1.md`
- `services/event_store/` (or equivalent internal path)
- Event integrity report script
- Replay dataset seed (versioned) under `reports/event_store/` with a documented window and config hash

### Done Criteria
- 24h ingestion with no critical loss.
- Source/event-count delta within tolerance.
- A short replay window exists and can be re-processed deterministically to reproduce counts and schema validation.

---

## Day 3 - Reconciliation Service

### Tasks
- Add periodic reconciliation jobs:
  - balances
  - positions/inventory
  - order/fill parity
- Classify drift severities (`warning`, `critical`).
- Expose reconciliation metrics and alerts.
- Track V (paper verification): run the paper smoke matrix once and capture evidence artifacts (logs + reconciliation report referencing paper mode).

### Deliverables
- `services/reconciliation_service/`
- `docs/ops/reconciliation_runbook.md`
- Grafana panels and alert rules for drift
- Paper smoke evidence captured under `reports/` (or referenced from `docs/ops/`)

### Done Criteria
- Reconciliation runs on schedule.
- Synthetic drift test triggers expected alert.
- Paper smoke run produces reconciliation output with expected severities (no unexplained criticals).

---

## Day 4 - Shadow Execution and Parity

### Tasks
- Build shadow evaluator for expected vs realized execution.
- Track parity KPIs:
  - fill ratio delta
  - slippage delta (bps)
  - reject rate delta
  - realized PnL delta
- Persist daily parity reports.
- Track V (regression backtest definition): define a minimal regression “backtest” harness for controller/risk/intent behavior using:
   - recorded candles (or recorded events) + fixed fee/slippage assumptions
   - expected invariants (no-trade variants place zero orders; risk denies are deterministic; intent expiry respected)
- Track D (dev speed): ensure parity/recon can be run locally in “--once” mode without full soak.

### Deliverables
- `services/shadow_execution/`
- `docs/validation/parity_metrics_spec.md`
- `reports/parity/YYYYMMDD/`
- `docs/validation/backtest_regression_spec.md` (assumptions + metrics + invariants)
- A script entrypoint for local regression runs (path decided during implementation)

### Done Criteria
- Daily parity report generated automatically.
- Pass/fail thresholds defined and versioned.
- Regression harness produces a versioned PASS/FAIL output on the replay dataset seed (from Day 2).

---

## Day 5 - Portfolio Risk Aggregation

### Tasks
- Add portfolio-level risk controls:
  - global daily loss cap
  - cross-bot net exposure cap
  - concentration caps
- Connect policy actions to pause/kill paths.
- Log all risk actions to immutable audit trail.
- Track V: add at least one portfolio-risk regression scenario (synthetic breach) that proves controls trip and are audited.

### Deliverables
- `services/portfolio_risk_service/`
- `docs/risk/portfolio_limits_v1.md`
- `docs/risk/kill_switch_audit_spec.md`

### Done Criteria
- Breach simulation triggers expected controls.
- Audit trail confirms action provenance.
- A deterministic “risk breach” test run is repeatable and produces identical audit structure.

---

## Day 6 - Promotion Gate Automation

### Tasks
- Build automated gate runner for:
  - preflight checks
  - smoke tests
  - paper smoke matrix (required)
  - regression backtest harness (required for any strategy/controller/risk changes; recommended even for infra changes)
  - reconciliation status
  - parity thresholds
  - alerting health
- Block promotion on critical gate failure.

### Deliverables
- `scripts/release/run_promotion_gates.py` (or equivalent)
- `docs/validation/promotion_gate_contract.md`

### Done Criteria
- Single command outputs PASS/FAIL with reasons.
- Failed critical gate blocks deployment.
- Gate output references evidence artifact paths (reports + logs) so operators can debug quickly.

---

## Day 7 - Controlled Soak and Decision

### Tasks
- Run 24h-48h micro-capital soak on Bitget live connector.
- Monitor stability, drift, parity, and risk action frequency.
- Produce readiness decision: continue hardening vs migration-later trigger.
- Track V: run a short (multi-hour) paper soak in parallel (or immediately before live soak) to compare parity/recon noise and validate “no uncontrolled orders” variants.

### Deliverables
- `docs/ops/soak_report_YYYYMMDD.md`
- `docs/ops/option4_readiness_decision.md`

### Done Criteria
- Critical incidents triaged and documented.
- Evidence-based next-step decision finalized.
- Decision explicitly cites: gate runner PASS/FAIL, paper smoke/soak evidence, parity/recon trend, and event-store integrity trend.

---

## Day 8 - Reproducible Builds (External Control Plane)

### Tasks
- Convert external services from “pip install at runtime” to **pinned, versioned images** (or equivalent reproducible packaging).
- Lock Python dependencies (hashes if possible) and capture build provenance.
- Add a “desk runtime” mode that does not rely on mutable dependency resolution.

### Deliverables
- Versioned build artifacts for external services (images/tags) + a short build/run doc.
- Updated release manifest to include external service versions.

### Done Criteria
- A fresh host can bring up the external profile with **no runtime dependency downloads**.
- Rolling restart of external services completes within expected time budget and yields identical behavior.

---

## Day 9 - Game Day: Fail-Closed Under Partial Outage

### Tasks
- Run at least one controlled failure drill:
  - Redis outage / consumer lag / external services restart storm.
- Validate system behavior is **fail-closed**:
  - promotion blocked
  - bots pause/stop per policy
  - alerts fire with actionable context
- Record the exact steps and outcomes.

### Deliverables
- `docs/ops/game_day_YYYYMMDD.md` (scenario, steps, timelines, results, fixes)
- One or more incident entries if applicable (`docs/ops/incidents.md`)

### Done Criteria
- No “silent unsafe” mode observed (no uncontrolled live placement during degraded control-plane conditions).
- Recovery steps are documented and repeatable.

---

## Day 10 - Replay + Regression Harness (First-Class Gate Input)

### Tasks
- Turn the Day 2 replay seed into a deterministic “replay → reconcile → parity → risk” regression run.
- Produce stable PASS/FAIL outputs and store artifacts with retention rules.

### Deliverables
- A single entrypoint command/script for regression replay (path chosen during implementation).
- Regression artifacts: JSON result + short markdown summary with evidence pointers.

### Done Criteria
- Two consecutive runs on the same dataset yield the same PASS/FAIL and stable metrics within tolerance.
- Gate runner can consume the regression result as an input.

---

## Day 11 - Local Dev Acceleration (Open-Source Only)

### Tasks
- Standardize developer workflow:
  - one-command bring-up for test profile and external profile
  - fast “developer checks” (lint/unit + minimal smoke)
- Reduce “stale cache” footguns (documented and automated where possible).

### Deliverables
- `docs/dev/local_dev_quickstart.md` (or equivalent) with canonical commands.
- A small command wrapper (Makefile / task runner / scripts) to run the fast checks.

### Done Criteria
- A new machine (or clean workspace) can run:
  - paper smoke (bot3) + binance testnet smoke (bot4) using the documented workflow
- Dev checks run in a short, predictable time window.

---

## Day 12 - Security + Secrets Hygiene

### Tasks
- Review and harden secret handling:
  - env files, credential prefixes, accidental logging
  - principle of least privilege on API keys (trade-only, IP allowlist if possible)
- Add a key rotation procedure and “break-glass” policy.

### Deliverables
- `docs/ops/secrets_and_key_rotation.md`
- Updated runbooks with safe handling rules (what must never be committed/logged).

### Done Criteria
- Rotation can be executed without downtime beyond the planned restart window.
- No secrets appear in logs or reports under normal operation.

---

## Day 13 - Artifact Retention + Auditability

### Tasks
- Define and implement retention for:
  - event store snapshots
  - reconciliation/parity/risk reports
  - gate results
- Ensure audit trail is queryable and tied to a release/manifests.

### Deliverables
- `docs/ops/artifact_retention_policy.md`
- Gate output includes stable references (paths/IDs) to evidence artifacts.

### Done Criteria
- Operator can answer “what happened yesterday?” from artifacts without scraping raw logs.
- Evidence is sufficient to reproduce and triage a drift/parity/risk event.

---

## Day 14 - Migration Spike (Timeboxed) + Decision Update

### Tasks
- Run a small, bounded spike to measure the cost of migrating away from the current execution engine:
  - define required features (connectors, order lifecycle, risk veto, audit)
  - prototype minimal “execution adapter” or alternative stack in paper only
- Update the readiness decision rubric with results.

### Deliverables
- `docs/ops/migration_spike_YYYYMMDD.md` (findings, estimate, risks, recommendation)
- Updated `docs/ops/option4_readiness_decision.md` criteria (continue Option 4 vs start migration track).

### Done Criteria
- Clear go/no-go for deeper migration investment based on measured effort and risk, not guesses.

---

## Day 15 - Bitget Live Connector Productionization (Micro-Cap)

### Tasks
- Shift primary evidence gathering to **Bitget live micro-cap** (not just testnet/paper):
  - define a minimal, safe capital envelope and symbols
  - run a short controlled live window and capture artifacts
- Add Bitget-specific incident taxonomy (disconnects, order rejects, funding/position nuances).
- Validate “no-trade” variant on Bitget live environment (must place zero orders).

### Deliverables
- `docs/ops/bitget_live_microcap_run_YYYYMMDD.md` (setup, limits, outcomes, incidents)
- Updated runbooks with Bitget live startup + rollback steps.

### Done Criteria
- Live Bitget window completes with **no uncontrolled behavior** and evidence artifacts captured.
- Any connector issues are triaged into actionable fixes/workarounds.

---

## Day 16 - Desk-Grade Accounting v1 (Fees/Funding/Positions)

### Tasks
- Define the desk accounting contract for:
  - fees paid (by venue/asset)
  - funding/borrow (if perps/margin)
  - realized vs unrealized PnL
  - position inventory snapshots
- Extend reconciliation to include at least one accounting integrity check beyond base_pct drift.

### Deliverables
- `docs/validation/accounting_contract_v1.md`
- One new accounting check wired into reconciliation output (with thresholds).

### Done Criteria
- Operator can explain daily PnL drivers (fees/funding/price move) using artifacts, not ad-hoc log scraping.

---

## Day 17 - Promotion Gates v2 + CI Execution

### Tasks
- Make gate runner the single source of promotion truth:
  - include freshness checks for recon/parity/risk/event-store integrity
  - include paper smoke matrix + regression replay outputs
- Run gates in a CI-like mode locally (non-interactive) and store results as artifacts.

### Deliverables
- Gate output artifact format (JSON + markdown summary) with stable evidence links.
- `docs/validation/promotion_gate_contract.md` updated with v2 inputs (freshness + replay).

### Done Criteria
- A single command produces a deterministic PASS/FAIL suitable for “solo desk release”.

---

## Day 18 - Bus Resilience + Data Loss Prevention

### Tasks
- Review Redis Streams durability settings and operational risks:
  - persistence mode, restart behavior, retention (`maxlen`) policies
  - backup/restore story for desk incident recovery
- Define “acceptable data loss” for control-plane events (ideally zero for audit/risk intents).
- If Redis is a bottleneck, draft a minimal OSS migration path (e.g., Redpanda) as an optional future step.

### Deliverables
- `docs/ops/bus_durability_policy.md`
- A recovery procedure section added to `docs/ops/runbooks.md` (bus restart + verification).

### Done Criteria
- You can restart the bus without losing critical audit/intent capability or creating silent staleness.

---

## Day 19 - Multi-Bot Scaling + Isolation Rules

### Tasks
- Define scaling rules:
  - which bots are allowed to trade live, which are test-only, which are paper-only
  - resource limits, restart policy, and failure isolation expectations
- Add explicit per-bot safety envelopes (max notional, symbols, mode) and document them.

### Deliverables
- `docs/ops/multi_bot_policy_v1.md`
- Updated compose/runbooks to reflect the policy and the canonical profiles to run.

### Done Criteria
- Adding a new bot instance does not change the risk profile of existing bots without an explicit policy edit + gate run.

---

## Day 20 - Security Hardening v2 (Operational Reality)

### Tasks
- Enforce “no secrets in artifacts”:
  - verify reports/logs do not contain API keys/passphrases
  - tighten logging around credential prefix diagnostics
- Add a minimal “break-glass” procedure:
  - how to disable trading safely if operator access is limited

### Deliverables
- Updated `docs/ops/secrets_and_key_rotation.md` with operational do/don’t rules and break-glass steps.
- A small checklist section in runbooks: “pre-release secrets hygiene”.

### Done Criteria
- A release can be executed without accidental credential exposure in logs/reports.

---

## Day 21 - Weekly Readiness Review + Decision Checkpoint

### Tasks
- Perform a structured review of the last week:
  - event integrity trend
  - recon/parity trends and false positives
  - risk action frequency
  - incidents and recovery time
- Update go/no-go:
  - continue Option 4 hardening vs start deeper migration track
- Tighten thresholds only if noise is stable and data sufficiency improved.

### Deliverables
- `docs/ops/weekly_readiness_review_YYYYMMDD.md`
- Updated `docs/ops/option4_execution_progress.md` and readiness decision rubric.

### Done Criteria
- A clear, evidence-backed decision is recorded with next week’s top risks and mitigations.

---

## Day 22 - Pro Desk Dashboards v1 (Control Plane + Multi-Bot)

### Tasks
- Upgrade monitoring from “bot-only KPIs” to a desk view that includes the **control plane**:
  - event-store Day2 gate status + freshness
  - reconciliation status + freshness
  - parity status + freshness
  - portfolio-risk status + freshness
- Add explicit alerting for stale/unknown control-plane outputs (fail-closed bias for promotions).

### Deliverables
- New/updated Grafana dashboard: `Trading Desk Control Plane` (multi-bot + service health + freshness).
- Updated Prometheus alert rules for freshness and gate failures.

### Done Criteria
- Operator can see, on one screen, whether promotion is safe: **gate GO/NO-GO + all control-plane services fresh**.

---

## Day 23 - Wallet/Positions + Blotter v1 (Open-Source, Practical)

### Tasks
- Make “wallet and positions” visible in Grafana:
  - export key fields from `reports/exchange_snapshots/latest.json` (per bot: equity, assets, base_pct, probe status)
- Make “trade activity” visible:
  - expose fills count + last fill timestamp and (optionally) a simple fills table source (file-based or logs-based)

### Deliverables
- Exchange snapshot Prometheus exporter (or extension of existing exporter) with per-bot wallet/position gauges.
- Grafana panels: wallet snapshot by bot, equity by bot, and basic blotter indicators.

### Done Criteria
- You can answer “what does each bot hold?” and “did it trade recently?” without opening CSVs or containers.

---

## Day 24 - Performance Analytics v1 (Desk-Grade, Still Lightweight)

### Tasks
- Add portfolio performance panels:
  - equity curve (per bot and aggregate)
  - drawdown curve
  - daily PnL distribution and rolling stats
- Extend the bot metrics exporter to publish the missing “pro” risk metrics already present in `minute.csv`:
  - `equity_quote`, `base_pct`, `target_base_pct`
  - `daily_loss_pct`, `drawdown_pct`
  - `cancel_per_min`, `risk_reasons` (as label/info metric)

### Deliverables
- Extended `bot-metrics-exporter` metrics set + updated `Hummingbot Trading Desk Overview` panels.
- `docs/ops/dashboard_kpi_contract_v1.md` (what each panel means + the metric source).

### Done Criteria
- You can review performance and risk posture for all bots (PnL + drawdown + activity) from Grafana with <1 minute triage time.

---

## Day 25 - PostgreSQL Operational Store v1 (Desk UI Backbone)

### Tasks
- Add PostgreSQL to the runtime stack (compose profile) with persistent storage and sane defaults:
  - retention/backups plan (minimum: periodic dump)
  - read-only access for Grafana
- Provision Grafana PostgreSQL datasource for dashboards (blotter, wallet history, equity curves).

### Deliverables
- Compose additions for `postgres` + volume + optional `pgadmin` (optional).
- `docs/ops/postgres_ops_store_v1.md` (connection, backup/restore, retention, access model).
- Grafana datasource provisioning (or manual steps documented).

### Done Criteria
- Postgres survives restarts and retains data.
- Grafana can query Postgres and render a simple test panel (sanity query).

---

## Day 26 - Ops DB Writer v1 (CSV/JSON → Postgres, Idempotent)

### Tasks
- Implement an `ops-db-writer` service that periodically ingests:
  - bot CSV snapshots (`minute.csv`, `daily.csv`, `fills.csv`)
  - control-plane reports (`reports/reconciliation/latest.json`, `reports/parity/latest.json`, `reports/portfolio_risk/latest.json`)
  - exchange snapshots (`reports/exchange_snapshots/latest.json`)
  - promotion gate outputs (`reports/promotion_gates/*.json`)
- Use idempotent keys/upserts to avoid duplicate rows.
- Store ingest metadata (`ingest_ts_utc`, source path, schema version).

### Deliverables
- `services/ops_db_writer/` (or equivalent) + compose wiring under an `external`/`ops` profile.
- Minimal Postgres schema/migrations for:
  - `bot_snapshot_minute`, `bot_daily`, `fills`
  - `exchange_snapshot`
  - `reconciliation_report`, `parity_report`, `portfolio_risk_report`
  - `promotion_gate_run`
- First “pro” dashboard panels driven by Postgres:
  - multi-bot blotter table (last N fills)
  - wallet/positions history (per bot)
  - equity + drawdown curves (per bot and aggregate)

### Done Criteria
- The writer runs unattended, produces stable row counts, and can be restarted without duplicating data.
- Grafana renders blotter + wallet history + equity curve from Postgres (no CSV browsing needed for routine ops).

---

## Day 27 - Production Readiness Audit v1 (Per-Service)

### Tasks
- Run a structured readiness audit of the entire stack using:
  - `docs/ops/prod_readiness_checklist_v1.md`
- For each service, define:
  - target readiness level (L0–L3)
  - top 3 gaps (highest risk/ROI)
  - explicit SLOs (freshness/lag/error rate) and alert ownership
- Convert the audit into a short prioritized hardening backlog (top 10).

### Deliverables
- Updated `docs/ops/prod_readiness_checklist_v1.md` with current levels and evidence.
- `docs/ops/prod_hardening_backlog_v1.md` (top 10 items + acceptance criteria).

### Done Criteria
- You can answer “is it prod-ready?” with a per-service scorecard and measurable SLOs, not vibes.

---

## Day 28 - Prod Hardening Sprint v1 (Reproducibility + SLOs + Recovery)

### Tasks
- Reproducibility:
  - eliminate runtime `pip install` for external services (immutable images + pinned deps)
  - ensure release manifest pins versions for all control-plane services
- Reliability:
  - add healthchecks + restart policies where missing
  - enforce freshness checks in promotion gates for recon/parity/risk/event store
- Recovery:
  - document and test restart recovery for Redis + key services (mini game-day)

### Deliverables
- Versioned images for control-plane services (or equivalent reproducible packaging).
- Updated Prometheus alert rules for freshness/lag and critical service down.
- Gate runner updated to fail on stale/unknown critical inputs.
- `docs/ops/recovery_drills_v1.md` (steps + expected outcomes + evidence pointers).

### Done Criteria
- A bad deployment or partial outage is detectable within minutes and has a documented, repeatable rollback/recovery path.
- Promotion is blocked automatically if critical safety signals are stale/unknown.

---

## Day 29 - Strategy/Controller Modularization v1 (Catalog + Config-Driven Selection)

### Tasks
- Make strategy/controller selection fully **config-driven** and avoid per-bot code drift:
  - define naming conventions for controller configs and script configs (strategy + version + mode + venue)
  - define a “strategy catalog” layout (approved bundles + defaults + risk envelope)
- Reduce operational overhead of adding strategies:
  - minimize the need to edit compose when adding a new controller
  - ensure all bots can load controllers from the shared repo mount

### Deliverables
- `docs/ops/strategy_catalog_v1.md` (structure, naming, versioning, promotion rules).
- Config templates directory and conventions documented (where new configs live, how to name them).

### Done Criteria
- Adding a new strategy/controller requires **no code copying into bot folders** and ideally **no compose edits**—only new shared code + new config templates.

---

## Day 30 - Compose Mount Simplification + Drift Prevention (Controllers as Shared Module)

### Tasks
- Simplify compose mounts to be strategy-scalable:
  - mount `hbot/controllers/` as a directory (read-only) instead of mounting individual controller `.py` files per bot
  - keep bot folders focused on `conf/`, `logs/`, `data/`, `scripts/`
- Add a drift-prevention check:
  - validate that bots are not running with ad-hoc controller overrides
  - validate strategy config references resolve to the shared catalog paths
- Update runbooks for the new structure (including pycache invalidation guidance for dev vs prod).

### Deliverables
- Updated `hbot/compose/docker-compose.yml` mounting strategy (shared controllers/services).
- `scripts/release/check_strategy_catalog_consistency.py` (or equivalent) run as part of promotion gates.
- Runbook updates: “add new strategy”, “add new bot”, “select strategy by config”.

### Done Criteria
- You can add a new controller version and roll it out to a specific bot by **changing only the bot’s config selection**, with gates catching drift/misconfig.

---

## Day 31 - Test Suite Formalization + Gate Integration (CI-Ready)

### Tasks
- Wire existing tests (`hbot/tests/`) into the promotion gate and dev workflow:
  - unit: `test_paper_engine`, `test_event_schemas`, `test_intent_idempotency`
  - service: `test_ml_risk_gates`, `test_ml_feature_builder`, `test_ml_model_loader`
  - integration: `test_signal_risk_flow`, `test_ml_signal_to_intent_flow`
- Add a single `run_tests.py` entrypoint (or Makefile target) to run all tests deterministically.
- Set a minimum coverage target for controller/risk/services.
- Wire test PASS/FAIL into promotion gates (critical block on unit test failure).

### Deliverables
- `scripts/release/run_tests.py` (or equivalent) — test runner with JSON + markdown output.
- Coverage report artifact per run.
- Promotion gate updated: unit test PASS is required for promotion.

### Done Criteria
- All existing tests pass in a clean environment and produce a stable PASS/FAIL artifact.
- A failing test blocks promotion automatically.

---

## Day 32 - Coordination Service Audit + Policy (Silent Live Service)

### Tasks
- Audit `services/coordination_service/main.py`:
  - it reads risk decisions and emits `set_target_base_pct` intents (ML-driven inventory targeting)
  - is this intentional, tested, and safe for current live scope?
- Define its operational policy:
  - when should it run (ML-enabled only? per-bot scope?)
  - what are its safety limits (target_base_pct min/max clamp)
  - what happens when it conflicts with OpsGuard/portfolio-risk
- Add a runbook section and healthcheck.

### Deliverables
- `docs/ops/coordination_service_policy_v1.md`
- Runbook updated with start/stop and scope controls.
- Promotion gate or policy checker validates it runs only in permitted scope/mode.

### Done Criteria
- The coordination service is no longer a "silent" service; its behavior and limits are documented and enforceable.

---

## Day 33 - Control Plane Metrics Exporter (Wire Existing, Don't Reinvent)

### Tasks
- `services/control_plane_metrics_exporter.py` already exists and exposes Prometheus metrics for:
  - recon/parity/portfolio-risk freshness and status
  - event-store integrity freshness
- Wire it into compose (service under `external` profile).
- Add Prometheus scrape config and Grafana panels for control-plane health.
- This directly replaces what was planned in Day 22 — don't rebuild what's already there.

### Deliverables
- Compose service: `control-plane-metrics-exporter`.
- Prometheus scrape target added.
- Grafana dashboard: control-plane freshness + status panels per service.

### Done Criteria
- Grafana shows recon/parity/portfolio-risk/event-store freshness in real-time without operator file browsing.

---

## Day 34 - Daily Ops Report + Artifact Retention (Automate What Already Exists)

### Tasks
- `scripts/release/generate_daily_ops_report.py` and `scripts/release/run_artifact_retention.py` both exist but are not automated or scheduled.
- Wire daily ops report into the stack (compose scheduled task or on-demand CI step):
  - runs once per day, writes `reports/ops/daily_YYYYMMDD.md`
- Wire artifact retention to run on a schedule:
  - define retention windows per report type (event_store JSONL, parity, recon, gate runs)
  - fail-safe: never delete audit trail without explicit override

### Deliverables
- Compose service or scheduled entrypoint for daily ops report + retention.
- `docs/ops/artifact_retention_policy.md` updated with enforced retention rules and schedule.
- First automated daily ops report artifact in `reports/ops/`.

### Done Criteria
- Daily summary report is produced without manual intervention.
- Old artifacts are cleaned up automatically without touching audit evidence.

---

## Day 35 - HB Version Upgrade Path + Market Data Freshness Gate

### Tasks
- Define and document the **HB version upgrade procedure**:
  - what could break (connector/controller/executor API changes between versions)
  - how to test safely before promoting (testnet + paper smoke + full gate run)
  - rollback to previous pinned image if gates fail
- Add a **market data freshness gate**:
  - detect when the bot's candle/price feed is stale (no new mid-price within N seconds)
  - surface this in monitoring and optionally trigger soft_pause

### Deliverables
- `docs/ops/hb_version_upgrade_runbook.md` (step-by-step + gate requirements + rollback).
- Market data freshness metric added to bot-metrics-exporter (freshness gauge + alert).

### Done Criteria
- An HB version bump can be safely tested and rolled out without an ad-hoc manual process.
- Stale market data is visible in Grafana and alerts before it causes silent strategy degradation.

---

## Mandatory Operating Rules

- Never change strategy logic and infrastructure in the same cycle unless explicitly required.
- If reconciliation or parity is red, prioritize safety actions before optimization.
- Every deployment must have a tested rollback path.
- Keep all additions free/open-source-first.

## Daily AI Agent Reporting Template

Use this exact output structure each day:
1. What was changed
2. Files/services touched
3. Validation performed
4. Metrics before/after
5. Incidents/risks found
6. Rollback status
7. Next day plan (max 3 bullets)

---

## Day 36 - Full Accounting Layer v2 (Fees + Funding + Realized PnL Attribution)

### Tasks
- Replace the current "equity_quote delta as PnL proxy" with a proper trade-level accounting model:
  - realized PnL per fill (price move contribution only, fees stripped out)
  - fees paid (per asset, per venue, per bot, daily and cumulative)
  - funding/borrow cost (for perps/margin positions)
  - unrealized mark-to-market exposure
- Write this into Postgres (extend `fills` and `bot_daily` schema or add `accounting_ledger` table).
- Expose accounting metrics in Grafana: fee drag, funding cost, net realized PnL, daily attribution breakdown.

### Deliverables
- `docs/validation/accounting_contract_v2.md` (PnL attribution model, field definitions, assumptions).
- Extended Postgres schema + ops-db-writer update.
- Grafana panels: fee drag per bot, funding cost trend, attributed PnL waterfall.

### Done Criteria
- You can answer "how much did fees and funding cost me today vs price-move PnL?" from Grafana in <1 minute.
- Accounting output matches fills.csv within acceptable rounding tolerance.

---

## Day 37 - Formal CI Pipeline (Beyond Local Gate Runner)

### Tasks
- Promote the local gate runner into a **formal CI pipeline** that runs automatically:
  - on every code change (PR or push to main)
  - includes: tests + lint + regression replay + promotion gate PASS/FAIL
- Use a self-hosted OSS CI (e.g., **Gitea Actions**, **Woodpecker CI**, **act** on local runner) to avoid external SaaS dependency.
- Gate runner output (JSON + markdown) is archived per run and referenced in release manifest.

### Deliverables
- CI pipeline config (`.gitea/workflows/` or equivalent) that runs tests + gates automatically.
- CI run artifact archived with evidence paths.
- Promotion manifest updated to include CI run reference.

### Done Criteria
- Every push produces a deterministic PASS/FAIL CI result without operator intervention.
- A failing test, lint, or gate run blocks the release automatically.

---

## Day 38 - Deterministic Replay Regression (First-Class Gate, Two-Run Stability)

### Tasks
- Complete the replay regression harness so it is a **stable, first-class gate input**:
  - two consecutive runs on the same dataset yield identical PASS/FAIL and metrics within tolerance
  - harness is wired to CI (Day 37) and promotion gates (Day 17/Day 6)
- Expand the replay dataset to cover at least:
  - one "normal market" window
  - one "high-vol / shock" window
  - one "no-trade variant" window (must verify zero live orders)
- Produce versioned regression artifacts (dataset ID + config hash + result).

### Deliverables
- Regression artifacts: per-window JSON result + markdown summary per CI run.
- Gate runner updated: promotion requires regression PASS on all windows.
- `docs/validation/backtest_regression_spec.md` updated with multi-window coverage.

### Done Criteria
- Any controller/strategy/risk code change that regresses behavior is caught automatically before promotion.
- Regression output is deterministic: same input → same output on any machine.

---

## Day 39 - ML Signal Governance (Baseline, Drift, Retirement)

### Tasks
- Establish a **formal ML signal governance policy**:
  - baseline comparison: ML signal path must outperform or match the non-ML signal on a defined metric set before being enabled in production
  - model drift detection: track prediction confidence distribution over time; alert when it degrades
  - model retirement: define what triggers a model to be disabled (confidence below threshold for N windows)
- Add model metadata to the audit trail (model version + confidence + feature hash per signal).
- Ensure coordination service is gated: only runs if ML is explicitly enabled AND model freshness passes.

### Deliverables
- `docs/ops/ml_signal_governance_v1.md` (baseline policy, drift alert thresholds, retirement criteria).
- Model freshness check added to promotion gates (fail if model stale/confidence degraded).
- Grafana panels: confidence distribution over time, model version active, signal approval rate.

### Done Criteria
- You cannot accidentally run a stale or unvalidated ML model in production without a gate failing.
- ML signal is provably better than (or equal to) baseline signal before enabling in live scope.

---

## Day 40 - ClickHouse Event Analytics (When Postgres Is No Longer Enough)

### Tasks
- Deploy **ClickHouse** (OSS, compose-friendly) as an analytics-optimized store alongside Postgres:
  - Postgres remains the operational store (blotter, wallet snapshots, gate history, accounting)
  - ClickHouse handles: high-volume event replay/analytics, signal/risk decision history, large JSONL ingestion
- Build a lightweight ingestor from `reports/event_store/events_YYYYMMDD.jsonl` → ClickHouse.
- Add Grafana ClickHouse datasource for event-level analytics (e.g., signal distribution, risk veto rates, fill latency histograms).

### Deliverables
- Compose service: `clickhouse` + persistent volume + retention config.
- `services/event_analytics_writer/` — ingestor from JSONL event store to ClickHouse.
- Grafana dashboard: event analytics (signal counts, risk veto rate, fill distribution).
- `docs/ops/analytics_store_policy_v1.md` (what goes in Postgres vs ClickHouse, retention rules).

### Done Criteria
- Event-level analytics queries run in <1 second on a full day's event JSONL.
- Postgres and ClickHouse coexist cleanly; each owns its data domain without overlap.

---

## Day 41 - Generic Backtest Harness v1 (Strategy-Agnostic Core)

### Design Principle
The backtest system must work for **all current and future strategies** on this desk (market making, directional, grid, ML-signal-driven, arbitrage). It achieves this through a clean separation: a **generic simulation core** + **thin strategy adapters** (one per strategy type). Adding a future strategy = implement one method. All fill simulation, portfolio tracking, PnL accounting, and reporting are inherited for free.

### Architecture
```
BacktestHarness
├── MarketDataProvider (pluggable interface)
│   ├── EventStoreProvider   ← primary: market_snapshot events (10s, correct resolution)
│   └── OHLCVProvider        ← secondary: CCXT candles with mandatory local cache + bias doc
│
├── StrategyAdapter (one thin adapter per strategy, implements one method)
│   └── process_bar(bar: BarData, state: BacktestState) → List[OrderIntent]
│
├── FillSimulator (generic, reuses paper_engine.py Layer 1 only)
│   ├── LimitFillModel: synthetic bid/ask from mid ± ATR-based spread (not bar.low/high)
│   └── ConservativeFillModel: fill only if price moved past level by ≥ 1 ATR tick
│
├── PortfolioTracker (generic, strategy-agnostic)
│   ├── multi-asset ledger (base + quote per bot)
│   ├── fee tracker (loaded from config/fee_profiles.json)
│   └── PnL + peak equity + drawdown accounting
│
└── ReportWriter (generic, same schema for all strategies)
    ├── summary.json (run_id, strategy_name, config_hash, data_source, fill_bias, metrics)
    └── bars.jsonl   (bar-by-bar state — works for any strategy output)
```

### Data Source Policy (from challenge review)
- **Primary**: event store `market_snapshot` events (10-second resolution, already captured, deterministic, `adverse_drift_30s` works correctly, no API dependency).
- **Secondary**: CCXT OHLCV with **mandatory local cache** per `(venue, pair, start, end)`. Cached file is pinned by content hash in `summary.json`. OHLCV outputs carry `fill_model_bias=optimistic_estimated` in report.
- **Fill model for OHLCV**: synthetic `bid=mid*(1 - atr_spread/2)`, `ask=mid*(1 + atr_spread/2)` — never `bar.low/bar.high` (look-ahead bias).

### OrderIntent Contract (re-use existing event schema)
```python
@dataclass
class OrderIntent:
    side: str          # "buy" | "sell"
    price: Decimal     # limit price
    amount: Decimal    # base quantity
    order_type: str    # "limit_maker" | "limit" | "market"
    level_id: str      # e.g. "buy_0", "sell_1" — for multi-level strategies
    expires_at_ms: int # intent expiry (enforce existing contract)
```

### Tasks
- Implement `scripts/backtest/harness/`:
  - `data_provider.py` (abstract `MarketDataProvider` + `EventStoreProvider` + `OHLCVProvider` with local cache)
  - `strategy_adapter.py` (abstract `StrategyAdapter` with `process_bar()`)
  - `fill_simulator.py` (generic `FillSimulator`, reuses `paper_engine.py` Layer 1)
  - `portfolio_tracker.py` (generic ledger + fee + PnL + drawdown)
  - `report_writer.py` (generic `summary.json` + `bars.jsonl`)
  - `runner.py` (`BacktestRunner` that wires all components)
- Implement `scripts/backtest/adapters/epp_v24_adapter.py` (first strategy adapter — thin wrapper around EPP pure logic).
- Implement `scripts/backtest/run_backtest.py` (CLI: `--strategy`, `--data-source`, `--venue`, `--pair`, `--start`, `--end`, `--config`).

### Deliverables
- `scripts/backtest/harness/` (6 modules, strategy-agnostic)
- `scripts/backtest/adapters/epp_v24_adapter.py`
- `scripts/backtest/run_backtest.py`
- `docs/validation/backtest_harness_spec.md` (architecture, adapter contract, data source policy, fill bias rules)
- First backtest run artifact in `reports/backtest/runs/<run_id>/`

### Done Criteria
- Two runs on identical event store inputs produce byte-identical `summary.json`.
- Adding a new strategy adapter requires **only** implementing `process_bar()` — no changes to harness code.
- `paper_engine.py` is not modified; live paper trading is unaffected.
- OHLCV-sourced runs are clearly labeled `fill_model_bias=optimistic_estimated`.

---

## Day 42 - Backtest Postgres Schema + Writer (Strategy-Agnostic, All Runs Queryable)

### Design Principle
The Postgres schema must accommodate **any strategy** run through the generic harness, not just EPP. The `strategy_name` and `config_hash` fields act as the differentiator. Common bar-level fields (equity, drawdown, fills) are strategy-agnostic; strategy-specific state is stored as `jsonb`.

### Tasks
- Extend Postgres (Day 25) with generic backtest tables:
  - `backtest_run`: run_id, ts_utc, strategy_name, venue, pair, start_dt, end_dt, config_hash, fee_profile, data_source, fill_model_bias, status + summary metrics (total_pnl, sharpe_proxy, max_drawdown_pct, fill_count, total_fees)
  - `backtest_bar`: run_id, bar_ts, mid_price, equity, base_pct, drawdown_pct, fill_count, fee_quote, strategy_state jsonb (regime/spread/edge for EPP; signal_value for directional; etc.)
  - `backtest_fill`: run_id, fill_ts, side, price, amount, fee_quote, level_id
  - `backtest_regime_stats`: run_id, regime_label, bar_count, fill_count, total_pnl, avg_spread — populated only for strategies that emit regime labels (null-safe for others)
- Implement `scripts/backtest/write_backtest_to_db.py` (idempotent upsert by run_id, consumes `bars.jsonl` + `summary.json`).
- Wire into `run_backtest.py` via `--write-db` flag (Postgres is optional, not required).

### Deliverables
- Postgres migration for 4 backtest tables.
- `scripts/backtest/write_backtest_to_db.py`
- At least one EPP run imported, one future-stub run confirming schema works for a second strategy type.

### Done Criteria
- `backtest_run` table shows strategy_name and config_hash per run.
- `backtest_bar.strategy_state` jsonb stores EPP-specific fields without schema change.
- A hypothetical directional strategy run could be stored with `regime_label=null` without breaking queries.

---

## Day 43 - Backtest Analytics Dashboard (TradingView-Inspired, Grafana + Postgres)

### Design Principle
Grafana handles **analytics panels** (stats, heatmap, tables, curves). A separate lightweight viewer handles the **TradingView-style interactive chart** (candlesticks + fill markers + regime bands). Both read from the same Postgres backtest tables.

### Context: why two viewers
Grafana cannot render a TradingView-style candlestick chart with interactive fill marker overlays. We use **`lightweight-charts`** (TradingView's own open-source charting library, MIT licensed) for the chart view, and Grafana for all analytics panels.

### Tasks
**Part A — Grafana analytics dashboard** (`hbot-backtest-review`):
- **Run selector**: dropdown (strategy_name + run_id + venue/pair/dates + data_source label + fill_bias)
- **Performance summary stats** (TradingView-inspired, market-making adapted):
  - Net Profit (total PnL)
  - Gross Profit (spread capture) / Gross Loss (fees + adverse selection)
  - Max Drawdown %
  - Sharpe Ratio proxy (`daily_returns / std * sqrt(365)`)
  - Profit Factor (`gross_spread_capture / total_costs`)
  - Fill Rate (`filled_intents / actionable_intents` — market making win rate equivalent)
  - Avg spread capture per fill
  - Total fees paid / Total turnover
- **Equity curve** (running cumulative PnL)
- **Drawdown curve** (underwater equity, peak-to-trough)
- **Monthly returns heatmap** (calendar grid: green=profit, red=loss per month/year)
- **Daily session table** (date / PnL / fills / turnover / regime distribution / fee drag)
- **Regime performance breakdown** (conditional: shown only if `regime_label IS NOT NULL`)
- **Run comparison** (two-run equity curve overlay for parameter sensitivity)
- **Fill model bias warning banner** (visible when `fill_model_bias=optimistic_estimated`)

**Part B — lightweight-charts viewer** (TradingView-style, local HTML + JS):
- Served as a static HTML file from `scripts/backtest/viewer/backtest_chart.html`
- Reads from Postgres via a thin local API endpoint (`scripts/backtest/viewer/serve.py`)
- Panels:
  - **Candlestick chart** with fill markers (▲ buy=green, ▽ sell=red)
  - **Regime-colored background bands** (neutral=blue, up=green, down=red, high_vol=orange)
  - **Spread + spread_floor + net_edge** as overlay line series on chart
  - **Equity curve** as second pane below the chart
  - **Hover tooltip** showing regime / spread / edge / fill detail at each bar
- Run selector: URL param `?run_id=<id>` or dropdown fetched from API

### Deliverables
- `monitoring/grafana/dashboards/backtest_review.json` (Grafana analytics)
- `scripts/backtest/viewer/backtest_chart.html` (lightweight-charts chart view)
- `scripts/backtest/viewer/serve.py` (thin local API: candles + fills + bars from Postgres)
- Backtest summary row added to `control_plane_health.json` (latest N runs: strategy/PnL/drawdown).

### Done Criteria
- Performance summary stats display Net Profit, Drawdown, Sharpe, Profit Factor, Fill Rate for any run.
- Monthly returns heatmap renders correctly for a multi-month backtest.
- lightweight-charts viewer shows candlestick + fill markers + regime bands in browser (no Grafana needed for chart view).
- A future directional strategy run renders correctly: equity curve + fills + stats visible; regime panel absent.
- OHLCV-sourced runs show fill bias warning prominently.

---

## Day 44 - Paper Engine Hardening v1 (Fix Universal Auto-Install + 6 Structural Issues)

### Context
The paper trading challenge revealed a **critical architectural gap** and 6 structural bugs. The architectural gap is the highest priority: the custom paper engine is **never installed** in the current production path, making all paper engine config fields (`internal_paper_enabled`, `paper_seed`, `paper_latency_ms`, `paper_queue_participation`, etc.) cosmetic with zero effect.

### Issue 0 (Architecture — Critical) — Paper adapter is never installed; paper engine is dead code
- **Root cause**: `install_paper_adapter()` is defined in `paper_engine.py` but **never called** from `scripts/shared/v2_with_controllers.py` (the shared script used by all bots). The `internal_paper_enabled` config field exists in `EppV24Config` but nothing reads it and triggers installation. The connector stays as HB's raw `PaperTradeExchange` wrapper. As a result, `paper_fill_count`, `paper_reject_count`, and `paper_avg_queue_delay_ms` in `minute.csv` are always 0 — `connector.paper_stats` never exists because `PaperExecutionAdapter` is never installed.
- **Fix**: Add a **universal auto-installation hook** in `v2_with_controllers.py`:
  - After `apply_initial_setting()`, iterate controllers.
  - For each controller where `connector_name.endswith("_paper_trade")` AND `getattr(config, "internal_paper_enabled", False)` is True:
    - Call `enable_framework_paper_compat_fallbacks()` once per process.
    - Call `install_paper_adapter(controller, connector_name, trading_pair, cfg)`.
  - This is **universal**: works for every current and future strategy that uses the shared script with no per-strategy code required.
- **Config-driven activation**: `internal_paper_enabled: true` in any controller YAML enables the adapter for that controller automatically. `internal_paper_enabled: false` (or absent) leaves it disabled (live connectors are unaffected).

### Issue 1 (Critical) — Bot3 capital too small; edge gate kills trading before first fill
- **Root cause**: `total_amount_quote=10` USDT is so small that the computed spread floor immediately exceeds the available edge, tripping the edge gate before any order fills. Bot3 CSV shows 3 rows, 0 fills, immediate `soft_pause`.
- **Fix**: Set bot3 paper smoke `total_amount_quote=500`, `min_net_edge_bps=0` (no edge gate for paper smoke), `require_fee_resolution=false`. Paper smoke validates **structural behavior** (preflight, orders placed, fills cycle), not edge profitability.
- **New config**: `epp_v2_4_bot3_paper_smoke.yml` updated; document that paper smoke ≠ live profitability gate.

### Issue 2 (Critical) — Paper smoke gate passes without fill evidence
- **Root cause**: current gate checks `account_probe_status=paper_only` (exchange snapshot) — connector health only. Zero fills still passes.
- **Fix**: Add `paper_fill_count_min` check to paper smoke validator. Paper smoke PASS requires `paper_fill_count > 0` within the observation window. Wire into `run_promotion_gates.py`.

### Issue 3 (Medium) — No time-gating between consecutive partial fills
- **Root cause**: `refresh_open_orders()` fires on every `_submit_order()` call with no elapsed-time check. Same order can receive multiple partial fills within the same second.
- **Fix**: Add `_last_fill_ts: Dict[str, float]` to `PaperExecutionAdapter`. Enforce minimum `latency_ms` elapsed before applying another partial fill to the same order. This prevents unrealistically fast fill completion.

### Issue 4 (Medium) — `paper_seed=7` declared but never used
- **Root cause**: `PaperEngineConfig.seed` field exists in controller config but is never passed to any RNG. The fill model is fully deterministic regardless of seed value.
- **Fix**: Add seeded `random.Random` instance to `DepthFillModel`. Use it to randomize `queue_factor` ± 20% around `queue_participation` and randomize `partial_fill_ratio` within `[min, max]`. Seed is set once at construction. This adds realistic fill variance while keeping runs reproducible with the same seed.

### Issue 5 (Medium) — Adverse selection model wrong (only on taker crosses; misses post-fill drift)
- **Root cause**: `adverse_selection_bps` is applied as price slippage only when `is_cross=True` (taker fill). EPP places limit maker orders that almost never cross — so `adverse_selection_bps` is effectively never applied. Real adverse selection is post-fill mark-to-market drift.
- **Fix**: Add a `post_fill_drift_window_ms` parameter (default 500ms). After each fill, sample the market mid price `post_fill_drift_window_ms` later and apply the actual mid drift as an unrealized mark-to-market cost. Track this as `paper_adverse_pnl_quote` in stats.

### Issue 6 (Low) — Spot paper (`bitget_paper_trade`) does not validate perpetual behavior
- **Root cause**: Primary production target is `bitget_perpetual` (perps), but paper smoke uses `bitget_paper_trade` (spot). Funding, leverage, and position modes are not validated.
- **Fix**: Document explicitly that bot3 paper smoke validates **connector wiring and strategy logic only** (not perp semantics). Bot4 `binance_perpetual_testnet` is the **perp validation path** — make it a required gate input for any perp deployment.

### Deliverables
- Updated `controllers/paper_engine.py` (time-gating, seeded RNG, post-fill drift model) — Layer 1 only, no HB integration changes.
- Updated bot3 paper smoke config (`data/bot3/conf/controllers/epp_v2_4_bot3_paper_smoke.yml`).
- Updated `scripts/release/run_promotion_gates.py` (paper fill count gate).
- `docs/validation/paper_engine_hardening_v1.md` (what changed, assumptions, known remaining gaps).

### Done Criteria
- Bot3 paper smoke produces `paper_fill_count > 0` within a 10-minute window.
- Same seed produces same fill sequence; different seeds produce different fill sequences.
- A taker cross fill no longer fully fills in a single cycle.
- Promotion gate fails if `paper_fill_count == 0` after the smoke window.

---

## Day 45 - Paper Trading as Formal Desk Gate (KPI Contract + Soak Evidence + Perp Path)

### Context
Even after hardening (Day 44), paper trading needs to become a **formal, evidence-based gate** — not just a "connector is ready" check. A semi-pro desk treats paper soak as the mandatory last line of defense before any capital deployment.

### Tasks
**Part A — Automated Paper KPI Validator**
Based on the existing runbook KPIs (`docs/ops/runbooks.md` "EPP Paper Validation Checklist"), build `scripts/release/validate_paper_soak.py`:
- Reads `minute.csv` from a paper bot over a specified time window
- Checks all 7 KPIs:
  - `% running >= 65%` (not stuck in soft_pause)
  - `turnover_today_x <= 3.0`
  - `daily_loss_pct < 1.5%`
  - `drawdown_pct < 2.5%`
  - `cancel_per_min < cancel_budget_per_min for >95% of samples`
  - `paper_fill_count > 0` (fills occurred)
  - `paper_reject_count near zero after warmup period`
- Produces `reports/paper_soak/latest.json` (PASS/FAIL + per-KPI breakdown + evidence)

**Part B — Minimum Soak Duration Gate**
- Paper smoke (short, 10-minute): validates wiring, preflight, first fills — already in gates.
- Paper soak (new, minimum 2-hour): required before any live capital promotion. Validator reads the last 2h of `minute.csv` evidence.
- Wire both into promotion gates: smoke = required for all promotions; soak = required for live capital changes.

**Part C — Paper Parity Check**
- Compare realized `paper_fill_count / paper_avg_queue_delay_ms` against internal model expectations:
  - Expected fill rate = `queue_participation * (fills_possible_at_spread_level)` over the window
  - Flag as `WARNING` if realized fill rate diverges > 50% from expected
- Helps detect when paper simulation assumptions are out of calibration vs live market conditions.

**Part D — Perp Paper Path Formalization**
- Document bot4 `binance_perpetual_testnet` as the **mandatory perp smoke gate**:
  - Required for any controller change that targets a perpetual connector
  - Pass criteria: preflight pass + connector ready + no recurring startup loop + orders active within 5 minutes
- Add `perp_smoke_matrix` gate to `run_promotion_gates.py` (separate from spot paper smoke)

### Deliverables
- `scripts/release/validate_paper_soak.py` (automated KPI validator)
- `reports/paper_soak/latest.json` (PASS/FAIL + per-KPI evidence)
- Updated `run_promotion_gates.py` (paper soak gate + perp smoke gate)
- Updated `docs/validation/validation_plan.md` (paper smoke vs soak vs perp path defined)
- `docs/validation/paper_kpi_contract_v1.md` (KPI definitions, thresholds, update process)

### Done Criteria
- Paper soak PASS requires all 7 KPIs green over a 2h window.
- Promotion to any live perpetual connector requires bot4 perp smoke PASS.
- Paper parity check runs automatically and flags calibration drift.
- A paper soak FAIL blocks promotion with a per-KPI breakdown in the gate output.

---

## Day 46 - Controller Decomposition: Break Up the God Class

### Context (Audit Finding — HIGH)
`EppV24Controller` is 1164 lines mixing 10+ responsibilities: regime detection, spread computation, risk policy, fee resolution, CSV logging, edge gating, external intent handling, inventory skew, order sizing, and order book reads. This makes it untestable in isolation and high-risk for any change.

### Tasks
- Extract focused, independently testable modules from `EppV24Controller`:
  - `RegimeDetector` — owns `_detect_regime()`, `_price_buffer`, regime specs (PHASE0_SPECS)
  - `SpreadEngine` — owns `_pick_spread_pct()`, `_build_side_spreads()`, `_spread_floor_pct` computation, `_pick_levels()`
  - `RiskPolicy` — owns `_risk_policy_checks()`, `_risk_loss_metrics()`, `_edge_gate_update()`
  - `FeeManager` — owns `_ensure_fee_config()` and all fee state (`_maker_fee_pct`, `_taker_fee_pct`, `_fee_source`, etc.)
  - `OrderSizer` — owns `_apply_runtime_spreads_and_sizing()`, `_quantize_price()`, `_quantize_amount()`, `_project_total_amount_quote()`
- Each module must be a standalone class with explicit inputs and outputs (no implicit state reads from the controller).
- The controller becomes a thin orchestrator (~200 lines) that wires modules together in `update_processed_data()`.
- Each extracted module gets its own unit test file.

### Deliverables
- `controllers/regime_detector.py`
- `controllers/spread_engine.py`
- `controllers/risk_policy.py`
- `controllers/fee_manager.py`
- `controllers/order_sizer.py`
- `controllers/epp_v2_4.py` (slimmed to orchestrator)
- `tests/controllers/test_regime_detector.py`
- `tests/controllers/test_spread_engine.py`
- `tests/controllers/test_risk_policy.py`
- `tests/controllers/test_fee_manager.py`
- `tests/controllers/test_order_sizer.py`

### Done Criteria
- `EppV24Controller` is under 300 lines.
- Each extracted module has ≥80% branch coverage.
- All existing tests still pass.
- No behavioral change: minute.csv output is identical before and after decomposition for same inputs.

---

## Day 47 - Controller Unit Tests (Core Strategy Coverage)

### Context (Audit Finding — HIGH)
The highest-criticality module (`EppV24Controller`) has zero tests. Only the paper engine has unit tests. This is unacceptable for live capital.

### Tasks
- Write comprehensive unit tests for the controller (or its Day 46 decomposed modules) with a mock `ConnectorRuntimeAdapter`:
  - Regime detection: each regime triggers correct spread range and level count
  - Edge gate: blocks at threshold, resumes at resume threshold, respects hold timer
  - Risk limits: daily loss, drawdown, and turnover hard limits trigger HARD_STOP
  - Fee resolution cascade: auto → project → manual fallback
  - Day rollover: resets counters (traded_notional, fills_count, equity_open)
  - Inventory skew: correct direction and capping
  - Spread floor: computed from costs + min edge + vol penalty
  - No-trade / disabled variants: produce zero orders
  - External intent: soft_pause, resume, kill_switch, set_target_base_pct
- Add property-based tests (hypothesis) for spread/skew math:
  - Spread is always ≥ spread_floor
  - Buy spread + sell spread always sums to approximately total spread
  - Skew is always within `[-skew_cap, +skew_cap]`
  - Net edge computation is monotonically increasing with spread

### Deliverables
- `tests/controllers/test_epp_v2_4.py` (or per-module test files from Day 46)
- Coverage report showing ≥80% line coverage on controller logic
- Property-based test file using `hypothesis`

### Done Criteria
- All regime/edge/risk/fee paths have at least one test.
- Property-based tests run and pass with 200+ examples each.
- Controller test failure blocks promotion (wired into gate).

---

## Day 48 - Eliminate Monkey-Patches (Clean Adapter Pattern)

### Context (Audit Finding — HIGH)
5 monkey-patches are applied at module import time to Hummingbot internals: `ExecutorBase.get_trading_rules`, `ExecutorBase.get_in_flight_order`, `MarketDataProvider._create_non_trading_connector`, `start_trade_monitor`, and `ConnectorManager.update_connector_balances`. These make HB upgrades extremely dangerous and are impossible to test without a full runtime.

### Tasks
- Replace each monkey-patch with a clean adapter/wrapper:
  - `get_trading_rules` patch → `PaperExecutionAdapter` should expose `trading_rules` dict natively; remove global patch
  - `get_in_flight_order` patch → `PaperExecutionAdapter` should expose `_order_tracker` as a proper attribute
  - `_create_non_trading_connector` patch → Add a pre-check in `v2_with_controllers.py` that strips `_paper_trade` suffix before calling the original method
  - `start_trade_monitor` patch → Add a try/except wrapper at the call site in `v2_with_controllers.py`, not a global patch
  - `update_connector_balances` patch → Add connector alias mapping at strategy init, not a global patch
- Document which HB version (2.12.0) these workarounds target.
- Create a **compatibility matrix** file listing each workaround, its purpose, and the HB version range it applies to.

### Deliverables
- Updated `controllers/paper_engine.py` (no global patches)
- Updated `scripts/shared/v2_with_controllers.py` (no global patches)
- `docs/dev/hb_compatibility_matrix.md` (workaround catalog + version range)

### Done Criteria
- Zero module-level monkey-patches remain.
- `enable_framework_paper_compat_fallbacks()` is removed or converted to instance-level setup.
- All existing tests pass.
- Paper trading still works with HB 2.12.0.

---

## Day 49 - Dependency Management + Type Checking

### Context (Audit Finding — HIGH / LOW)
No `setup.py`, `pyproject.toml`, or project-level dependency pins exist. The project cannot be reliably reproduced. Additionally, extensive type annotations exist but no type checker is configured.

### Tasks
- Create `pyproject.toml` at `hbot/` level with:
  - Project metadata (name, version, Python requirement ≥3.11)
  - Runtime dependencies (redis, pydantic, ccxt, psycopg, joblib, scikit-learn, requests, boto3)
  - Dev dependencies (pytest, pytest-cov, hypothesis, mypy, ruff)
  - Entry points for services (e.g., `hbot-event-store = services.event_store.main:run`)
- Configure `mypy` with a `mypy.ini` or `[tool.mypy]` section:
  - Strict mode for `controllers/` and `services/contracts/`
  - Gradual mode for `services/` (allow untyped calls initially)
- Configure `ruff` for linting:
  - Enable import sorting, unused imports, basic style checks
- Wire `mypy` and `ruff` into the CI pipeline (`run_ci_pipeline.py`) and promotion gates.

### Deliverables
- `hbot/pyproject.toml`
- `mypy` and `ruff` configuration
- Updated `scripts/release/run_ci_pipeline.py` (adds type-check and lint steps)

### Done Criteria
- `pip install -e .` works from `hbot/` directory.
- `mypy controllers/ services/contracts/` passes with zero errors.
- `ruff check .` passes with zero errors.
- Type-check failure blocks promotion.

---

## Day 50 - Real Kill Switch (Exchange Cancel-All + Position Flatten)

### Context (Audit Finding — HIGH)
`OpsGuard.force_hard_stop()` only prevents new order placement. It does not cancel existing open orders on the exchange or flatten positions. A real kill switch must interact with the exchange.

### Tasks
- Build `services/kill_switch/kill_switch_service.py`:
  - Listens for `kill_switch` intents on Redis Stream
  - On trigger: calls exchange cancel-all-orders API (via ccxt)
  - Optionally: places market orders to flatten positions (configurable, off by default)
  - Sends audit event with full action log
  - Sends webhook/Slack notification
  - Writes `reports/kill_switch/latest.json` with action evidence
  - Requires manual restart to resume trading (no auto-recovery)
- Add kill switch trigger to `v2_with_controllers.py`:
  - When `OpsGuard` enters HARD_STOP, publish `kill_switch` intent to Redis
- Add kill switch dry-run mode for testing.
- Add Prometheus metric: `hbot_kill_switch_triggered_total`.

### Deliverables
- `services/kill_switch/kill_switch_service.py`
- Compose service under `external` profile
- `docs/risk/kill_switch_operations_v1.md` (trigger conditions, behavior, recovery procedure)
- Prometheus alert: `KillSwitchTriggered`

### Done Criteria
- Dry-run kill switch cancels simulated orders and produces audit trail.
- Recovery requires explicit manual action (container restart + config change).
- Kill switch intent is visible in event store and Grafana.

---

## Day 51 - Exchange-Side Fill Reconciliation

### Context (Audit Finding — HIGH)
Reconciliation currently compares local CSV `base_pct` against target. It does not verify that local fills match exchange-reported fills. Phantom or missing fills would go undetected.

### Tasks
- Extend `reconciliation_service` with exchange fill comparison:
  - Fetch recent fills from exchange API (via ccxt `fetch_my_trades()`)
  - Compare against local `fills.csv` by order_id and trade_id
  - Alert on:
    - Missing fills (exchange has fill, local doesn't)
    - Phantom fills (local has fill, exchange doesn't)
    - Price/amount discrepancy beyond tolerance
  - Store comparison report in `reports/reconciliation/fill_reconciliation_latest.json`
- Add `exchange_fill_reconciliation` check to reconciliation findings.
- Add Grafana panel for fill reconciliation status.

### Deliverables
- Extended `services/reconciliation_service/main.py`
- `reports/reconciliation/fill_reconciliation_latest.json`
- Grafana panel: fill reconciliation status + discrepancy count
- Prometheus alert: `FillReconciliationMismatch`

### Done Criteria
- A controlled fill produces matching entries on both sides (exchange API and local CSV).
- A simulated phantom/missing fill triggers the expected alert.

---

## Day 52 - Graceful Shutdown + Signal Handling

### Context (Audit Finding — MEDIUM)
All services use `while True` + `time.sleep()` with no signal handling. Containers cannot drain in-flight work on `SIGTERM`, risking partial writes and data corruption.

### Tasks
- Add signal handling to all service `main.py` files:
  - Register `SIGTERM` and `SIGINT` handlers
  - Set a stop flag that breaks the main loop
  - Drain in-flight Redis reads/writes before exiting
  - Log shutdown reason and duration
- Add graceful shutdown tests:
  - Send `SIGTERM` to running service, verify clean exit within 10 seconds
  - Verify no partial writes in JSONL or CSV files after shutdown

### Deliverables
- Updated `services/*/main.py` (all 10 service mains)
- `services/common/graceful_shutdown.py` (shared signal handler utility)

### Done Criteria
- Every service exits cleanly on `SIGTERM` within 10 seconds.
- No partial/corrupted writes observed after graceful shutdown.
- Docker `stop` (which sends SIGTERM) completes without `SIGKILL` fallback.

---

## Day 53 - CSV → Redis Stream Migration for Bot Telemetry

### Context (Audit Finding — HIGH)
CSV files are the primary data source for 6+ services (metrics exporter, reconciliation, parity, portfolio risk, ops-db-writer, exchange snapshot). This creates file-locking risks, O(n) full-file scans, path coupling, and schema fragility.

### Tasks
- Publish bot telemetry (minute snapshot, fill events, daily rollover) to Redis Streams alongside CSV:
  - New stream: `hb.bot_telemetry.v1` with `minute_snapshot`, `fill`, and `daily_rollover` event types
  - Publisher: extend `v2_with_controllers.py` to publish telemetry events via `HBEventPublisher`
  - Consumers: optionally let services read from Redis instead of CSV (feature flag per service)
- Keep CSV as a secondary export for human inspection and backward compatibility.
- Add retention policy for telemetry stream (configurable `maxlen`).
- Migrate `bot_metrics_exporter` to read from Redis first, CSV fallback.

### Deliverables
- Extended `services/contracts/event_schemas.py` with `BotMinuteSnapshotEvent`, `BotFillEvent`, `BotDailyRolloverEvent`
- Extended `services/contracts/stream_names.py` with `BOT_TELEMETRY_STREAM`
- Updated `scripts/shared/v2_with_controllers.py` (telemetry publisher)
- Updated `services/bot_metrics_exporter.py` (Redis-first, CSV fallback)
- Feature flag: `BOT_TELEMETRY_VIA_REDIS=true/false`

### Done Criteria
- Bot telemetry events appear in Redis stream within 1 second of CSV write.
- Metrics exporter produces identical output from Redis source vs CSV source.
- CSV continues to be written for backward compatibility.

---

## Day 54 - Multi-Exchange Fee Resolver + Rate Limit Handling

### Context (Audit Finding — MEDIUM)
`FeeResolver.from_exchange_api()` only supports Bitget. Adding a second exchange requires code changes. Additionally, there is no exchange rate limit awareness beyond cancel budget tracking.

### Tasks
- Make `FeeResolver` pluggable:
  - Define `ExchangeFeeAdapter` protocol with `fetch_fees(connector, trading_pair) → Optional[FeeRates]`
  - Implement `BitgetFeeAdapter` (extract from current code)
  - Implement `BinanceFeeAdapter` (for testnet/live perpetual)
  - Registry: `FeeResolver.register_adapter(exchange_prefix, adapter)`
  - Auto-dispatch based on `connector_name` prefix
- Add exchange rate limit tracking:
  - `services/common/rate_limiter.py`: per-exchange token bucket
  - Track order placement, cancellation, and balance query rates
  - Back off automatically on 429 responses
  - Share rate limit budget across bots targeting the same exchange
  - Expose `hbot_exchange_rate_limit_remaining` Prometheus gauge

### Deliverables
- `services/common/fee_adapter.py` (protocol + registry + Bitget + Binance adapters)
- `services/common/rate_limiter.py` (token bucket + Prometheus metrics)
- Updated `controllers/epp_v2_4.py` (use pluggable fee resolver)

### Done Criteria
- Fee resolution works for both Bitget and Binance connectors without code changes.
- Rate limiter prevents 429 errors during high-activity periods.
- Adding a third exchange requires only implementing a new adapter class.

---

## Day 55 - Dead Code Cleanup + Helper Consolidation + Settings Fix

### Context (Audit Finding — LOW / MEDIUM)
20+ example/demo scripts in `data/bot{1,2}/scripts/` create clutter. Helper functions (`_safe_float`, `_utc_now`, `_read_json`, etc.) are duplicated across 8+ files. `RedisSettings`/`ServiceSettings` use `os.getenv()` at class definition time, breaking test isolation.

### Code Quality Quick Wins (bundle with Day 55)
These are immediate fixes from the code quality audit that should be bundled:
- Rename `_d()` → `_to_decimal()` across all 4 controller files
- Make `RegimeSpec` frozen: `@dataclass(frozen=True)`
- Add `class ProcessedState(TypedDict)` for the 40-key `processed_data` dict
- Add docstrings to `EppV24Controller`, `PaperExecutionAdapter`, `RegimeSpec`, `EppV24Config`

### Tasks
- **Dead code cleanup:**
  - Audit `data/bot{1,2}/scripts/` — identify which scripts are active vs example/demo
  - Move inactive examples to `docs/examples/` or delete
  - Remove any unused imports or functions identified by `ruff`
- **Helper consolidation:**
  - Create `services/common/utils.py` with canonical implementations:
    - `safe_float()`, `safe_bool()`, `utc_now()`, `today()`, `read_json()`, `write_json()`, `read_last_csv_row()`, `count_csv_rows()`
  - Replace all duplicates across services with imports from `services/common/utils.py`
- **Settings initialization fix:**
  - Replace class-level `os.getenv()` defaults in `RedisSettings` and `ServiceSettings` with `field(default_factory=...)`:
    ```python
    @dataclass
    class RedisSettings:
        host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "redis"))
    ```
  - This allows test code to instantiate settings with overrides without monkeypatching `os.environ`.

### Deliverables
- Updated `services/common/utils.py` (canonical helpers)
- Updated `services/common/models.py` (factory-based defaults)
- Cleaned `data/bot{1,2}/scripts/` (examples moved or removed)
- All service files updated to import from `services/common/utils.py`

### Done Criteria
- Zero duplicate `_safe_float()` / `_utc_now()` / `_read_json()` definitions remain outside `services/common/utils.py`.
- `RedisSettings()` can be instantiated in tests without setting environment variables.
- No unused scripts remain in bot data directories.
- All tests pass after cleanup.

---

## Day 56 - Decimal Precision Fix + Logging Infrastructure (Code Quality Sprint)

### Context (Code Quality Audit — CRITICAL + HIGH)
The code quality audit identified 5 critical defects and 15 high-severity issues that should be resolved as a focused sprint before scaling capital. These are targeted fixes, not architectural changes.

### Tasks — Precision Fixes
- Change `RuntimeLevelState.buy_spreads` and `sell_spreads` from `List[float]` to `List[Decimal]`
- Remove `float(x) for x in buy_spreads` conversions at lines 656-657 of `epp_v2_4.py`
- Fix `Decimal(spreads[int(level)])` at line 734 — already Decimal after the type change
- Audit all `_safe_float()` call sites in services: keep float for Prometheus metrics (required), use Decimal for financial comparisons in reconciliation/parity/risk services
- Add fee extraction fallback in `did_fill_order()`: `fee_quote = notional * self._taker_fee_pct` when primary extraction fails

### Tasks — Logging Infrastructure
- Add `logging.getLogger(__name__)` to all 4 controller files
- Log all caught exceptions at WARNING+ in `epp_v2_4.py` (7 sites), `paper_engine.py` (4 critical sites), `connector_runtime_adapter.py` (2 critical sites), `fee_provider.py` (4 sites)
- Add `_balance_read_failed` flag to `ConnectorRuntimeAdapter`; trigger SOFT_PAUSE when balance reads fail
- Log fill event relay failures in `paper_engine.py` at ERROR level with fill details
- Add `_dropped_relay_count` metric to `PaperExecutionAdapter.paper_stats`

### Tasks — Safety Fixes
- Make `RegimeSpec` frozen: `@dataclass(frozen=True)`
- Extract magic numbers to `EppV24Config`: `ema_period` (50), `atr_period` (14), `trend_skew_factor` (0.8), `neutral_skew_factor` (0.5), `spread_step_multiplier` (0.4), `vol_penalty_multiplier` (0.5)
- Add `variant_mode: Literal["live","paper_only","disabled","no_trade"]` to `EppV24Config` to replace hardcoded variant gating

### Deliverables
- Updated `controllers/epp_v2_4.py` (precision + logging + config extraction)
- Updated `controllers/paper_engine.py` (logging + relay metrics)
- Updated `controllers/connector_runtime_adapter.py` (logging + failure flag)
- Updated `services/common/fee_provider.py` (logging)
- `docs/validation/code_quality_audit_fixes.md` (what changed and why)

### Done Criteria
- `RuntimeLevelState` spreads are `List[Decimal]` — no float conversion in pricing pipeline
- Every `except Exception` in controller files logs at WARNING+ level
- Balance read failure triggers SOFT_PAUSE within one tick cycle
- All magic numbers are configurable via YAML
- `RegimeSpec` is frozen

---

## Day 57 - Structured Logging + Exception Observability

### Context (Code Quality Audit — HIGH)
Only 2 of 113 Python files use `logging.getLogger`. 50+ files use `print()`. Error conditions are invisible in production.

### Tasks
- Standardize logging pattern across all services:
  - Use `logging.getLogger(__name__)` (never `print()`)
  - JSON structured logging for services (machine-parseable)
  - Human-readable for scripts/CLI tools
- Add exception counter metrics:
  - `hbot_exception_total{module, exception_type, severity}` Prometheus counter
  - Exposed via `bot_metrics_exporter.py`
- Add observability to fee resolution:
  - Log which source was tried, which succeeded, which failed
  - Log fee values resolved (maker/taker/source) at INFO level per resolution cycle
- Add observability to order book access:
  - Log when `_get_top_of_book()` returns zeros (distinguish "empty book" from "read failed")
  - Add `_book_read_failed_count` to processed_data

### Deliverables
- `services/common/logging_config.py` (shared logging setup)
- Updated all service `main.py` files (replace `print()` with `logger`)
- Updated controller files (structured logging)
- Exception counter in `bot_metrics_exporter.py`

### Done Criteria
- Zero `print()` calls remain in service code (scripts allowed for CLI output)
- Every exception caught in controller/adapter files is logged
- Fee resolution path is fully traceable from logs
- Exception counter is visible in Grafana

---

## Day 58 - ProcessedState Type Contract + Config Documentation

### Context (Code Quality Audit — MEDIUM)
The `processed_data` dictionary has 40+ untyped keys that are the primary data contract between the controller and every downstream consumer. `EppV24Config` has 40+ fields with minimal documentation.

### Tasks
- Define `ProcessedState` as a `TypedDict` or `@dataclass`:
  - All 40+ keys with explicit types
  - Docstrings for each field (unit, range, meaning)
  - Mark optional fields
  - Validate at assignment time (or via mypy)
- Document `EppV24Config` fields:
  - Add field descriptions via `Field(description=...)` for all parameters
  - Group fields by concern (fee, regime, risk, paper, runtime)
  - Document variant meanings (a=live, b/c=disabled, d=no_trade)
  - Document dangerous defaults and their rationale
- Publish `docs/dev/epp_v2_4_config_reference.md` auto-generated from Pydantic schema

### Deliverables
- `controllers/types.py` (`ProcessedState` TypedDict)
- Updated `controllers/epp_v2_4.py` (use `ProcessedState` type)
- `docs/dev/epp_v2_4_config_reference.md`
- Updated `EppV24Config` field descriptions

### Done Criteria
- `mypy` catches type errors when accessing `processed_data` keys
- Every `EppV24Config` field has a human-readable description
- Config reference doc is generated from code (not hand-maintained)

---

## Day 59 - Performance Quick Wins (Tick-Loop Hot Path)

### Context (Performance Audit)
The tick loop contains 30+ `Decimal("...")` string-to-Decimal allocations, 7 redundant `get_connector()` reflection chains, 2 redundant `band_pct()` O(2880) recomputations, a blocking Redis `ping()`, and repeated `trading_pair.split("-")` calls.  These add 3-16ms of avoidable overhead per tick.

### Tasks
- **Cache Decimal constants** as module-level variables in `epp_v2_4.py`, `price_buffer.py`, `paper_engine.py`:
  - `_ZERO = Decimal("0")`, `_ONE = Decimal("1")`, `_TWO = Decimal("2")`, `_10K = Decimal("10000")`, `_100 = Decimal("100")`, etc.
  - Replace all `Decimal("0")` call-site constructions with cached constants
- **Cache `get_connector()` per tick**: call once at the top of `update_processed_data()`, pass result to all sub-methods via parameter
- **Cache `band_pct()` result**: store in a local variable at line ~307, reuse at line ~324 instead of recomputing
- **Cache `trading_pair.split("-")`**: compute `_base_asset` / `_quote_asset` once in `ConnectorRuntimeAdapter.__init__` or `EppV24Controller.__init__`
- **Throttle Redis ping**: replace per-tick `_bus_client.ping()` with check every 30 ticks or use last-xadd success as health signal
- **Amortize dedup cleanup**: move `_cleanup_seen()` in `intent_consumer.py` to once per poll batch, not per event
- **Cap `_order_tracker._orders`**: prune `FILLED`/`CANCELED`/`FAILED` orders older than 60 seconds

### Deliverables
- Updated `controllers/epp_v2_4.py` (Decimal constants, connector caching, band_pct caching)
- Updated `controllers/price_buffer.py` (Decimal constants)
- Updated `controllers/paper_engine.py` (Decimal constants, order tracker pruning)
- Updated `controllers/connector_runtime_adapter.py` (asset caching)
- Updated `scripts/shared/v2_with_controllers.py` (ping throttling)
- Updated `services/hb_bridge/intent_consumer.py` (amortized cleanup)

### Done Criteria
- Zero `Decimal("0")` or `Decimal("1")` constructions inside functions called per-tick
- `get_connector()` called exactly once per tick cycle
- `band_pct()` called exactly once per tick cycle
- Redis ping at most once every 30 ticks
- `_order_tracker._orders` size stays bounded

---

## Day 60 - Running Indicators (O(1) EMA/ATR)

### Context (Performance Audit — CRITICAL)
`price_buffer.ema()` iterates up to 2880 bars from scratch every tick.  `atr()` copies the entire deque and iterates it, and is called twice per tick.  Total: ~11,520 Decimal operations per tick from indicators alone.

### Tasks
- **Running EMA**: maintain `_ema_value: Optional[Decimal]` on `MidPriceBuffer`, update incrementally in `add_sample()` using `alpha * close + (1 - alpha) * ema_prev`.  `ema()` becomes a simple property returning the cached value.
- **Running ATR**: maintain `_atr_value: Optional[Decimal]` with Wilder's smoothing method.  Update in `add_sample()` when a new minute bar completes.  `atr()` returns the cached value.
- **Cache `band_pct`**: since ATR and latest close are now cached, `band_pct()` is O(1).
- **Keep `ema()` and `atr()` methods** for backward compatibility, but they now return the cached running value.
- **Add tests**: verify running values match the from-scratch computation within Decimal precision tolerance.

### Deliverables
- Updated `controllers/price_buffer.py` (running EMA + ATR)
- `tests/controllers/test_price_buffer.py` — verify equivalence with brute-force computation

### Done Criteria
- `ema()` and `atr()` are O(1) per call
- Running values match from-scratch computation to 12 decimal places
- No regression in existing `test_regime_detector.py` or `test_spread_engine.py`

---

## Day 61 - Buffered CSV Writer + Async I/O

### Context (Performance Audit — CRITICAL)
`epp_logging.py` opens, reads header, stats, writes, and closes the CSV file on every single log call.  Fill events trigger sync I/O on the event handler hot path.

### Tasks
- **Buffered writer**: keep file handles open and write through a buffer that flushes every N rows or every T seconds (configurable, default: 10 rows or 5 seconds).
- **Schema rotation**: check header only on first write after buffer open, not on every append.
- **Async option**: optionally use a background thread with `queue.Queue` to decouple CSV writes from the tick loop entirely.
- **Graceful flush on shutdown**: ensure buffer is flushed when `ShutdownHandler.requested` becomes True.
- **Metric**: emit `hbot_csv_write_duration_seconds` histogram via processed_data.

### Deliverables
- Updated `controllers/epp_logging.py` (buffered writer)
- Configuration: `csv_buffer_size: int = 10`, `csv_flush_interval_s: int = 5`

### Done Criteria
- File open/close happens at most once per flush interval, not per row
- Fill event handler does not block on filesystem I/O
- No data loss on graceful shutdown

---

## Day 62 - Service Loop Performance (Reconciliation + Metrics Scrape)

### Context (Performance Audit — HIGH)
`_count_event_fills()` in reconciliation service scans the entire daily JSONL file (~864K lines after 24h).  `_read_last_csv_row()` iterates from row 0 to EOF.  `bot_metrics_exporter` loads entire log files into memory via `readlines()`.

### Tasks
- **Indexed event fill count**: maintain a running counter per bot in a lightweight sidecar file (e.g., `reports/event_store/fill_counts.json`) updated by the event store service.  Reconciliation reads the counter file instead of scanning JSONL.
- **Efficient last-CSV-row**: implement `read_last_csv_row()` via `seek(-4096, SEEK_END)` — read only the last 4KB of file to find the last complete row.
- **Tail-read for error counting**: replace `fp.readlines()` with `seek(-N, SEEK_END)` to read only the last ~40KB of log file.
- **Cache policy file**: in coordination service, cache the parsed policy dict and only re-read when `os.path.getmtime()` changes.
- **Remove double-wait**: in services that use `xreadgroup(block_ms=N)` followed by `time.sleep(T)`, remove the `time.sleep()` since the blocking read already provides the wait.

### Deliverables
- Updated `services/common/utils.py` (efficient `read_last_csv_row`)
- Updated `services/reconciliation_service/main.py` (use counter file)
- Updated `services/event_store/main.py` (maintain fill counters)
- Updated `services/bot_metrics_exporter.py` (tail-read for errors)
- Updated `services/coordination_service/main.py` (mtime-cached policy)

### Done Criteria
- Reconciliation cycle time does not grow with day length
- Metrics scrape does not load entire log files into memory
- Policy file read at most once per actual file change

---

## Day 63 - Tick-Loop Instrumentation + Grafana Performance Dashboard

### Context (Performance Audit — Instrumentation Plan)
No timing instrumentation exists on the hot path.  We cannot validate optimization impact or detect regressions without measurements.

### Tasks
- **Add `time.perf_counter()` around key sections** of `update_processed_data()`:
  - Total tick duration
  - Indicator computation (EMA + ATR + band_pct + drift)
  - Connector I/O (balances + order book + ready check)
  - CSV write duration
- **Expose as `processed_data` keys**: `_tick_duration_ms`, `_indicator_duration_ms`, `_connector_io_duration_ms`, `_csv_write_duration_ms`
- **Bot metrics exporter**: expose as Prometheus gauges:
  - `hbot_tick_duration_seconds`
  - `hbot_tick_indicator_seconds`
  - `hbot_tick_connector_io_seconds`
  - `hbot_csv_write_seconds`
  - `hbot_paper_order_tracker_size`
- **Grafana dashboard panel**: add a "Tick Performance" row to the trading overview dashboard with:
  - Tick duration histogram
  - Indicator vs connector vs CSV breakdown
  - Order tracker size trend

### Deliverables
- Updated `controllers/epp_v2_4.py` (timing instrumentation)
- Updated `services/bot_metrics_exporter.py` (new Prometheus metrics)
- Updated `monitoring/grafana/dashboards/trading_overview.json` (performance panels)

### Done Criteria
- Tick duration is visible in Grafana
- Can identify which component (indicators / connector / CSV) dominates tick time
- Alert fires if tick duration exceeds 100ms

---

## Day 64 - Strategy Logic Hardening (Quick Wins from Strategy Audit)

### Context (Strategy Audit — CRITICAL + HIGH)
The strategy audit identified 11 logic issues. The quick-win fixes below address the 4 most impactful bugs without changing the core strategy structure.

### Tasks
- **Reduce `spread_floor_recalc_s` default from 300 to 30**: prevents 5-minute stale floor during vol spikes. Change in `EppV24Config` field default. Config override still available.
- **Add regime transition cooldown**: introduce `regime_hold_ticks: int = Field(default=3)` — regime must be detected for N consecutive ticks before switching. Prevents order churn on EMA boundary oscillation.
- **Add `spread_min > market_spread / 2` guard**: before placing orders, verify that each side spread is wider than half the market spread. If not, widen to `market_spread / 2 + 1 bps`. Prevents accidentally crossing the book.
- **Cancel stale-side executors on regime flip**: when regime changes one-sided mode (e.g., neutral→up removes sells), immediately issue `StopExecutorAction` for active executors on the removed side. Don't wait for `executor_refresh_time`.

### Deliverables
- Updated `controllers/epp_v2_4.py` (4 fixes)
- Updated `EppV24Config` (new `regime_hold_ticks` field)

### Done Criteria
- Regime flips require 3 consecutive ticks (30s at 10s tick interval) to activate
- No executor remains active on a side that the regime has disabled
- Spread floor updates every 30s by default
- Orders never placed inside the market spread

---

## Day 65 - Fill Factor Calibration + Edge Validation

### Context (Strategy Audit — HIGH)
`fill_factor=0.4` is the single most important parameter for edge estimation, but has no empirical basis. Additionally, the analysis shows **the strategy may have negative expectancy at VIP0 fee tier** with default parameters.

### Tasks
- **Build `scripts/analysis/calibrate_fill_factor.py`**: reads `fills.csv` + `minute.csv`, computes `realized_spread_capture = |fill_price - mid_ref| / mid_ref` for each fill, and calculates the actual fill factor as `mean(realized_spread_capture) / mean(spread_pct)`.
- **Build `scripts/analysis/edge_report.py`**: produces a daily edge report: `gross_spread_capture - fees_paid - estimated_slippage - adverse_drift_cost`. Shows whether the strategy is actually profitable on a per-fill and per-day basis.
- **Add maker/taker classification to `did_fill_order()`**: check `event.trade_fee.is_maker` (if available from HB) or infer from `fill_price vs mid_ref` direction. Add `is_maker` column to fills.csv.
- **Document the edge model**: `docs/validation/edge_model_v1.md` — defines what constitutes "edge" for this strategy, how to measure it, and the minimum viable fee tier.

### Deliverables
- `scripts/analysis/calibrate_fill_factor.py`
- `scripts/analysis/edge_report.py`
- Updated `controllers/epp_v2_4.py` (maker/taker classification in `did_fill_order`)
- `docs/validation/edge_model_v1.md`

### Done Criteria
- `fill_factor` can be calibrated from live data (not just guessed)
- Edge report shows per-day net PnL with fee/slippage breakdown
- Maker/taker ratio is visible in fills.csv

---

## Day 66 - Adverse Selection + Funding Rate Modeling

### Context (Strategy Audit — HIGH)
`adverse_drift_30s` is not vol-normalized. Funding rate is not tracked for perp connectors. These two gaps distort both edge estimation and PnL attribution.

### Tasks
- **Vol-normalize shock drift**: change `shock_drift_30s_pct` comparison from absolute `drift >= threshold` to `drift / band_pct >= shock_multiplier`, where `shock_multiplier` is a new config field (default 1.25). This makes shock detection adaptive to current volatility.
- **Add funding rate tracking**: for perpetual connectors, fetch the funding rate (from connector or ccxt) and add it to the cost model: `net_edge = fill_factor * spread - fees - slippage - drift - funding_rate_cost_per_period`. Add `funding_rate` and `funding_cost_today_quote` to `processed_data`.
- **Add adverse selection measurement**: after each fill, measure the mid price 30 seconds later. Compute `adverse_selection_bps = (mid_post_fill - fill_price) * direction / mid`. Track running average in `processed_data`.

### Deliverables
- Updated `controllers/epp_v2_4.py` (vol-normalized shock, funding tracking, adverse selection measurement)
- New config fields: `shock_drift_multiplier`, `funding_rate_refresh_s`

### Done Criteria
- Shock detection sensitivity adapts to current volatility
- Funding rate cost is visible in processed_data and daily PnL
- Realized adverse selection is measurable from fills data

---

## Day 67 - Perp Equity Fix + Leverage Cap (Risk Audit — CRITICAL)

### Context (Risk Audit Finding FC-1, RC-2, P-1)
Equity is computed as `quote + base * mid` (spot formula). For perpetuals, this is incorrect — the correct equity is `margin_balance + unrealized_pnl`. Additionally, there is no leverage cap validation: a user can set `leverage: 20` in the YAML with no runtime guard.

### Tasks
- **Fix perp equity**: when `_perpetual` is in `connector_name`, use the connector's `get_balance("USDT")` as the equity (which includes unrealized PnL in perp mode) rather than `quote + base * mid`.
- **Add `max_leverage` config field**: `max_leverage: int = Field(default=5, ge=1, le=20, description="Maximum allowed leverage. Rejected at startup if config.leverage exceeds this.")`. Validate in `__init__`.
- **Add margin ratio check**: query `connector.get_margin_ratio()` (or equivalent) once per tick. If margin ratio < 20%, trigger SOFT_PAUSE. If margin ratio < 10%, trigger HARD_STOP.
- **Add `is_perpetual` property** to `EppV24Config` for cleaner branching.

### Done Criteria
- Equity calculation uses the correct method for spot vs perp connectors
- `leverage > max_leverage` is rejected at controller startup
- Margin ratio < 10% triggers HARD_STOP

---

## Day 68 - Orphan Order Scan + HARD_STOP → Exchange Cancel (Risk Audit — CRITICAL)

### Context (Risk Audit Finding RC-1, RC-4)
HARD_STOP clears runtime spreads but doesn't cancel existing exchange orders. Crash-restart can leave orphan orders that fill unexpectedly.

### Tasks
- **Wire HARD_STOP to kill switch**: when `OpsGuard` enters HARD_STOP with a risk reason (daily_loss, drawdown, turnover), publish a `kill_switch` intent to Redis so the kill switch service cancels exchange orders.
- **Orphan order scan on startup**: in `v2_with_controllers.py.__init__()`, query the exchange for open orders on the trading pair. If any exist that aren't tracked by the executor, cancel them and log an audit event.
- **Cancel budget escalation**: track consecutive cancel-budget breaches. After 3 consecutive SOFT_PAUSEs from cancel budget, escalate to HARD_STOP.

### Done Criteria
- HARD_STOP from risk limits triggers exchange-level cancel-all
- Orphan orders detected and canceled on startup
- Repeated cancel budget breaches escalate to HARD_STOP

---

## Day 69 - Realized PnL Tracking + Persistent Daily State (Risk Audit — HIGH)

### Context (Risk Audit Finding FC-2, FC-3, PnL Gaps)
No per-fill realized PnL. `_daily_equity_open` resets on restart, distorting daily loss limits.

### Tasks
- **Per-fill realized PnL**: maintain a `_cost_basis: Dict[str, Decimal]` mapping `side → avg_entry_price`. On each fill, compute `realized_pnl = (fill_price - avg_entry_price) * amount * direction - fee`. Add `realized_pnl_quote` column to fills.csv.
- **Persistent daily state**: write `_daily_equity_open`, `_daily_equity_peak`, `_traded_notional_today`, `_fills_count_today`, `_fees_paid_today_quote` to a JSON file (`logs/epp_v24/<instance>/daily_state.json`) every minute. On startup, load from this file if the day matches.
- **Funding cost accumulation**: deduct `funding_cost = funding_rate * position_notional` from PnL each funding period. Add `funding_cost_today_quote` to daily state persistence.

### Done Criteria
- Each fill in fills.csv has a `realized_pnl_quote` column
- Daily loss limits survive bot restart within the same day
- Funding cost is accumulated and visible in daily PnL

---

## Day 70 - Funding Rate in Edge Model + Portfolio Kill Switch (Risk Audit — HIGH)

### Context (Risk Audit Finding P-3, MB-3)
Funding rate is tracked but not deducted from the edge model. Kill switch is per-instance, not portfolio-wide.

### Tasks
- **Deduct funding from edge**: add `funding_cost_per_refresh_cycle` to the net edge formula: `net_edge = fill_factor * spread - fees - slippage - drift - turnover_penalty - funding_cost_est`. `funding_cost_est = abs(funding_rate) * (refresh_s / 28800)` (proportional to the hold period as fraction of 8h funding interval).
- **Portfolio-wide kill switch**: extend `portfolio_risk_service` to publish `kill_switch` intents for ALL scoped bots (not just the breaching bot) when `global_daily_loss_cap_pct` is breached. The kill switch service already listens per-instance.
- **Add `portfolio_kill_switch_on_global_breach: bool` config** in `portfolio_limits_v1.json` (default `true`).

### Done Criteria
- Net edge estimate includes funding rate cost
- Global daily loss breach cancels all orders on all scoped bots
- Funding cost impact visible in edge_report.py output

---

## Day 71 - Startup Order Scan + Position Reconciliation (Execution Audit — CRITICAL)

### Context (Execution Audit R-1, R-2, G-1, G-2)
After a crash/restart, orphan orders may remain on the exchange with no local tracking. The local `_position_base` can drift from the exchange position after missed fills. No periodic reconciliation exists.

### Tasks
- **Startup open-order scan**: in `v2_with_controllers.py.__init__()`, for each controller with a live connector, query `connector.get_open_orders()` (or equivalent). Cancel any orders not tracked by executors. Log audit event for each orphan found.
- **Periodic position reconciliation**: every 5 minutes in `update_processed_data()`, query the exchange for the actual position size (for perps: `connector.get_position()`, for spot: `connector.get_balance(base_asset)`). Compare with `_position_base`. If delta > 1%, log WARNING. If delta > 5%, trigger SOFT_PAUSE.
- **Add `_last_position_recon_ts` state** with 5-minute cooldown.
- **Add `position_drift_pct` to `processed_data`** for observability.

### Done Criteria
- Orphan orders detected and canceled on startup with audit event
- Position drift > 5% triggers SOFT_PAUSE
- `position_drift_pct` visible in Grafana

---

## Day 72 - Order Ack Timeout + Cancel-Before-Place Guard (Execution Audit — HIGH)

### Context (Execution Audit R-3, R-6, G-3, G-5)
No timeout for "order placing" state. Cancel-then-place on same level can create duplicate orders on exchange.

### Tasks
- **Order ack timeout**: in `executors_to_refresh()`, add a check: if an executor has been `is_active and not is_trading` for longer than 30 seconds (configurable `order_ack_timeout_s`), issue `StopExecutorAction` and log WARNING.
- **Cancel-before-place guard**: in `get_levels_to_execute()`, exclude levels where the previous executor is still in STOPPING state (check `close_type is not None and is_active`).
- **Max concurrent executors**: add `max_active_executors` config field (default 10). `get_levels_to_execute()` returns empty if active count >= max.
- **Execution price deviation alert**: in `did_fill_order()`, if `|fill_price - entry_price| / entry_price > 0.01` (1%), log WARNING with fill details.

### Done Criteria
- Orders stuck in "placing" for > 30s are canceled
- No duplicate orders on the same level
- Max executor count enforced

---

## Day 73 - WS Health Monitoring + Connector Status Exposure (Execution Audit — HIGH)

### Context (Execution Audit R-5, G-4, FM-6)
No visibility into WS connection health. Stale order book during reconnection leads to bad pricing.

### Tasks
- **Expose connector status dict**: in `ConnectorRuntimeAdapter`, add `status_summary() → Dict[str, bool]` that returns the connector's `status_dict` contents. Add to `processed_data` as `connector_status`.
- **Detect order book staleness**: track `_last_book_update_ts` by comparing order book top-of-book on consecutive ticks. If the top-of-book price is identical for > 30 seconds, flag `order_book_stale = True` in `processed_data`.
- **WS reconnection counter**: if `connector_ready()` transitions from False → True, increment `_ws_reconnect_count`. Expose in `processed_data`.
- **Add Prometheus metrics**: `hbot_ws_reconnect_total`, `hbot_order_book_stale`.

### Done Criteria
- Connector status visible in processed_data and Grafana
- Order book staleness detected and flagged
- WS reconnection events counted

---

## Day 74 - Go-Live Hardening Drill (Execution Audit — Validation)

### Context (Go-Live Checklist items 11-14)
Before live deployment, validate restart recovery, multi-day operation, and paper→live parity.

### Tasks
- **Restart recovery test**: start bot on testnet, let it place orders, kill the process (SIGKILL), restart, verify orphan orders are detected and canceled.
- **Paper→live parity check**: run paper and testnet simultaneously on same pair for 1 hour. Compare: fill count ratio, average spread capture, regime distribution, and PnL direction.
- **Multi-day soak**: run on testnet for 48 hours continuously. Verify: daily state rollover, no memory growth, no executor leak, funding rate tracking accuracy.
- **Exchange rate limit verification**: monitor Bitget rate limit response headers during the soak. Verify headroom > 50% at all times.
- **Document results**: `docs/ops/go_live_hardening_drill_YYYYMMDD.md` with evidence for each checklist item.

### Done Criteria
- Restart recovery works: orphan orders found and canceled
- Paper and testnet show same regime distribution and directionally consistent PnL
- 48-hour soak completes with no executor leaks, memory leaks, or unplanned stops
- All 14 go-live checklist items marked PASS

---

## Day 75 - Cross-Environment Parity Report (Validation Audit)

### Context (Validation Audit — Parity Gaps)
No tool exists to compare metrics across backtest, paper, and live environments side-by-side. Without parity measurement, there's no way to detect when simulation gives false confidence.

### Tasks
- **Build `scripts/analysis/parity_report.py`**: reads fills.csv from two environments (e.g., paper bot3 vs testnet bot4) and computes:
  - Fill rate ratio (fills/hour)
  - Avg spread capture ratio
  - Maker ratio comparison
  - Adverse selection comparison
  - Net edge comparison
  - Regime distribution divergence
- Output: `reports/analysis/parity_report.json` with per-metric pass/fail and an overall parity score
- **Parity thresholds**: fill rate ratio > 3x = WARNING; spread capture divergence > 50% = WARNING; regime distribution divergence > 10% = WARNING

### Done Criteria
- Side-by-side comparison of any two environments in one report
- WARNING flags when paper appears unrealistically optimistic vs live

---

## Day 76 - Post-Trade Shadow Validator (Validation Audit)

### Context (Validation Audit — FA-1, FA-2, FA-5)
`fill_factor`, `adverse_selection_bps`, and `queue_participation` are assumed constants with no empirical basis. The edge model may be lying.

### Tasks
- **Build `scripts/analysis/post_trade_validator.py`**: runs after each trading session and computes:
  - **Realized fill factor**: `mean(|fill_price - mid_ref|) / mean(spread_pct)` from fills.csv
  - **Realized adverse selection**: for each fill, look up mid price 30s later in minute.csv and compute `|(mid_30s - fill_price) / fill_price|`
  - **Realized queue participation**: `actual_fills / theoretical_fill_opportunities` (estimated from minutes where `state=running` and `orders_active > 0`)
  - **Edge model validation**: compare realized values against config values. If `realized_fill_factor < 0.7 * config.fill_factor`, flag CRITICAL.
- **Automated trigger**: can be wired into daily ops report or run as a cron job
- **Output**: `reports/analysis/post_trade_validation.json`

### Done Criteria
- Post-trade validator can detect when the edge model overestimates profitability
- CRITICAL flag fires when realized fill factor is materially lower than assumed
- Report runs automatically and is included in promotion gate checks

---

## Day 77 - Validation Ladder Gate Integration (Validation Audit)

### Context (Validation Audit — Validation Ladder)
The validation ladder (Level 0-7) exists conceptually but is not enforced. A strategy change can bypass paper soak and go directly to live.

### Tasks
- **Wire validation ladder into promotion gates**: `run_promotion_gates.py` must verify:
  - Level 1: backtest regression PASS (already exists)
  - Level 2: paper smoke PASS with `paper_fill_count > 0` (partially exists)
  - Level 3: paper soak PASS with all 7 KPIs green (exists but not gate-integrated)
  - Level 5 pre-check: `fill_factor_calibration.json` exists and `realized_fill_factor > 0`
  - Level 6 pre-check: `post_trade_validation.json` exists and no CRITICAL flags
- **Add `validation_level` field to promotion gate output**: shows which level of the ladder has been passed
- **Block live capital promotion if Level 3 not PASS**

### Done Criteria
- Promotion gates enforce the validation ladder
- Cannot promote to live without Level 3 PASS
- `validation_level` visible in gate output

---

## Day 78 - Metrics Export Gap Closure (SRE Audit)

### Context (SRE Audit — 20 missing metrics)
Days 63-73 added tick timing, position drift, margin ratio, funding rate, WS reconnect, and order book staleness to `processed_data`, but none are exported to Prometheus yet.

### Tasks
- **Extend `bot_metrics_exporter.py`** with 12 new metrics from `processed_data`:
  - `hbot_tick_duration_seconds`, `hbot_tick_indicator_seconds`, `hbot_tick_connector_io_seconds`
  - `hbot_position_drift_pct`, `hbot_margin_ratio`, `hbot_funding_rate`
  - `hbot_realized_pnl_today_quote`, `hbot_ws_reconnect_total`, `hbot_order_book_stale`
  - `hbot_cancel_budget_breach_count`, `hbot_validation_level`
  - `hbot_executor_count{state="active|stopping"}`
- **Add 10 new alert rules** to `alert_rules.yml` (from audit section 4)
- **Add Slack webhook** to `alertmanager.yml` (commented template already exists — uncomment and configure)

### Done Criteria
- All 12 new metrics visible in Prometheus / Grafana
- 10 new alert rules firing correctly on test data
- Alert delivery to Slack channel confirmed

---

## Day 79 - Execution Quality Dashboard + Structured Incident Template (SRE Audit)

### Context (SRE Audit — Dashboard sections 3-4)
No dashboard for execution quality (fill rate, maker ratio, spread capture, adverse selection). No structured incident template.

### Tasks
- **New Grafana dashboard: `Execution Quality`** with panels:
  - Fill rate (fills/hour) per bot — from `hbot_bot_fills_total` rate
  - Maker ratio per bot — derive from fills.csv `is_maker` column
  - Average spread capture (bps) — from `edge_report.json` or Postgres
  - Fill factor (realized vs configured) — from `fill_factor_calibration.json`
  - Position drift gauge — from `hbot_position_drift_pct`
  - Margin ratio gauge (perps) — from `hbot_margin_ratio`
- **New Grafana dashboard: `Risk & Exposure`** with panels:
  - Daily loss vs limit, drawdown vs limit
  - Cross-bot net exposure
  - Kill switch events timeline
- **Structured incident template**: create `docs/ops/incident_template.md` with fields: severity, timeline, root cause, impact, resolution, action items, evidence links

### Done Criteria
- Two new Grafana dashboards deployed and rendering data
- Incident template used for at least one post-mortem

---

## Day 80 - Backup + Retention + Operational Automation (SRE Audit)

### Context (SRE Audit — Backup score 4/10)
No scheduled Postgres backup. No event store archival. No automated config drift detection.

### Tasks
- **Postgres backup script**: `scripts/ops/pg_backup.sh` — daily `pg_dump` to `backups/` directory with 7-day retention. Compose service under `ops` profile.
- **Event store archival**: compress and archive `reports/event_store/events_*.jsonl` files older than 3 days to `backups/event_store/`. Delete originals after 7 days.
- **Config drift cron**: run `check_strategy_catalog_consistency.py` daily (compose service or cron).
- **Add `/health` HTTP endpoint** to `bot_metrics_exporter.py` and `control_plane_metrics_exporter.py` — returns 200 with last scrape age.

### Done Criteria
- Daily Postgres backup running and verified (restore test)
- Event store JSONL files older than 7 days automatically archived
- Config drift check runs daily without manual intervention
- `/health` endpoints respond for external uptime monitoring

---

## Day 81 - Execution Adapter Protocol (Migration Readiness — Optional)

### Context (Migration Audit)
The HB coupling surface is concentrated in 5 files (~2100 LOC). Formalizing an `ExecutionAdapter` protocol makes future connector swaps (to ccxt, NautilusTrader, or custom) a drop-in replacement without strategy logic changes.

### Tasks (Only execute if migration trigger fires)
- **Define `ExecutionAdapter` protocol** in `controllers/execution_adapter.py`:
  - `place_limit_order(pair, side, price, amount) → order_id`
  - `cancel_order(pair, order_id) → bool`
  - `get_balances() → Dict[str, Decimal]`
  - `get_order_book(pair) → OrderBook`
  - `get_open_orders(pair) → List[Order]`
  - Callback hooks: `on_fill`, `on_cancel`, `on_fail`
- **Refactor `ConnectorRuntimeAdapter`** to implement the protocol
- **Refactor `PaperExecutionAdapter`** to implement the protocol
- **Strategy code calls only the protocol** — no direct HB imports in orchestrator

### Done Criteria
- Strategy logic has zero `from hummingbot` imports
- Swapping execution adapter requires changing one line of configuration

---

## Day 82 - Strategy Runner Abstraction (Migration Readiness — Optional)

### Context (Migration Audit)
`v2_with_controllers.py` (500 LOC) is 100% HB-coupled glue. Extracting a framework-agnostic runner makes the strategy portable.

### Tasks (Only execute if migration trigger fires)
- **Extract `StrategyRunner` base class**: owns tick loop, bus integration, drawdown checks, preflight
- **`HBStrategyRunner(StrategyRunner)`**: thin subclass with HB-specific lifecycle
- **`CcxtStrategyRunner(StrategyRunner)`**: future ccxt-based runner (stub only)

### Done Criteria
- Strategy runner logic is framework-agnostic
- HB-specific code is isolated in subclass

---

## Migration Trigger Guardrail (Option 4 — Updated)

**Do not migrate execution platform now.** Revisit if ANY trigger fires:
- HB V2 framework makes a breaking change requiring > 1 week adaptation
- Primary exchange switches from Bitget to Binance/Bybit (unlocks NautilusTrader)
- Strategy evolves beyond market making (directional alpha needs proper backtest)
- Team grows to 2+ developers with bandwidth to maintain custom framework
- Post-trade validator consistently flags CRITICAL on fill model assumptions
- parity and reconciliation are stable for multiple windows
- portfolio risk controls are proven in production-like soak
- rollback to current baseline is tested end-to-end

### Migration Readiness Status
- **Portable components**: 80% of codebase (services, backtest, analysis, config, monitoring) — zero HB imports
- **Coupled components**: 5 files, ~2100 LOC — documented in `docs/dev/hb_compatibility_matrix.md`
- **Adapter protocol**: defined (Day 81, optional) — not yet implemented
- **Estimated migration effort if triggered**: 6-10 weeks (ccxt DIY) or 12-16 weeks (NautilusTrader + Bitget adapter)
