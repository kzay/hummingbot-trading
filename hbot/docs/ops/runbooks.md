# Runbooks

## Purpose
Operational SOPs for startup, shutdown, recovery, and controlled changes.

## Startup (external orchestration)
1. Validate `env/.env`.
2. Start:
   - `docker compose --env-file ../env/.env --profile multi --profile external up -d`
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

## Degraded Mode
- Redis down:
  - restart without `--profile external`
  - keep local HB safeguards active

## Rollback
- Revert to previous image/config snapshot.
- Run post-rollback health checks and log verification.

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
   - `docker compose --env-file ../env/.env --profile test up -d bot3 bot4`
3. Reserved scale slot:
   - `bot2` remains disabled unless an explicit policy revision is approved.

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
  - `docker exec hbot-bot1 rm -rf /home/hummingbot/controllers/__pycache__ /home/hummingbot/controllers/market_making/__pycache__`
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

1. For EPP v2.4 controllers, keep `connector_name: bitget_paper_trade` and
   `internal_paper_enabled: true`.
2. In `conf_client.yml`, ensure:
   - `paper_trade_exchanges: [bitget]`
   - `paper_trade_account_balance` includes realistic BTC/USDT balances.
3. For standalone scripts (bot3): use `bitget_paper_trade` in the `markets` dict
   and enable `paper_trade_exchanges: [bitget]` in `conf_client.yml`.
4. Start the bot and verify `status` includes paper diagnostics (`paper fills`,
   `rejects`, `avg_qdelay_ms`) plus controller regime/spread data.
5. If you need emergency rollback, set `internal_paper_enabled: false` and
   recreate the bot container.

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
docker exec hbot-bot1 rm -rf /home/hummingbot/controllers/__pycache__ \
    /home/hummingbot/controllers/market_making/__pycache__
docker compose --env-file ../env/.env -f docker-compose.yml up -d --force-recreate bot1
```

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
   - `Hummingbot Trading Desk Overview`
   - `Hummingbot Bot Deep Dive`
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
- `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml exec -T postgres psql -U hbot -d hbot_ops -c "select now() as ts_utc;"`
- one-shot writer check:
  - `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml run --rm ops-db-writer python /workspace/hbot/services/ops_db_writer/main.py --once`

Backup:
- `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml exec -T postgres pg_dump -U hbot hbot_ops > reports/ops_db/postgres_dump_latest.sql`

### Incident Triage (Trading)

1. Check bot state and net edge panels (running/soft_pause/hard_stop).
2. Inspect fee source panel (API vs fallback) before adjusting strategy thresholds.
3. Use Loki logs panel filtered by `bot` + `ERROR` for fast root-cause isolation.
4. Cross-check container restarts and host resource saturation in infrastructure dashboard.
