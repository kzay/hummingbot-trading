# Runbooks

## Purpose
Operational SOPs for startup, shutdown, recovery, and controlled changes.

## Startup (external orchestration)
1. Validate `env/.env`.
2. Start:
   - `docker compose --env-file ../env/.env --profile multi --profile test --profile external up -d`
3. Confirm service health (`ps`, logs, Redis ping).
4. Start/verify strategy in bot terminal.

## EPP V2 Environment Switch (No Code Changes)
1. Pick one controller profile file:
   - `data/bot1/conf/controllers/epp_v2_4_binance_demo_smoke.yml`
   - `data/bot1/conf/controllers/epp_v2_4_bitget_paper_smoke.yml`
2. Start with matching script config:
   - `start --script v2_with_controllers.py --conf v2_epp_v2_4_binance_demo_smoke.yml`
   - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bitget_paper_smoke.yml`
3. Verify preflight passes in logs (`Preflight validation passed.`).
4. If preflight fails, fix config mismatch and restart; do not patch controller code.

## Preflight Failure Meanings
- `connector ... not mapped in exchange_profiles.json`:
  - Add/update `config/exchange_profiles.json`.
- `requires paper_trade_exchanges`:
  - Add required exchange under `paper_trade.paper_trade_exchanges` in `conf_client.yml`.
- `fee profile ... missing connector`:
  - Add connector fee entry under selected profile in `config/fee_profiles.json`.

## Shutdown
- Graceful:
  - `docker compose --env-file ../env/.env --profile multi --profile external down`

## Graceful Shutdown Verification
Use this before deploy, rollback, or host maintenance so stateful services drain cleanly.

1. Stop with a bounded timeout:
   - `docker compose --env-file ../env/.env --profile multi --profile external stop --timeout 10`
2. Confirm containers exit:
   - `docker compose --env-file ../env/.env ps`
3. Verify state artifacts were left in a readable state:
   - `reports/verification/paper_exchange_state_snapshot_latest.json`
   - `reports/verification/paper_exchange_pair_snapshot_latest.json`
   - `reports/verification/paper_exchange_command_journal_latest.json`
4. If shutdown was part of a planned restart, bring services back and confirm health before resuming bots.
5. If any state artifact is missing or corrupt, keep promotion blocked and run the recovery/restore drill before restarting trading.

## Degraded Mode
- Redis down:
  - restart without `--profile external`
  - keep local HB safeguards active

## Rollback
- Revert to previous image/config snapshot.
- Run post-rollback health checks and log verification.

## Postgres Backup + Restore Drill
Run this at least once before any near-live promotion window and after any backup-path change.

1. Create a fresh backup artifact:
   - `python scripts/ops/pg_backup.py --once`
2. Validate the restore path into a clean instance:
   - `python scripts/ops/ops_db_restore_drill.py`
3. Confirm evidence:
   - `reports/ops/ops_db_backup_latest.json`
   - `reports/ops/ops_db_restore_drill_latest.json`
4. Keep promotion blocked if either report is stale, failed, or shows query mismatches after restore.

## Shared Market History Rollout
Use this when enabling provider-backed history reads or runtime seeding.

1. Follow:
   - `docs/ops/shared_market_history_runbook.md`
2. Generate/refresh evidence:
   - `python scripts/ops/backfill_market_bar_v2.py --dry-run`
   - `python scripts/ops/backfill_market_bar_v2.py`
   - `python scripts/ops/report_market_bar_v2_capacity.py`
3. Run promotion gates:
   - `python scripts/release/run_promotion_gates.py --ci`
4. Keep rollout blocked if backfill parity, seed rollout, or capacity evidence is stale/failing.

## Active Paper Market Feed
Use this when active paper bots depend on shared quote snapshots from `market-data-service`.

1. Keep discovery enabled unless you are doing a deliberate one-off override:
   - `MARKET_DATA_SERVICE_AUTO_DISCOVER=true`
   - `MARKET_DATA_SERVICE_CONTROLLER_CONFIG_ROOT=/workspace/hbot/data`
2. Scope discovered feeds to the execution desk connectors so unrelated venues do not flood the shared quote stream:
   - `MARKET_DATA_SERVICE_DISCOVERY_CONNECTORS=bitget_perpetual`
3. After any controller-pair change or feed restart, verify:
   - `reports/market_data_service/latest.json`
   - `reports/verification/paper_exchange_pair_snapshot_latest.json`
4. If active submits fail with `no_market_snapshot`, confirm the missing pair exists in both artifacts before changing command TTLs or bot logic.

## Near-Live Release Discipline
Use this sequence when preparing a candidate build so ROAD-1 / ROAD-5 evidence and strict promotion stay aligned.

1. Refresh analysis evidence:
   - `python hbot/scripts/analysis/performance_dossier.py`
   - `python hbot/scripts/analysis/bot1_multi_day_summary.py`
   - `python hbot/scripts/analysis/testnet_multi_day_summary.py`
2. Check the strategic ladders:
   - `reports/analysis/performance_dossier_latest.json`
   - `reports/strategy/multi_day_summary_latest.json`
   - `reports/strategy/testnet_multi_day_summary_latest.json`
3. Run strict promotion only after evidence is fresh:
   - `python scripts/release/run_strict_promotion_cycle.py`
4. Promotion interpretation:
   - `performance_dossier_expectancy_ci` failing means strategy quality is still the blocker.
   - `road1_gate` or `road5_gate` failing means the remaining blocker is campaign duration / validation evidence, not simulator ambiguity.

## Secrets Hygiene (Operational)
- Canonical policy:
  - `docs/ops/secrets_and_key_rotation.md`
  - `docs/infra/secrets_and_env.md`
- Never print or commit secret values from `env/.env`.
- Only use masked secret diagnostics (`****ABCD`) in logs/reports.
- If secret exposure is suspected:
  - move to safe mode (`soft_pause`/`kill_switch`)
  - rotate keys immediately
  - document incident without secret values

## Key Rotation (Planned)
1. Update keys in host `env/.env`.
2. Recreate affected containers only:
   - `exchange-snapshot-service`
   - impacted bot containers
3. Validate:
   - `reports/exchange_snapshots/latest.json` (`account_probe_status`)
   - `reports/reconciliation/latest.json` (no critical drift)
4. Revoke old keys after validation.

## Break-Glass Credential Response
1. Pause/stop impacted bots.
2. Revoke compromised keys at exchange.
3. Apply emergency rotated keys in `env/.env`.
4. Recreate affected services and rerun promotion checks.
5. Record incident metadata and evidence paths in `docs/ops/incidents.md`.

## Bus Restart + Verification (Day 18)
Use this when Redis must be restarted or recovered.

1. Pre-checkpoint:
   - `python scripts/release/run_bus_recovery_check.py --label pre_restart`
2. Restart Redis:
   - `docker compose --env-file ../env/.env -f docker-compose.yml restart redis`
3. Wait for health:
   - `docker compose --env-file ../env/.env -f docker-compose.yml ps redis`
   - ensure status includes `healthy`.
4. Post-checkpoint:
   - `python scripts/release/run_bus_recovery_check.py --label post_restart`
5. Acceptance:
   - `reports/bus_recovery/latest.json` shows `status=pass`
   - no missing correlations and no restart-induced delta regression.
6. Optional strict legacy check:
   - `python scripts/release/run_bus_recovery_check.py --label post_restart --enforce-absolute-delta --max-delta 5`

If post-check fails:
- keep promotion blocked
- inspect `reports/event_store/day2_gate_eval_latest.json`
- inspect latest `reports/event_store/source_compare_*.json`
- open incident in `docs/ops/incidents.md`

## Multi-Bot Scaling + Isolation (Day 19)
Policy source:
- `docs/ops/multi_bot_policy_v1.md`
- `config/multi_bot_policy_v1.json`

Canonical startup modes:
1. Live primary bot + control plane:
   - `docker compose --env-file ../env/.env --profile external up -d bot1`
2. Validation bots (paper + connector testnet):
   - `docker compose --env-file ../env/.env --profile test up -d bot3 bot4 bot5`
3. Reserved scale slot:
   - `docker compose --env-file ../env/.env --profile multi up -d bot2`
   - keep `bot2` in no-trade mode unless an explicit policy revision is approved.

Required policy gate before promotion:
- `python scripts/release/check_multi_bot_policy.py`
- `python scripts/release/run_promotion_gates.py --ci`

If policy check fails:
- Keep promotion blocked.
- Reconcile mismatches between:
  - `config/multi_bot_policy_v1.json`
  - `config/portfolio_limits_v1.json`
  - `config/exchange_account_map.json`
  - `config/reconciliation_thresholds.json`
- Re-run policy check and promotion gates after fixes.

## Strategy Catalog Operations (Day 29)
Catalog source:
- `docs/ops/strategy_catalog_v1.md`
- `config/strategy_catalog/catalog_v1.json`
- `config/strategy_catalog/templates/controller_template.yml`
- `config/strategy_catalog/templates/script_template.yml`

Add a new strategy/controller variant (no compose edits):
1. Implement/update shared controller code in `controllers/`.
2. Copy template configs and create a pair:
   - `data/<bot>/conf/controllers/controller_<strategy>_<version>_<bot>_<venue>_<mode>.yml`
   - `data/<bot>/conf/scripts/script_<strategy>_<version>_<bot>_<venue>_<mode>.yml`
3. Start with:
   - `start --script v2_with_controllers.py --conf <script_config>.yml`
4. Run promotion gates and collect evidence before promotion.

## Shared Controllers Mount + Drift Prevention (Day 30)
- Controllers are mounted as shared directories for all bots:
  - `../controllers -> /home/hummingbot/controllers` (read-only)
  - `../controllers -> /home/hummingbot/controllers/market_making` (read-only compatibility path)
- Drift checker command:
  - `python scripts/release/check_strategy_catalog_consistency.py`
- Gate integration:
  - `python scripts/release/run_promotion_gates.py --ci`
  - requires `strategy_catalog_consistency=PASS`

Controller refresh guidance:
- Dev:
  - recreate affected bot container(s) after controller edits.
- If stale code persists:
  - `docker exec kzay-capital-bot1 rm -rf /home/hummingbot/controllers/__pycache__ /home/hummingbot/controllers/market_making/__pycache__`
- Prod:
  - use controlled recreate; do not patch controller files inside running containers.

## Test Suite Gate (Day 31)
- Deterministic runner:
  - `python scripts/release/run_tests.py`
- Optional runtime selection:
  - `--runtime host`
  - `--runtime docker`
  - `--runtime auto` (default)
- Artifacts:
  - `reports/tests/latest.json`
  - `reports/tests/latest.md`
  - `reports/tests/coverage.xml`
  - `reports/tests/coverage.json`
- Promotion dependency:
  - `run_promotion_gates.py` requires critical `unit_service_integration_tests=PASS`.

## Coordination Service Policy (Day 32)
- Policy source:
  - `docs/ops/coordination_service_policy_v1.md`
  - `config/coordination_policy_v1.json`
- Default safety:
  - `COORD_ENABLED=false`
  - `COORD_REQUIRE_ML_ENABLED=true`
- Health artifact:
  - `reports/coordination/latest.json`
- Policy validation:
  - `python scripts/release/check_coordination_policy.py`
- Promotion dependency:
  - `run_promotion_gates.py` requires critical `coordination_policy_scope=PASS`.

## Control-Plane Coordination Metrics (Day 33)
- Exporter source:
  - `services/control_plane_metrics_exporter.py`
- Coordination artifacts surfaced:
  - `reports/coordination/latest.json`
  - `reports/policy/coordination_policy_latest.json`
- Prometheus metrics to verify:
  - `hbot_control_plane_report_fresh{report="coordination"}`
  - `hbot_control_plane_report_fresh{report="coordination_policy"}`
  - `hbot_control_plane_gate_status{gate="coordination_policy_scope",source="promotion_latest"}`
  - `hbot_control_plane_gate_status{gate="coordination_runtime_ok"}`
- Quick check:
  - `curl -s http://localhost:9401/metrics | grep coordination`
- Dashboard panels:
  - `Trading Desk Control Plane`:
    - `Coord Policy Gate`
    - `Coord Runtime Health`
- Alert rules:
  - `CoordinationPolicyGateFailed`
  - `CoordinationRuntimeNotHealthy`

## Event-Store Recovery + Strict Cycle (Day 35)
- Single-command recovery runner:
  - `python scripts/release/recover_event_store_stack_and_strict_cycle.py --max-wait-sec 180 --poll-sec 5 --max-report-age-min 20`
- Behavior:
  - validates Docker daemon reachability
  - starts minimal external services (`redis`, `event-store-service`, `event-store-monitor`, `day2-gate-monitor`)
  - waits for health and then runs strict promotion cycle
  - writes artifact:
    - `reports/recovery/latest.json`
- Pass condition:
  - all four services become healthy
  - strict cycle returns PASS (`critical_failures=[]`)
- If still FAIL:
  - inspect `reports/promotion_gates/latest.json`
  - inspect `reports/event_store/day2_gate_eval_latest.json`

## Realtime UI + L2 Operations
1. Enable services:
   - `docker compose --env-file ../env/.env --profile external up -d realtime-ui-api realtime-ui-web`
2. Set rollout mode:
   - `REALTIME_UI_API_MODE=shadow` for parallel validation.
   - `REALTIME_UI_API_MODE=active` when operator cutover is approved.
3. Security gate before non-loopback exposure:
   - set `REALTIME_UI_API_AUTH_ENABLED=true`
   - set `REALTIME_UI_API_AUTH_TOKEN` through the operator secret path
   - set `REALTIME_UI_API_ALLOWED_ORIGINS` to the approved UI origins
   - keep `REALTIME_UI_API_ALLOW_QUERY_TOKEN=false`
4. Degraded-mode fallback policy:
   - keep `REALTIME_UI_API_DEGRADED_MODE_ENABLED=false` for normal operation
   - enable degraded mode only for emergency CSV/JSON fallback during outage handling
5. Verify health:
   - API: `http://localhost:9910/health`
   - Web UI: `http://localhost:8088`
6. Run L2 quality gate manually:
   - `python scripts/release/check_realtime_l2_data_quality.py`
7. Strict-cycle evidence:
   - `reports/verification/realtime_l2_data_quality_latest.json`
   - `reports/promotion_gates/latest.json` must show `realtime_l2_data_quality=PASS`.

Rollback:
- set `REALTIME_UI_API_MODE=disabled`
- keep `desk_snapshot_service` available, but do not enable degraded fallback unless incident response explicitly calls for it
- rerun strict cycle before resuming promotion flow.
  - treat `day2_event_store_gate` as expected until elapsed window + delta tolerance both pass.

## Day2 Baseline Reanchor (Day 36)
- Use only after infrastructure recovery when baseline drift is legacy/stale and obscures current ingest quality.
- Command:
  - `python scripts/utils/reset_event_store_baseline.py --reason "day36_reanchor_after_runtime_recovery" --force`
- Produces evidence:
  - `reports/event_store/baseline_reset_preview_*.json`
  - `reports/event_store/baseline_counts_backup_*.json`
  - `reports/event_store/baseline_reset_apply_*.json`
- Immediate verification:
  - `python scripts/utils/event_store_count_check.py`
  - `python scripts/utils/day2_gate_evaluator.py`
  - expect:
    - `delta_since_baseline_tolerance=PASS`
    - `missing_correlation=PASS`
    - `elapsed_window` remains pending until full Day2 window elapses.

## Accounting Layer v2 (Day 36)
- Run accounting integrity checker:
  - `python scripts/release/check_accounting_integrity_v2.py --max-age-min 20`
- Artifacts:
  - `reports/accounting/latest.json`
  - `reports/accounting/accounting_integrity_<timestamp>.json`
- Promotion integration:
  - `run_promotion_gates.py` includes `accounting_integrity_v2` as a critical gate.
- DB persistence path:
  - `ops-db-writer` ingests `reports/reconciliation/latest.json` `accounting_snapshots[]` into Postgres `accounting_snapshot`.
- Quick SQL checks:
  - `SELECT COUNT(*) FROM accounting_snapshot;`
  - `SELECT bot, ts_utc, fees_paid_today_quote, funding_paid_today_quote FROM accounting_snapshot ORDER BY ts_utc DESC, bot LIMIT 20;`

## Formal CI Pipeline (Day 37)
- One-command CI orchestrator:
  - `python scripts/release/run_ci_pipeline.py --tests-runtime host --cov-fail-under 5 --min-events 1000`
- Dry run:
  - `python scripts/release/run_ci_pipeline.py --dry-run --tests-runtime host`
- Workflow file:
  - `.github/workflows/day37_formal_ci_pipeline.yml`
- CI evidence:
  - `reports/ci_pipeline/latest.json`
  - `reports/ci_pipeline/latest.md`
- Includes:
  - deterministic tests (`run_tests.py`)
  - replay regression multi-window (`run_replay_regression_multi_window.py`)
  - promotion gates (`run_promotion_gates.py --ci --skip-replay-cycle`)

## Replay Regression First-Class Gate (Day 38)
- Multi-window runner:
  - `python scripts/release/run_replay_regression_multi_window.py --windows 500,1000,2000 --repeat 2`
- Artifacts:
  - `reports/replay_regression_multi_window/latest.json`
  - `reports/replay_regression_multi_window/latest.md`
- Promotion integration:
  - `run_promotion_gates.py` critical gate `replay_regression_first_class`
- Window pass criteria:
  - each window must have `status=pass`
  - each window must have `deterministic_repeat_pass=true`

## ML Signal Governance (Day 39)
- Policy source:
  - `config/ml_governance_policy_v1.json`
  - `docs/ops/ml_signal_governance_policy_v1.md`
- Checker:
  - `python scripts/release/check_ml_signal_governance.py`
- Artifacts:
  - `reports/policy/ml_governance_latest.json`
  - `reports/policy/ml_governance_check_<timestamp>.json`
- Promotion integration:
  - `run_promotion_gates.py` includes critical gate `ml_signal_governance`.
- Interpretation:
  - `ML_ENABLED=false`: policy validation + baseline-only safe mode should PASS.
  - `ML_ENABLED=true`: requires fresh `reports/ml/latest.json` and passing baseline/drift/retirement checks.

## ClickHouse Event Analytics (Day 40)
- Bring up ClickHouse stack:
  - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml up -d clickhouse clickhouse-ingest`
- One-shot dry run (no DB writes):
  - `python services/clickhouse_ingest/main.py --once --dry-run`
- One-shot real ingest:
  - `python services/clickhouse_ingest/main.py --once`
- Ingestion artifacts:
  - `reports/clickhouse_ingest/latest.json`
  - `reports/clickhouse_ingest/state.json`
- Grafana datasource:
  - `ClickHouse Events` (`uid: clickhouse-events`)
- Quick verification SQL (ClickHouse):
  - `SELECT count(*) FROM event_store_raw_v1;`
  - `SELECT event_type, count(*) FROM event_store_raw_v1 GROUP BY event_type ORDER BY count(*) DESC LIMIT 20;`

## Market Data Freshness Gate (Roadmap Day 35)
- Checker command:
  - `python scripts/release/check_market_data_freshness.py --max-age-min 20`
- Artifact:
  - `reports/market_data/latest.json`
- Promotion integration:
  - `run_promotion_gates.py` includes `market_data_freshness` as a warning gate.
- Interpretation:
  - `events_file_fresh=true` and `market_data_rows_present=true` => healthy feed recency signal.
  - warning does not hard-block promotion, but must be triaged before final approval.

## HB Version Upgrade Path (Roadmap Day 35)
- Dry-run readiness check:
  - `python scripts/release/check_hb_upgrade_readiness.py --target-image hummingbot/hummingbot:version-2.12.1`
- Preflight evidence:
  - `reports/upgrade/latest.json`
- Controlled rollout:
  1. test profile first:
     - `HUMMINGBOT_IMAGE=<target> docker compose --env-file env/.env -f compose/docker-compose.yml --profile test up -d --force-recreate bot3 bot4`
  2. run checks:
     - `python scripts/release/run_promotion_gates.py --ci`
  3. no-trade live safety rollout:
     - `HUMMINGBOT_IMAGE=<target> docker compose --env-file env/.env -f compose/docker-compose.yml up -d --force-recreate bot1`
  4. monitor:
     - `reports/reconciliation/latest.json`
     - `reports/parity/latest.json`
     - `reports/portfolio_risk/latest.json`
- Rollback:
  - set `HUMMINGBOT_IMAGE` back to previous tag and recreate `bot1`/`bot3`/`bot4`.

## Pre-Release Secrets Hygiene (Day 20)
Run before any promotion decision:
1. `python scripts/release/run_secrets_hygiene_check.py --include-logs`
2. Confirm `reports/security/latest.json` has:
   - `status=pass`
   - `finding_count=0`
3. Confirm promotion gate includes `secrets_hygiene` check and remains PASS.
4. If fail:
   - block promotion
   - remove/redact leaked material
   - rotate affected keys if real values were exposed
   - re-run hygiene check + gates

## Paper Trade Startup

1. Runtime mode is controlled by `BOT_MODE=paper|live` (env), not by
   `internal_paper_enabled`.
2. For EPP v2.4 in paper mode, keep the production connector mapping
   (for example `connector_name: bitget_perpetual`); Paper Engine v2 bridge
   intercepts order routing.
3. In `conf_client.yml`, ensure:
   - `paper_trade_exchanges` includes the live connector name used by the bot
     (for example `bitget_perpetual` for bot1/bot2/bot3/bot5).
   - `paper_trade_account_balance` includes realistic BTC/USDT balances.
4. Only legacy standalone scripts should use `bitget_paper_trade` directly.
   Controller-based paper lanes now keep the live connector mapping and rely on
   Paper Engine v2 interception.
5. Start the bot and verify `status` includes paper diagnostics (`paper fills`,
   `rejects`, `avg_qdelay_ms`) plus controller regime/spread data.
6. If you need emergency rollback from paper-exchange service integration, set
   `PAPER_EXCHANGE_MODE_BOT<id>=disabled` and recreate that bot container.

## Paper Exchange Service Rollout (P1-9)

Use this for controlled cutover of `PAPER_EXCHANGE_MODE` per bot
(`disabled|shadow|active|auto`).

Optional strict-routing hardening:
- set `PAPER_EXCHANGE_SERVICE_ONLY=true` to force fail-closed service routing.
- optional per-bot override: `PAPER_EXCHANGE_SERVICE_ONLY_BOT<id>=true|false`.
- when strict-routing is enabled, `auto` resolves to `active` even when heartbeat
  is stale (no implicit shadow fallback).

One-command canary launcher (recommended):
- `python scripts/ops/run_paper_exchange_canary.py --bot bot3 --mode shadow`
- `python scripts/ops/run_paper_exchange_canary.py --bot bot3 --mode auto`
- `python scripts/ops/run_paper_exchange_canary.py --bot bot3 --mode auto --service-only-mode true`
- Preview only (no changes/commands):
  - `python scripts/ops/run_paper_exchange_canary.py --bot bot3 --mode shadow --dry-run`
  - `python scripts/ops/run_paper_exchange_canary.py --bot bot3 --mode auto --dry-run`

1. Start service in isolated profile:
   - `docker compose --env-file ../env/.env --profile external --profile paper-exchange up -d redis paper-exchange-service`
2. Canary in shadow mode on a validation bot (recommended `bot3`):
   - set `PAPER_EXCHANGE_MODE_BOT3=shadow` in `env/.env`
   - recreate canary bot:
     - `docker compose --env-file ../env/.env --profile test up -d --force-recreate bot3`
3. Validate parity + load evidence:
   - `python scripts/release/run_promotion_gates.py --check-paper-exchange-thresholds --run-paper-exchange-load-harness`
4. Promote canary to active mode:
   - set `PAPER_EXCHANGE_MODE_BOT3=active` and recreate `bot3`
5. Roll to bot1 only after gate pass:
   - set `PAPER_EXCHANGE_MODE_BOT1=shadow` (then `active` after parity re-check)
   - recreate `bot1` each step.

### Sustained Load Qualification (P1-19)

Use this before promoting active-mode desk concurrency claims.

One-command sustained qualification (default 2h profile):
- `python scripts/release/run_paper_exchange_sustained_qualification.py --strict`

What it does:
1. Runs multi-instance synthetic harness for sustained duration.
2. Runs load/backpressure checker scoped to harness `run_id`.
3. Emits consolidated artifact:
   - `reports/verification/paper_exchange_sustained_qualification_latest.json`

Common overrides:
- shorter dry qualification window:
  - `python scripts/release/run_paper_exchange_sustained_qualification.py --strict --duration-sec 1800 --sustained-window-sec 1800`
- explicit instance coverage:
  - `--instance-names bot1,bot3,bot4 --min-instance-coverage 3`

Promotion integration (optional, long-running):
- `python scripts/release/run_promotion_gates.py --ci --check-paper-exchange-thresholds --check-paper-exchange-sustained-qualification`
- strict-cycle pass-through:
  - `python scripts/release/run_strict_promotion_cycle.py --check-paper-exchange-sustained-qualification`

### Performance Baseline Capture (QPRO-PERF-2)

Use this when you intentionally re-anchor the regression baseline after a validated
load profile update (for example, a sustained qualification profile refresh).

One-command baseline capture:
- `python scripts/release/capture_paper_exchange_perf_baseline.py --strict --profile-label sustained_2h`

Optional strict-cycle wiring:
- `python scripts/release/run_strict_promotion_cycle.py --capture-paper-exchange-perf-baseline --paper-exchange-perf-baseline-profile-label sustained_2h`

### Paper Exchange Rollback

1. Immediate rollback for impacted bot:
   - set `PAPER_EXCHANGE_MODE_BOT<id>=disabled` in `env/.env`
   - recreate that bot container (`--force-recreate`)
2. If service instability persists:
   - stop service profile:
     - `docker compose --env-file ../env/.env --profile paper-exchange stop paper-exchange-service`
3. Confirm rollback health:
   - `python scripts/ops/preflight_paper_exchange.py`
   - `python scripts/release/run_promotion_gates.py --check-paper-exchange-thresholds`

### Active-Mode Failure Policy (P1-16)

For `PAPER_EXCHANGE_MODE_<BOT>=active`, controller behavior is deterministic:

1. `service_down` failures (`redis_unavailable`, command publish failures/exceptions):
   - action: `soft_pause`
   - reason prefix: `paper_exchange_soft_pause:service_down:`
2. `stale_feed` failures (`stale_market_snapshot`, `no_market_snapshot`):
   - action: `soft_pause`
   - reason prefix: `paper_exchange_soft_pause:stale_feed:`
3. `command_backlog` failures (`expired_command`):
   - action: `soft_pause`
   - reason prefix: `paper_exchange_soft_pause:command_backlog:`
4. Recovery loop (repeated failures on same `(instance, connector, pair)`):
   - action: `hard_stop`
   - reason prefix: `paper_exchange_recovery_loop:<class>:<reason>`
5. Recovery:
   - first successful `processed` outcome resets failure streak and emits `resume`.

Operator checks:
- In controller logs/telemetry, confirm standardized reason prefixes above.
- Confirm no implicit fallback to legacy local execution while mode is `active`.
- If `hard_stop` is raised, either:
  - rollback to `PAPER_EXCHANGE_MODE_<BOT>=disabled`, or
  - resolve service/feed condition and issue controlled restart.

## Canonical Data Plane Rollback (TS8)

Use this when canonical DB mode (`db_primary`) needs immediate fallback to CSV compatibility (`csv_compat`).

1. Apply timed rollback drill (writes evidence + mode flags):
   - `python scripts/ops/data_plane_rollback_drill.py --env-file env/.env --apply --from-mode db_primary --to-mode csv_compat`
2. Verify promotion checks in fallback mode:
   - `python scripts/release/run_promotion_gates.py --max-report-age-min 20`
3. Validate drill evidence:
   - `reports/ops/data_plane_rollback_drill_latest.json` has `status=pass`
   - `duration_sec <= 300` (5-minute rollback target)

## EPP Paper Validation Checklist (24h minimum)

Track these KPIs from `minute.csv` / `fills.csv` before changing capital:

- Stability
  - `% running` >= 65%
  - No repetitive minute-by-minute flapping between `running` and `soft_pause`
- Risk
  - `turnover_today_x` <= 3.0
  - `daily_loss_pct` < 1.5% and `drawdown_pct` < 2.5%
  - No `hard_stop` events from risk limits
- Execution quality
  - `cancel_per_min` below configured budget for >95% of samples
  - Fee source remains resolved (`api:*`, `connector:*`, or `project:*`)
  - `paper_reject_count` remains near zero after startup warmup
- Inventory
  - `base_pct` remains inside configured hard band (`min_base_pct`..`max_base_pct`)
  - `base_pct` tracking error vs target shrinks after large deviations

## Smoke Test Matrix (Phase 4)
- Binance demo futures micro-size:
  - `start --script v2_with_controllers.py --conf v2_epp_v2_4_binance_demo_smoke.yml`
  - Expect connector ready, preflight pass, continuous ticks for soak window.
- Bitget paper micro-size:
  - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bitget_paper_smoke.yml`
  - Expect connector ready, preflight pass, order cycle/fill logs on paper connector.

## Bot3 Dedicated V2 Paper Matrix
- Bot3 is the mandatory test bot for V2 paper-controller scenarios.
- Bot3 now mirrors Bot1's production connector mapping in paper mode
  (`bitget_perpetual` via Paper Engine v2), rather than using the old direct
  paper-trade wrapper path.
- Start bot3:
  - `docker compose --env-file ../env/.env --profile test up -d bot3`
- Active paper trading scenario:
  - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot3_paper_smoke.yml`
- No-trade safety scenario:
  - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot3_paper_notrade.yml`
- Pass criteria:
  - preflight pass
  - connector ready
  - no API order errors
  - expected behavior per mode (orders in smoke, no orders in notrade)

## Bot5 Dedicated IFT/JOTA Paper Lane
- Bot5 is the institutional-flow paper-validation lane.
- It preserves its distinct IFT/JOTA strategy configuration while using the same
  hardened paper/runtime baseline as Bot1.
- Start bot5:
  - `docker compose --env-file ../env/.env --profile test up -d bot5`
- Active paper trading scenario:
  - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot5_ift_jota_paper.yml`
- Pass criteria:
  - preflight pass
  - connector ready
  - paper diagnostics populated
  - fills/order flow match the intended IFT/JOTA lane behavior without bypassing
    safety guards

## Bot4 Binance Testnet V2 Matrix
- Bot4 is the dedicated V2 validation bot for Binance testnet scenarios.
- Start bot4:
  - `docker compose --env-file ../env/.env --profile test up -d --force-recreate bot4`
- Configure connector credentials in bot4 once:
  - `connect binance_perpetual_testnet`
- Scenarios:
  - Active smoke:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_smoke.yml`
  - No-trade safety:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_notrade.yml`
  - Manual-fee fallback:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_manual_fee.yml`
  - Auto-fee resolution:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_auto_fee.yml`
  - Edge-gate pause:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_edge_pause.yml`
  - Inventory guard trigger:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_inventory_guard.yml`
  - Cancel-budget throttle:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_cancel_budget.yml`
- Pass criteria:
  - preflight pass
  - connector transitions to ready
  - no recurring startup/readiness loop
  - expected scenario behavior (orders active vs. no-trade)
  - evidence captured in `minute.csv` / `fills.csv` for each scenario

## Bot1 Bitget Live Micro-Cap (Day 15)
- Preconditions:
  - `bitget_perpetual` connector credentials configured for bot1.
  - Risk envelopes reviewed and approved for micro-cap.
  - Strict gate status reviewed before run.
- Start bot1:
  - `docker compose --env-file ../env/.env --profile multi up -d --force-recreate bot1`
- Scenarios:
  - Live micro-cap:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot1_bitget_live_microcap.yml`
  - Live no-trade safety:
    - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot1_bitget_live_notrade.yml`
- Validate no-trade window:
  - `python scripts/release/validate_notrade_window.py --minute-csv data/bot1/logs/epp_v24/bot1_a/minute.csv --expected-exchange bitget_perpetual --min-samples 10`
- Rollback:
  1. Stop strategy (`stop` in bot terminal).
  2. Switch to paper profile:
     - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bitget_paper_smoke.yml`
  3. If needed, recreate bot container and clear cache:
     - `python scripts/release/dev_workflow.py clear-pyc --bot bot1`
     - `docker compose --env-file ../env/.env -f compose/docker-compose.yml up -d --force-recreate bot1`

## Bitget Live Incident Taxonomy (Day 15)
- `bitget_disconnect`: websocket/API session drops or reconnect storms.
- `bitget_order_reject`: exchange rejects due to precision, min-size, margin, or mode mismatch.
- `bitget_ack_timeout`: delayed or missing order ack/update in expected SLA.
- `bitget_position_mode_mismatch`: runtime position mode differs from expected ONEWAY/HEDGE config.
- `bitget_funding_or_fee_drift`: realized fee/funding diverges from expected profile.

## Stale `.pyc` Cache Fix

When modifying mounted controller files (`epp_v2_4.py` etc.), the container's
Python bytecache may serve the old version. `docker restart` does NOT clear it.

Fix:
```bash
docker exec kzay-capital-bot1 rm -rf /home/hummingbot/controllers/__pycache__ \
    /home/hummingbot/controllers/market_making/__pycache__
docker compose --env-file ../env/.env -f docker-compose.yml up -d --force-recreate bot1
```

For other bots, replace `kzay-capital-bot1` / `bot1` with the affected bot container
and compose service name (`bot2`, `bot3`, `bot4`, or `bot5`).

## Checklist
- Connector ready
- No growing errors.log
- Audit stream populated
- Dead-letter volume acceptable

## Owner
- Operations
- Last-updated: 2026-02-20


## Dashboard Operations

### Startup

1. Start monitoring services:
   - `docker compose --env-file ../env/.env up -d prometheus grafana node-exporter cadvisor bot-metrics-exporter loki promtail`
2. Verify Prometheus target health (`/targets`) and datasource health in Grafana.
3. Open dashboards:
   - `Kzay Capital Trading Desk`
   - `Kzay Capital Bot Deep Dive`
   - `Trading Desk Control Plane`
   - `Trading Desk Wallet and Blotter`
   - `Trading Desk Ops DB Overview`

### Validation Checklist

- `bot-metrics` target is `UP`.
- Loki datasource responds and log panels return records.
- Per-bot KPI panels refresh in <30s.
- Alert rules loaded without errors in Prometheus (`/rules`).
- At least one controlled alert test performed (e.g., stop a bot container to trigger alert).

## Ops Database (Day 25)
PostgreSQL operational store:
- Policy/runbook:
  - `docs/ops/postgres_ops_store_v1.md`

Startup:
1. `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml up -d postgres`
2. `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml ps postgres`
3. Optional `pgadmin`:
   - `docker compose --env-file env/.env --profile ops --profile ops-tools -f compose/docker-compose.yml up -d pgadmin`
4. Start writer:
   - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml up -d ops-db-writer`

Sanity check:
- `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml exec -T postgres psql -U kzay_capital -d kzay_capital_ops -c "select now() as ts_utc;"`
- one-shot writer check:
  - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml run --rm ops-db-writer python /workspace/hbot/services/ops_db_writer/main.py --once`

Backup:
- `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml exec -T postgres pg_dump -U kzay_capital kzay_capital_ops > reports/ops_db/postgres_dump_latest.sql`

### Incident Triage (Trading)

1. Check bot state and net edge panels (running/soft_pause/hard_stop).
2. Inspect fee source panel (API vs fallback) before adjusting strategy thresholds.
3. Use Loki logs panel filtered by `bot` + `ERROR` for fast root-cause isolation.
4. Cross-check container restarts and host resource saturation in infrastructure dashboard.
