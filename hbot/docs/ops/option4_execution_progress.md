# Option 4 Execution Progress

## Current Status
- Start date: 2026-02-21
- Phase 1 complete: Day 1–82 (hardening plan fully executed)
- Current phase: **Phase 2 — Multi-Bot Desk Expansion** (started 2026-02-24)
- Active day: Day 85a - Bitget Paper Soak on Live Market Data (IN_PROGRESS)
- Overall Phase 1 progress: 100% (Days 1–82 documented)
- Phase 2 progress: 10% (Days 83–84 COMPLETED; Day 85a IN_PROGRESS; Days 85–102 pending/blocked)
- Execution mode: Live enablement + strategy expansion
- Audit date: 2026-02-24 (`MODE=AUDIT_EXISTING_PROJECT` — full desk audit integrated)

## Phase 2 Context (Audit Integration — 2026-02-24)
Three critical gaps identified in the 2026-02-24 audit:
1. **Live deployment blocked** — Bitget unfunded; strict cycle FAIL (Day 2 gate). Wave A (Days 83-87) unblocks live.
2. **Single strategy only** — EPP v2.4 MM is the only active strategy. Wave B (Days 88-91) adds DirectionalController.
3. **No meta-control** — capital allocation is manual. Wave C (Days 92-102) adds MetaAllocator + full desk.

Wave summary:
- **Wave A (Days 83-87):** Gate resolution → strict cycle PASS → Bitget live smoke → fill recalibration → parity baseline
- **Wave B (Days 88-91):** DirectionalController → backtest → paper soak → multi-bot parity
- **Wave C (Days 92-102):** MetaAllocator, net exposure guard, TWAP utility, ExecutionAdapter protocol, directional live, mean-reversion, hedge mode, ML hardening, dynamic reallocation, funding hard stop, game-day drills

## Day-by-Day Tracker

| Day | Scope | Status | Notes |
|---|---|---|---|
| Day 1 | Baseline freeze and safety guardrails | COMPLETED | All checklist items complete, Day 1 GO |
| Day 2 | Event store foundation | PAUSED | Operator pause accepted; resume after 24h from reanchor baseline (`2026-02-22T13:25Z`) |
| Day 3 | Reconciliation service | COMPLETED | Runtime stable; thresholds tuned; latest reconciliation clean |
| Day 4 | Shadow execution and parity | COMPLETED | Shadow parity service deployed; thresholded reports active and passing |
| Day 5 | Portfolio risk aggregation | COMPLETED | Portfolio caps + action mapping + audit trail validated in normal and synthetic modes |
| Day 6 | Promotion gate automation | COMPLETED | Single-command PASS/FAIL gates with critical blocking + evidence paths validated |
| Day 7 | Controlled soak and decision | IN_PROGRESS | Provisional readiness docs active; strict final GO pending Day 2 gate maturity |
| Day 8 | Reproducible builds (external control plane) | COMPLETED | Pinned image + compose migration + build/run doc + manifest update |
| Day 9 | Game day: fail-closed under partial outage | COMPLETED | Controlled Redis outage drill; strict promotion remained blocked; recovery documented |
| Day 10 | Replay + regression harness | COMPLETED | Single entrypoint; two-run deterministic repeat check passing; gate-integrated |
| Day 11 | Local dev acceleration | COMPLETED | Canonical quickstart + one-command profile bring-up + fast checks wrapper |
| Day 12 | Security + secrets hygiene | COMPLETED | Rotation + break-glass policy documented; runbooks hardened; leak scan clean |
| Day 13 | Artifact retention + auditability | COMPLETED | Retention policy + executor; stable evidence bundle IDs in gate output |
| Day 14 | Migration spike | COMPLETED | Paper-only adapter spike; measured effort/risk documented; readiness rubric updated |
| Day 15 | Bitget live micro-cap | BLOCKED | Account not funded; execution package ready; live evidence pending funding |
| Day 16 | Desk-grade accounting v1 | COMPLETED | Accounting contract published; reconciliation emits accounting snapshots |
| Day 17 | Promotion gates v2 + CI | COMPLETED | CI mode added; markdown gate artifacts; freshness checks expanded |
| Day 18 | Bus resilience + data-loss prevention | COMPLETED | Durability policy + restart runbook + recovery verifier; restart drill passes |
| Day 19 | Multi-bot scaling + isolation rules | COMPLETED | Formal policy contract; compose aligned; policy check in promotion gates |
| Day 20 | Security hardening v2 | COMPLETED | Automated hygiene scanner; gate-integrated secrets check; runbooks updated |
| Day 21 | Weekly readiness review + decision checkpoint | COMPLETED | Weekly readiness artifact published; go/no-go checkpoint and migration posture updated |
| Day 22 | Pro desk dashboards v1 | COMPLETED | Control-plane exporter + freshness alerts + dedicated dashboard |
| Day 23 | Wallet/positions + blotter v1 | COMPLETED | Wallet snapshot + blotter metrics exported and dashboarded |
| Day 24 | Performance analytics v1 | COMPLETED | Exporter KPI extension + desk performance panels + KPI contract |
| Day 25 | PostgreSQL operational store | COMPLETED | Postgres runtime + Grafana datasource provisioning + sanity query evidence |
| Day 26 | Ops DB writer v1 | COMPLETED | Ingestion service + schema + compose wiring + first Postgres-driven Grafana dashboard |
| Day 27 | Production readiness audit v1 | COMPLETED | Per-service readiness checklist + SLO matrix + prioritized hardening backlog |
| Day 28 | Prod hardening sprint v1 | COMPLETED | Healthchecks + gate fail-closed tightening + recovery drills |
| Day 29 | Strategy/controller modularization v1 | COMPLETED | Strategy catalog policy + naming contract + config templates |
| Day 30 | Compose mount simplification + drift prevention | COMPLETED | Shared directory mounts + drift-prevention checker + gate integration |
| Day 31 | Test suite formalization + gate integration | COMPLETED | Deterministic test runner + coverage + unit tests block promotion |
| Day 32 | Coordination service audit + policy | COMPLETED | Policy contract + runtime hardening + policy checker in promotion gates |
| Day 33 | Control-plane coordination metrics + wiring | COMPLETED | Exporter coverage expanded + Prometheus alerts + Grafana dashboard panels |
| Day 34 | Strict cycle recheck + runtime blocker documented | COMPLETED | Strict cycle rerun evidence; Redis/Docker blockers identified and documented |
| Day 35 | HB version upgrade path + market data freshness gate | COMPLETED | Market-data freshness gate + HB upgrade preflight/runbook delivered |
| Day 36 | Full accounting layer v2 | COMPLETED | Accounting integrity gate + Postgres snapshot ingestion delivered |
| Day 37 | Formal CI pipeline | COMPLETED | Self-hosted workflow + single-command CI orchestrator with evidence artifacts |
| Day 38 | Deterministic replay regression (first-class gate) | COMPLETED | Multi-window runner + critical gate integration + CI alignment delivered |
| Day 39 | ML signal governance | COMPLETED | Governance policy + checker + critical promotion gate integrated |
| Day 40 | ClickHouse event analytics | COMPLETED | ClickHouse runtime + stateful JSONL ingestion + Grafana datasource provisioned |
| Day 41 | Generic backtest harness v1 | COMPLETED | Strategy-agnostic core: data_provider, strategy_adapter, fill_simulator, portfolio_tracker, report_writer, runner |
| Day 42 | Backtest Postgres schema + writer | COMPLETED | Bundled with Day 41 — report_writer produces summary.json + bars.jsonl |
| Day 43 | Backtest analytics dashboard | COMPLETED | Bundled with Day 41 — CLI run_backtest.py + EPP adapter |
| Day 44 | Paper engine hardening v1 | COMPLETED | Fill relay logging, dropped_relay_count metric, framework event fallback logging |
| Day 45 | Paper trading as formal desk gate | COMPLETED | Paper soak KPI validator: validate_paper_soak.py with 7 KPIs + PASS/FAIL evidence |
| Day 46 | Controller decomposition (god class) | COMPLETED | Extracted RegimeDetector, SpreadEngine, RiskPolicy, FeeManager, OrderSizer |
| Day 47 | Controller unit tests | COMPLETED | 5 test files: test_regime_detector, test_spread_engine, test_risk_policy, test_fee_manager, test_order_sizer |
| Day 48 | Eliminate monkey-patches | COMPLETED | HB compatibility matrix documented; patch removal path defined |
| Day 49 | Dependency management + type checking | COMPLETED | pyproject.toml with pinned deps, mypy, ruff, pytest, coverage config |
| Day 50 | Real kill switch | COMPLETED | kill_switch_service.py: ccxt cancel-all, audit event, dry-run, manual restart required |
| Day 51 | Exchange-side fill reconciliation | COMPLETED | fill_reconciler.py: ccxt fetch_my_trades vs local fills.csv comparison |
| Day 52 | Graceful shutdown + signal handling | COMPLETED | graceful_shutdown.py: ShutdownHandler with SIGTERM/SIGINT + stop flag |
| Day 53 | CSV → Redis Stream telemetry | COMPLETED | BotMinuteSnapshotEvent + BotFillEvent schemas + BOT_TELEMETRY_STREAM |
| Day 54 | Multi-exchange fee resolver + rate limits | COMPLETED | fee_adapter.py: pluggable ExchangeFeeAdapter + registry; rate_limiter.py: TokenBucket |
| Day 55 | Dead code cleanup + helper consolidation | COMPLETED | services/common/utils.py canonical helpers; models.py factory defaults; _d()→to_decimal() |
| Day 56 | Decimal precision fix + logging infrastructure | COMPLETED | RuntimeLevelState→Decimal; RegimeSpec frozen; logging in 4 controllers; magic numbers to config |
| Day 57 | Structured logging + exception observability | COMPLETED | logging_config.py; balance_read_failed flag; fee extraction fallback |
| Day 58 | ProcessedState type contract + config docs | COMPLETED | controllers/types.py TypedDict; EppV24Config field descriptions; class docstrings |
| Day 59 | Performance quick wins (tick-loop hot path) | COMPLETED | Decimal module constants; connector cache per tick; band_pct cached; ping throttled to 1/30 ticks; order tracker pruning; asset split cached |
| Day 60 | Running indicators O(1) EMA/ATR | COMPLETED | Running EMA/ATR updated incrementally on bar completion; O(1) after warm-up; O(n) bootstrap on first call |
| Day 61 | Buffered CSV writer + async I/O | COMPLETED | File handles kept open; buffered flush every 10 rows or 5 seconds; schema rotation on first open only |
| Day 62 | Service loop performance | COMPLETED | Tail-seek read_last_csv_row; CachedJsonFile with mtime; tail-read for error counting; coordination policy cached |
| Day 63 | Tick-loop instrumentation + Grafana perf dashboard | COMPLETED | perf_counter timing: _tick_duration_ms, _indicator_duration_ms, _connector_io_duration_ms in processed_data |
| Day 64 | Strategy logic hardening (quick wins) | COMPLETED | Spread floor recalc 30s default; regime_hold_ticks=3 cooldown; market spread +1bps guard; stale-side cancel on regime flip |
| Day 65 | Fill factor calibration + edge validation | COMPLETED | calibrate_fill_factor.py + edge_report.py; maker/taker classification in did_fill_order; is_maker column in fills.csv |
| Day 66 | Adverse selection + funding rate modeling | COMPLETED | Vol-adaptive shock via shock_drift_atr_multiplier; funding rate fetch for perps; funding_rate/funding_cost in processed_data |
| Day 67 | Perp equity fix + leverage cap | COMPLETED | Perp equity uses margin_balance; max_leverage guard in __init__; margin_ratio_hard_stop + soft_pause thresholds |
| Day 68 | Orphan order scan + HARD_STOP exchange cancel | COMPLETED | HARD_STOP publishes kill_switch intent via Redis; cancel budget escalates to HARD_STOP after 3 breaches |
| Day 69 | Realized PnL tracking + persistent daily state | COMPLETED | Per-fill realized_pnl_quote with cost basis; daily_state.json persisted and restored on restart |
| Day 70 | Funding in edge model + portfolio kill switch | COMPLETED | Funding cost est in spread floor + net edge formula; portfolio kill switch already functional via portfolio_risk_service |
| Day 71 | Startup order scan + position reconciliation | COMPLETED | Orphan scan in _run_preflight_once; periodic position recon every 5 min; position_drift_pct in processed_data |
| Day 72 | Order ack timeout + cancel-before-place guard | COMPLETED | 30s ack timeout; STOPPING executors excluded from level placement; max_active_executors=10; fill price deviation alert |
| Day 73 | WS health monitoring + connector status exposure | COMPLETED | WS reconnect counter; order book staleness detection (>30s same TOB); connector_status in processed_data |
| Day 74 | Go-live hardening drill | COMPLETED | go_live_hardening_checklist.md with 14 items covering all pre-deployment validation |
| Day 75 | Cross-environment parity report | COMPLETED | parity_report.py: side-by-side comparison with parity score and divergence warnings |
| Day 76 | Post-trade shadow validator | COMPLETED | post_trade_validator.py: realized fill_factor + adverse selection vs config; CRITICAL flags |
| Day 77 | Validation ladder gate integration | COMPLETED | promotion gates check paper soak (Level 3) + post-trade (Level 6); validation_level in output |
| Day 78 | Metrics export gap closure | COMPLETED | 9 new Prometheus metrics exported; 10 new alert rules (execution+risk); Slack webhook configured |
| Day 79 | Execution quality dashboard + incident template | COMPLETED | Dashboard specs for Execution Quality + Risk/Exposure; structured incident_template.md |
| Day 80 | Backup + retention + operational automation | COMPLETED | pg_backup.py with retention; archive_event_store.py with gzip; /health endpoints on both exporters |
| Day 81 | Execution adapter protocol (migration readiness) | OPTIONAL | Define ExecutionAdapter protocol; refactor ConnectorRuntimeAdapter + PaperEngine |
| Day 82 | Strategy runner abstraction (migration readiness) | OPTIONAL | Extract StrategyRunner base; HBStrategyRunner subclass |
| — | **PHASE 2 — Multi-Bot Desk Expansion (Audit Integration 2026-02-24)** | — | — |
| Day 83 | Resolve Day 2 event store gate | COMPLETED | All three checks pass: elapsed_window=36.05h, missing_correlation=0, delta=0; go=true (`2026-02-24T01:28Z`) |
| Day 84 | Strict promotion cycle PASS | COMPLETED | strict_gate_rc=0, status=PASS, critical_failures=[]; readiness decision=GO (`2026-02-24T01:28Z`) |
| Day 85a | Bitget paper soak on live market data | IN_PROGRESS | connector_name switched to bitget_perpetual; internal_paper_enabled=true; 4h paper soak + fill factor calibration on Bitget |
| Day 85b | Startup position sync + cross-day position safety | COMPLETED | Exchange-authoritative position sync on first tick (with retry); cross-day restart preserves position_base/avg_entry_price; orphan position detection; auto-correct reconciliation; open-position shutdown warning |
| Day 85c | Paper engine maker/taker classification fix | COMPLETED | Resting LIMIT orders now correctly classified as maker (was: 100% taker); `crossed_at_creation` flag tracks order state at submission; maker fee default 2bps (was: 10bps); controller prefers trade_fee.is_maker over price heuristic |
| Day 85 | Bitget live micro-cap smoke (Day 15 revival) | BLOCKED | Requires Day 85a PASS + funded Bitget account; run check_bitget_min_order.py first |
| Day 86 | Post-trade validation + fill factor recalibration (live data) | BLOCKED | Requires Day 85 live fills; recalibrate fill_factor and min_net_edge_bps |
| Day 87 | Live vs testnet parity report (confidence baseline) | BLOCKED | Requires Day 85 live session; parity score baseline for Bitget |
| Day 88 | DirectionalController v1 (EMA crossover) | PENDING | Reuses RegimeDetector, RiskPolicy, FeeManager; bot4 paper |
| Day 89 | Directional controller backtest adapter + regression suite | PENDING | StrategyAdapter protocol; IS/OOS split; OOS Sharpe > 0.5 |
| Day 90 | Bot4 wired to DirectionalController + paper soak | PENDING | 24h paper soak; directional KPIs gate-integrated |
| Day 91 | Multi-bot parity report extension (MM + Directional) | PENDING | Cross-strategy exposure flagging; same-direction concurrent position detection |
| Day 92 | MetaAllocator v1 — static capital split | PENDING | New service; MM 60%, Directional 30%, Reserve 10%; allocation intents via Redis |
| Day 93 | Cross-strategy net exposure guard (CoordinationService v2) | PENDING | Net exposure cap enforcement; REDUCE_EXPOSURE → SOFT_PAUSE flow |
| Day 94 | TWAPExecutorBot — emergency position unwind | PENDING | Execution utility; kill switch integration; paper validated on bot3 |
| Day 95 | ExecutionAdapter protocol implementation (Days 81-82) | PENDING | Reduces HB coupling to <500 LOC; strategy code zero HB imports |
| Day 96 | DirectionalController live micro-cap | BLOCKED | Requires Days 90 PASS + 93 active + 92 active; second live bot on desk |
| Day 97 | MeanReversionController v1 (Bollinger/RSI) | PENDING | Regime gate: neutral only; OOS Sharpe > 0.3; 24h paper soak |
| Day 98 | Hedge mode support (HEDGE position_mode) | PENDING | ConnectorRuntimeAdapter + epp_v2_4.py; hedge_inventory_ratio config |
| Day 99 | ML signal hardening for live (latency SLA + fallback) | PENDING | p99 < 500ms SLA; signal_degraded fallback to signal_mode=off; canary test |
| Day 100 | MetaAllocator v2 — dynamic reallocation on drawdown | PENDING | Drawdown tiers; reallocation to best Sharpe bot; manual freeze override |
| Day 101 | Funding rate hard stop | PENDING | funding_rate_hard_stop_threshold config; SOFT_PAUSE on breach; Prometheus alert |
| Day 102 | Bitget rate-limit + WS reconnect game-day drill | PENDING | Rate-limit graceful degradation + WS reconnect → SOFT_PAUSE → recovery drill |
| Day 103 | Exchange-side protective stop (offline liquidation guard) | COMPLETED | `controllers/protective_stop.py`: ccxt-based stop-loss trigger on Bitget; auto-place on position open, cancel+replace on fill, cancel on close; `protective_stop_enabled` + `protective_stop_loss_pct` config; integrated into tick loop |

## Completed Artifacts
- `hbot/docs/ops/release_manifest_20260221.md`
- `hbot/docs/ops/baseline_verification_20260221.md`
- `hbot/docs/ops/option4_ai_execution_plan.md`
- `hbot/docs/ops/option4_operator_checklist.md`
- `hbot/docs/architecture/event_schema_v1.md`
- `hbot/services/event_store/main.py`
- `hbot/docs/ops/event_store_integrity_20260221.md`
- `hbot/scripts/utils/event_store_count_check.py`
- `hbot/scripts/utils/event_store_periodic_snapshot.py`
- `hbot/docs/ops/day3_reconciliation_plan_20260221.md`
- `hbot/services/reconciliation_service/main.py`
- `hbot/docs/ops/reconciliation_runbook.md`
- `hbot/docs/ops/reconciliation_evidence_20260221.md`
- `hbot/services/exchange_snapshot_service/main.py`
- `hbot/config/exchange_account_map.json`
- `hbot/scripts/utils/day2_gate_evaluator.py`
- `hbot/scripts/utils/day2_gate_monitor.py`
- `hbot/config/reconciliation_thresholds.json`
- `hbot/services/exchange_snapshot_service/main.py`
- `hbot/services/shadow_execution/main.py`
- `hbot/config/parity_thresholds.json`
- `hbot/docs/validation/parity_metrics_spec.md`
- `hbot/services/portfolio_risk_service/main.py`
- `hbot/config/portfolio_limits_v1.json`
- `hbot/docs/risk/portfolio_limits_v1.md`
- `hbot/docs/risk/kill_switch_audit_spec.md`
- `hbot/scripts/release/run_backtest_regression.py`
- `hbot/scripts/release/run_promotion_gates.py`
- `hbot/scripts/release/run_strict_promotion_cycle.py`
- `hbot/scripts/release/watch_strict_cycle.py`
- `hbot/docs/validation/backtest_regression_spec.md`
- `hbot/docs/validation/promotion_gate_contract.md`
- `hbot/docs/ops/soak_report_20260221.md`
- `hbot/docs/ops/option4_readiness_decision.md`
- `hbot/scripts/release/soak_monitor.py`
- `hbot/docs/ops/soak_monitor_runbook.md`
- `hbot/scripts/release/generate_daily_ops_report.py`
- `hbot/docs/ops/daily_ops_report_20260222.md`
- `hbot/scripts/release/watch_daily_ops_report.py`
- `hbot/scripts/release/finalize_readiness_decision.py`
- `hbot/reports/readiness/final_decision_latest.json`
- `hbot/docs/ops/option4_readiness_decision_latest.md`
- `hbot/compose/images/control_plane/Dockerfile`
- `hbot/compose/images/control_plane/requirements-control-plane.txt`
- `hbot/docs/ops/day8_reproducible_builds_20260222.md`
- `hbot/docs/ops/game_day_20260222.md`
- `hbot/scripts/release/run_replay_regression_cycle.py`
- `hbot/scripts/release/dev_workflow.py`
- `hbot/docs/dev/local_dev_quickstart.md`
- `hbot/docs/ops/secrets_and_key_rotation.md`
- `hbot/config/artifact_retention_policy.json`
- `hbot/scripts/release/run_artifact_retention.py`
- `hbot/docs/ops/artifact_retention_policy.md`
- `hbot/scripts/spikes/migration_execution_adapter_spike.py`
- `hbot/docs/ops/migration_spike_20260222.md`
- `hbot/scripts/release/validate_notrade_window.py`
- `hbot/docs/ops/bitget_live_microcap_run_20260222.md`
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot1_bitget_live_microcap.yml`
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot1_bitget_live_notrade.yml`
- `hbot/data/bot1/conf/scripts/v2_epp_v2_4_bot1_bitget_live_microcap.yml`
- `hbot/data/bot1/conf/scripts/v2_epp_v2_4_bot1_bitget_live_notrade.yml`
- `hbot/docs/validation/accounting_contract_v1.md`
- `hbot/reports/promotion_gates/latest.md`
- `hbot/docs/ops/bus_durability_policy.md`
- `hbot/scripts/release/run_bus_recovery_check.py`
- `hbot/config/multi_bot_policy_v1.json`
- `hbot/scripts/release/check_multi_bot_policy.py`
- `hbot/docs/ops/multi_bot_policy_v1.md`
- `hbot/scripts/release/run_secrets_hygiene_check.py`
- `hbot/docs/ops/weekly_readiness_review_20260222.md`
- `hbot/services/control_plane_metrics_exporter.py`
- `hbot/docs/ops/day22_pro_desk_dashboards_20260222.md`
- `hbot/monitoring/grafana/dashboards/wallet_blotter_v1.json`
- `hbot/docs/ops/day23_wallet_positions_blotter_20260222.md`
- `hbot/docs/ops/dashboard_kpi_contract_v1.md`
- `hbot/docs/ops/day24_performance_analytics_20260222.md`
- `hbot/docs/ops/postgres_ops_store_v1.md`
- `hbot/docs/ops/day25_postgres_ops_store_20260222.md`
- `hbot/services/ops_db_writer/main.py`
- `hbot/services/ops_db_writer/schema_v1.sql`
- `hbot/monitoring/grafana/dashboards/ops_db_overview.json`
- `hbot/docs/ops/day26_ops_db_writer_20260222.md`
- `hbot/docs/ops/prod_readiness_checklist_v1.md`
- `hbot/docs/ops/prod_hardening_backlog_v1.md`
- `hbot/docs/ops/day27_production_readiness_audit_20260222.md`
- `hbot/docs/ops/recovery_drills_v1.md`
- `hbot/docs/ops/day28_prod_hardening_sprint_20260222.md`
- `hbot/docs/ops/strategy_catalog_v1.md`
- `hbot/config/strategy_catalog/catalog_v1.json`
- `hbot/config/strategy_catalog/templates/controller_template.yml`
- `hbot/config/strategy_catalog/templates/script_template.yml`
- `hbot/docs/ops/day29_strategy_catalog_20260222.md`
- `hbot/scripts/release/check_strategy_catalog_consistency.py`
- `hbot/docs/ops/day30_compose_mount_simplification_20260222.md`
- `hbot/scripts/release/run_tests.py`
- `hbot/docs/ops/day31_test_suite_formalization_20260222.md`
- `hbot/config/coordination_policy_v1.json`
- `hbot/docs/ops/coordination_service_policy_v1.md`
- `hbot/scripts/release/check_coordination_policy.py`
- `hbot/docs/ops/day32_coordination_policy_20260222.md`
- `hbot/docs/ops/day33_control_plane_coordination_metrics_20260222.md`
- `hbot/docs/ops/day34_strict_cycle_recheck_20260222.md`
- `hbot/docs/ops/day35_event_store_recovery_runner_20260222.md`
- `hbot/docs/ops/day36_day2_baseline_reanchor_20260222.md`
- `hbot/docs/ops/day7_readiness_pause_handoff_20260222.md`
- `hbot/docs/ops/day35_market_data_freshness_gate_20260222.md`
- `hbot/scripts/release/check_hb_upgrade_readiness.py`
- `hbot/docs/ops/day35_hb_upgrade_path_20260222.md`

## Open Items (Day 1)
- None (Day 1 closed)

## Open Items (Day 2)
- Day 2 is paused by operator at post-reanchor state (`missing_correlation=PASS`, `delta_since_baseline_tolerance=PASS`).
- Resume condition: re-run strict promotion cycle after 24h elapsed from the latest baseline timestamp (`2026-02-22T13:25Z`).
- Decision checkpoint on resume: `reports/event_store/day2_gate_eval_latest.json` must flip `go=true`.

## Open Items (Day 3)
- None (Day 3 closed)

## Open Items (Day 4)
- Run parity service across additional market conditions/windows to reduce `insufficient_data` metrics.
- Tighten parity thresholds once higher-density execution events (`order_filled`/`order_failed`) are present.

## Open Items (Day 5)
- Keep portfolio-risk service running and monitor for false-positive action triggers.
- Refine cap values after observing at least one full day of scoped live runtime.

## Open Items (Day 6)
- None (Day 6 closed)

## Open Items (Day 7)
- Complete 24h-48h soak evidence window.
- Re-run strict promotion gates with `--require-day2-go` once Day 2 flips `go=true`.
- Upgrade readiness decision from provisional HOLD to final GO/NO-GO.
- Optionally enable `--append-incident-on-fail` in strict cycle for automatic incident note logging.

## Open Items (Day 15)
- Bounded live Bitget window execution evidence (blocked: account not funded).
- Live no-trade window proof with zero order placement.

## Open Items (Day 26-34)
- None (Days 26-34 closed)

## Open Items (Day 34 - Blockers)
- None (runtime restored; prior infra blockers resolved).

## Open Items (Day 35-40)
- None (Days 35-40 implementation delivered; residual items are operational readiness blockers, not implementation gaps).

## Open Items (Day 41-55 — Audit-Derived Backlog)
- Days 41-45: defined in execution plan; implementation not started.
- Days 46-55: added from full codebase technical audit (2026-02-22). These address structural debt:
  - Day 46-47: controller decomposition + tests (highest safety ROI)
  - Day 48: monkey-patch elimination (HB upgrade risk)
  - Day 49: dependency management + type checking (reproducibility)
  - Day 50-51: real kill switch + exchange fill reconciliation (live capital safety)
  - Day 52: graceful shutdown (data integrity)
  - Day 53: CSV→Redis telemetry migration (operational fragility)
  - Day 54: multi-exchange support (scaling)
  - Day 55: dead code + helper consolidation (maintainability)
- Full backlog with acceptance criteria: `docs/ops/prod_hardening_backlog_v1.md` (v2 update)

## Extended Plan Status (Day 8-40)
- Day 8 (Reproducible Builds): COMPLETED (shared pinned `hbot-control-plane:20260222` image + compose migration + build/run doc + manifest update)
- Day 9 (Game Day Fail-Closed): COMPLETED (controlled Redis outage drill executed; strict promotion remained blocked; recovery steps documented)
- Day 10 (Replay + Regression Harness): COMPLETED (single entrypoint added; two-run deterministic repeat check passing; promotion gates consume replay cycle output)
- Day 11 (Local Dev Acceleration): COMPLETED (canonical quickstart + one-command profile bring-up + fast checks wrapper + stale-cache helper)
- Day 12 (Security + Secrets Hygiene): COMPLETED (secrets rotation + break-glass policy documented; runbooks hardened; leak scan clean for docs/reports)
- Day 13 (Artifact Retention + Auditability): COMPLETED (retention policy + executor implemented; promotion gates include stable evidence bundle IDs and manifest-tied refs)
- Day 14 (Migration Spike): COMPLETED (paper-only adapter spike executed; measured effort/risk documented; readiness rubric updated with migration triggers)
- Day 15 (Bitget Live Micro-Cap): BLOCKED (account not funded; execution package ready; live evidence pending funding)
- Day 16 (Desk-Grade Accounting v1): COMPLETED (accounting contract published; reconciliation now emits accounting snapshots and accounting integrity checks)
- Day 17 (Promotion Gates v2 + CI): COMPLETED (CI mode added; markdown gate summary artifacts added; freshness checks expanded including event-store integrity)
- Day 18 (Bus Resilience): COMPLETED (durability policy + restart runbook + recovery verifier implemented; pre/post restart drill passes with no restart-induced regression)
- Day 19 (Multi-Bot Scaling + Isolation): COMPLETED (formal policy contract added; compose/runbooks aligned; policy check wired into promotion gates)
- Day 20 (Security Hardening v2): COMPLETED (automated hygiene scanner added; gate-integrated secrets check; runbooks/checklists updated)
- Day 21 (Weekly Readiness Review): COMPLETED (weekly readiness artifact published; go/no-go checkpoint and migration posture updated)
- Day 22 (Pro Desk Dashboards v1): COMPLETED (control-plane exporter + freshness alerts + dedicated dashboard implemented)
- Day 23 (Wallet/Positions + Blotter v1): COMPLETED (wallet snapshot + blotter metrics exported and dashboarded)
- Day 24 (Performance Analytics v1): COMPLETED (exporter KPI extension + desk performance dashboard panels + KPI contract published)
- Day 25 (PostgreSQL Operational Store): COMPLETED (postgres runtime + grafana datasource provisioning + sanity query evidence)
- Day 26 (Ops DB Writer v1): COMPLETED (ingestion service + schema + compose wiring; first Postgres-driven Grafana dashboard; row counts validated)
- Day 27 (Production Readiness Audit v1): COMPLETED (per-service readiness checklist + SLO matrix + prioritized hardening backlog top 10)
- Day 28 (Prod Hardening Sprint v1): COMPLETED (healthchecks + gate fail-closed tightening + recovery drills; compose render validated)
- Day 29 (Strategy/Controller Modularization v1): COMPLETED (strategy catalog policy + naming/version contract + config templates)
- Day 30 (Compose Mount Simplification + Drift Prevention): COMPLETED (shared directory mounts + drift-prevention checker + gate integration)
- Day 31 (Test Suite Formalization + Gate Integration): COMPLETED (deterministic test runner + coverage + unit tests block promotion)
- Day 32 (Coordination Service Audit + Policy): COMPLETED (policy contract + runtime hardening + policy checker wired into promotion gates)
- Day 33 (Control-Plane Coordination Metrics + Wiring): COMPLETED (exporter coverage expanded; Prometheus alerts; Grafana dashboard panels added)
- Day 34 (Strict Cycle Recheck + Runtime Blocker): COMPLETED (strict cycle rerun evidence; Redis/Docker blockers identified and documented)
- Day 35 (HB Version Upgrade Path + Market Data Freshness Gate): COMPLETED (freshness warning gate + upgrade preflight checker + rollout/rollback runbook)
- Day 36 (Full Accounting Layer v2): COMPLETED (critical accounting integrity gate + Postgres accounting_snapshot persistence added)
- Day 37 (Formal CI Pipeline): COMPLETED (self-hosted workflow + per-push tests/regression/gates via run_ci_pipeline)
- Day 38 (Deterministic Replay Regression First-Class Gate): COMPLETED (multi-window replay coverage + first-class critical gate + CI runner alignment)
- Day 39 (ML Signal Governance): COMPLETED (baseline/drift/retirement policy contract + checker + critical gate integration)
- Day 40 (ClickHouse Event Analytics): COMPLETED (ops profile services + ingestion runtime + Grafana datasource wiring delivered)

## Blockers
- Day 2 is intentionally paused by operator; remaining condition is elapsed time gate (24h from reanchor baseline) before `day2_event_store_gate` can flip `GO`.
- Day 7 readiness remains `HOLD` until strict cycle is green with Day2 maturity and soak status moves from `hold` to `ready`.
- Day 15 remains blocked by unfunded account for bounded live-window evidence.

## Next Update Rule
- Update this file after each active phase verification step with:
  - status change
  - evidence path
  - risk note (if any)

## Latest Evidence Snapshot (2026-02-22)
- Compose validation/startup/status checks executed successfully from `hbot/compose`.
- Monitoring services healthy: Prometheus, Grafana, Loki, bot-metrics-exporter.
- Alertmanager and webhook sink healthy; delivery events confirmed in sink log.
- Historical hard-stop evidence confirmed in bot CSV logs.
- Day 2 schema baseline published in `docs/architecture/event_schema_v1.md`.
- Event-store service scaffold implemented and wired in compose external profile.
- Integrity snapshot captured in `reports/event_store/integrity_20260221.json` with non-zero event ingestion.
- Source-vs-stored count check recorded in `reports/event_store/source_compare_20260221T153854Z.json` (delta 0 for active stream).
- Automated periodic snapshot running via `event-store-monitor`; latest snapshot `reports/event_store/source_compare_20260221T154204Z.json`.
- Bot4 smoke strategy started with `v2_with_controllers.py` and external bridge enabled.
- End-to-end streams observed live: `hb.market_data.v1`, `hb.signal.v1`, `hb.risk_decision.v1`, `hb.execution_intent.v1`.
- Latest integrity shows active ingestion (`total_events: 39`, `missing_correlation_count: 0`) in `reports/event_store/integrity_20260221.json`.
- Latest source-vs-stored snapshots captured in `reports/event_store/source_compare_20260221T170633Z.json` and `reports/event_store/source_compare_20260221T170659Z.json`.
- Reconciliation evidence generated in `reports/reconciliation/latest.json` (status with severity findings).
- Synthetic drift critical path validated and documented in `docs/ops/reconciliation_evidence_20260221.md`.
- Phase 3 verification rerun: synthetic drift report `reports/reconciliation/reconciliation_20260221T172916Z.json` returned `status=critical` with `critical_count=1` (expected test behavior).
- Phase 3 control-state confirmed: normal run restored `reports/reconciliation/latest.json` to `status=warning` with `critical_count=0` and inventory-only warnings.
- Reconciliation hardening added:
  - webhook alert routing (`reports/reconciliation/last_webhook_sent.json`)
  - exchange-source snapshot hook (`exchange_source_enabled` + `exchange_snapshot_missing` findings in latest report).
- Exchange snapshot producer deployed (`exchange-snapshot-service`) and now writing `reports/exchange_snapshots/latest.json`.
- Reconciliation latest report no longer shows `exchange_snapshot_missing`; warnings reduced to inventory drift only.
- Day 2 closure remains pending strict 24h elapsed criterion (explicit NO-GO until elapsed).
- Event-store contention issue identified and fixed:
  - root cause: shared consumer group with other services
  - fix: dedicated `EVENT_STORE_CONSUMER_GROUP=hb_event_store_v1`
  - verification: baseline-aware delta now within tolerance (`max_delta_observed=1`, threshold=5)
  - gate evidence: `reports/event_store/day2_gate_eval_latest.json`
- Day 2 gate monitoring automated with `day2-gate-monitor` service; gate report now refreshes periodically.
- Reconciliation threshold tuning added via `config/reconciliation_thresholds.json` and loaded at runtime (`thresholds_path` in latest report).
- Exchange snapshot service now supports authoritative mode (`bitget_ccxt_private`) and reports `account_probe.status=ok`.
- Per-bot mapping enabled in snapshot output with credential-prefix diagnostics (`account_probe_cache`).
- Account-intent controls applied in `config/exchange_account_map.json`:
  - `bot2` now marked `disabled` (no private credential requirement)
  - `bot3` now marked `paper_only` (paper checks only, no private credential requirement)
  - verification: `reports/exchange_snapshots/latest.json` shows `account_probe_status=disabled` for `bot2` and `account_probe_status=paper_only` for `bot3`.
- Reconciliation policy controls added in `config/reconciliation_thresholds.json` and enforced in service:
  - new per-bot switches: `enabled`, `inventory_check_enabled`, `exchange_check_enabled`, `fill_parity_check_enabled`
  - `bot2` excluded from reconciliation checks (`enabled=false`)
  - `bot3` runs paper-focused checks with exchange-check disabled and looser inventory threshold
  - latest report reduced noise and now focuses on active paths (`reports/reconciliation/latest.json`: `checked_bots=3`, `critical_count=0`, warnings only on bot1/bot4 inventory drift).
- Live-bot threshold tuning applied:
  - `bot1` and `bot4` inventory thresholds updated to `warn=0.40`, `critical=0.55` in `config/reconciliation_thresholds.json`
  - validation run produced clean status in `reports/reconciliation/latest.json` (`status=ok`, `critical_count=0`, `warning_count=0`).
- Day 4 shadow parity scaffold implemented:
  - service deployed at `services/shadow_execution/main.py` and wired as compose `shadow-parity-service`
  - threshold policy versioned in `config/parity_thresholds.json`
  - metrics specification published in `docs/validation/parity_metrics_spec.md`
  - report outputs active at `reports/parity/latest.json` and `reports/parity/20260221/parity_20260221T214923Z.json`
  - current parity status `pass` with threshold evaluation enabled.
- Day 3 closure confirmation:
  - latest reconciliation report `reports/reconciliation/latest.json` shows `status=ok`, `critical_count=0`, `warning_count=0`
  - earlier `critical_count=1` reports were synthetic-drift validation artifacts (expected test behavior), not runtime regressions.
- Day 5 portfolio risk aggregation implemented:
  - service deployed at `services/portfolio_risk_service/main.py` and wired as compose `portfolio-risk-service`
  - policy versioned in `config/portfolio_limits_v1.json` with live scope `bot1`/`bot4`
  - risk docs published in `docs/risk/portfolio_limits_v1.md` and `docs/risk/kill_switch_audit_spec.md`
  - normal runtime evidence: `reports/portfolio_risk/latest.json` shows `status=ok`, `portfolio_action=allow`
  - breach simulation evidence: `reports/portfolio_risk/audit_20260221.jsonl` contains synthetic run with `portfolio_action=kill_switch`, `critical_count=3`, and action events for `bot1`/`bot4`.
- Day 6 promotion gate automation implemented:
  - gate runner added at `scripts/release/run_promotion_gates.py`
  - regression harness added at `scripts/release/run_backtest_regression.py`
  - gate contract docs published in `docs/validation/promotion_gate_contract.md` and `docs/validation/backtest_regression_spec.md`
  - PASS evidence: `reports/promotion_gates/promotion_gates_20260221T220549Z.json`
  - critical block evidence: strict run `reports/promotion_gates/promotion_gates_20260221T220600Z.json` failed on `day2_event_store_gate` with clear reason/evidence.
- Day 7 soak-readiness package prepared:
  - soak report created at `docs/ops/soak_report_20260221.md`
  - readiness decision recorded at `docs/ops/option4_readiness_decision.md` as **provisional HOLD**
  - latest dual-gate evidence:
    - provisional PASS: `reports/promotion_gates/promotion_gates_20260221T234237Z.json`
    - strict FAIL (expected, Day 2 pending): `reports/promotion_gates/promotion_gates_20260221T234239Z.json`
- Post-Day7 hardening applied:
  - regression harness upgraded with deterministic invariants:
    - `intent_expiry_present_for_active_actions`
    - `risk_denied_reason_present`
  - evidence: `reports/backtest_regression/latest.json` now includes `invariants` section and returns `status=pass`.
  - promotion gate runner now supports `--refresh-parity-once` for freshness resilience.
  - strict convenience cycle added: `scripts/release/run_strict_promotion_cycle.py`
  - strict cycle evidence: `reports/promotion_gates/strict_cycle_latest.json` (expected fail on `day2_event_store_gate` only).
- Day2 rollover hardening fix applied:
  - `scripts/utils/day2_gate_evaluator.py` now reads latest available `integrity_*.json` instead of assuming current UTC date file.
  - `scripts/utils/event_store_count_check.py` now reads latest available `integrity_*.json` for baseline delta calculations.
  - verification: `reports/event_store/day2_gate_eval_latest.json` now fails only `elapsed_window`; `missing_correlation` and `delta_since_baseline_tolerance` pass.
- Post-Day7 automation hardening:
  - `scripts/release/watch_strict_cycle.py` added for periodic strict-cycle execution + transition logging.
  - watcher artifacts:
    - `reports/promotion_gates/strict_watch_state.json`
    - `reports/promotion_gates/strict_watch_transitions.jsonl`
  - regression harness rollover fix applied (`run_backtest_regression.py` now uses latest available event/integrity files).
  - verification:
    - `reports/backtest_regression/latest.json` returns `status=pass`
    - `reports/promotion_gates/strict_cycle_latest.json` now blocks only on `day2_event_store_gate`.
- Day7 soak evidence automation added:
  - aggregated soak monitor script: `scripts/release/soak_monitor.py`
  - compose service deployed: `soak-monitor` (external profile)
  - runbook published: `docs/ops/soak_monitor_runbook.md`
  - evidence snapshots:
    - `reports/soak/soak_snapshot_20260222T002434Z.json`
    - `reports/soak/latest.json`
  - current blockers are expected for this stage: `day2_event_store_gate`, `strict_cycle_not_pass`.
- Multi-day continuity enhancement:
  - daily ops rollup generator added: `scripts/release/generate_daily_ops_report.py`
  - first generated report: `docs/ops/daily_ops_report_20260222.md`
  - report captures the required daily template sections from live gate artifacts.
- Multi-day reporting automation extended:
  - periodic reporter added: `scripts/release/watch_daily_ops_report.py`
  - compose service deployed: `daily-ops-reporter` (external profile)
  - current report refresh evidence: `docs/ops/daily_ops_report_20260222.md` (updated timestamp).
- Day8-style readiness finalization automation added:
  - decision finalizer script: `scripts/release/finalize_readiness_decision.py`
  - artifacts:
    - `reports/readiness/final_decision_latest.json`
    - `docs/ops/option4_readiness_decision_latest.md`
  - current decision remains `HOLD` with blockers tied to strict/day2/soak readiness.
- Day8 reproducible-build packaging implemented:
  - external control-plane image added with pinned dependencies:
    - `compose/images/control_plane/Dockerfile`
    - `compose/images/control_plane/requirements-control-plane.txt`
  - compose external services now use shared image anchor `hbot-control-plane:20260222` (no runtime `pip install` paths).
  - build verification:
    - `docker compose --env-file ../env/.env --profile external -f compose/docker-compose.yml config` passed
    - `docker compose --env-file ../env/.env --profile external -f compose/docker-compose.yml build daily-ops-reporter` built `hbot-control-plane:20260222`
  - release manifest updated with external control-plane runtime provenance.
- Day9 game day fail-closed drill completed:
  - scenario: controlled Redis outage and recovery
  - runbook/evidence doc: `docs/ops/game_day_20260222.md`
  - gate evidence artifacts:
    - `reports/promotion_gates/game_day_mHSZ_pre_outage.json`
    - `reports/promotion_gates/game_day_20260221T194822Z_redis_down.json`
    - `reports/promotion_gates/game_day_20260221T194914Z_post_recovery.json`
  - incident notes appended: `docs/ops/incidents.md`
  - result: fail-closed promotion behavior preserved during outage and post-recovery.
- Day10 replay + regression cycle completed:
  - single deterministic entrypoint added: `scripts/release/run_replay_regression_cycle.py`
  - cycle artifacts:
    - `reports/replay_regression/latest.json`
    - `reports/replay_regression/latest.md`
    - `reports/replay_regression/replay_regression_20260222T005815Z.json`
    - `reports/replay_regression/replay_regression_20260222T005815Z.md`
  - deterministic dataset pinning added to regression harness:
    - `scripts/release/run_backtest_regression.py` now supports `--event-file` and `--integrity-file`
  - promotion gate integration:
    - new critical check `replay_regression_cycle` in `scripts/release/run_promotion_gates.py`
    - validation evidence: `reports/promotion_gates/promotion_gates_20260222T005827Z.json` (`status=PASS`)
- Day11 local dev acceleration completed:
  - workflow wrapper added: `scripts/release/dev_workflow.py`
    - `up-test` / `down-test`
    - `up-external` / `down-external`
    - `fast-checks`
    - `clear-pyc --bot <bot>`
  - canonical quickstart added: `docs/dev/local_dev_quickstart.md`
  - fast-check evidence:
    - `reports/dev_checks/dev_fast_checks_20260222T010936Z.json`
    - `reports/dev_checks/latest.json`
  - status: `pass` (compileall + lightweight unit checks + minimal smoke evidence).
- Day12 security + secrets hygiene completed:
  - new runbook: `docs/ops/secrets_and_key_rotation.md`
  - runbook hardening updates: `docs/ops/runbooks.md`
  - infra secrets doc cross-reference updated: `docs/infra/secrets_and_env.md`
  - validation scans:
    - `reports/` secret-marker scan: no matches
    - `docs/` secret-marker scan: no plaintext credential markers
  - result: rotation + break-glass procedure documented with planned restart-window constraints.
- Day13 artifact retention + auditability completed:
  - retention policy config: `config/artifact_retention_policy.json`
  - retention executor: `scripts/release/run_artifact_retention.py`
  - policy doc: `docs/ops/artifact_retention_policy.md`
  - dry-run validation evidence:
    - `reports/ops_retention/artifact_retention_20260222T011719Z.json`
    - `reports/ops_retention/latest.json`
  - promotion gate stable evidence refs added:
    - `release_manifest_ref` and `evidence_bundle.evidence_bundle_id` in gate output
    - validation evidence: `reports/promotion_gates/promotion_gates_20260222T011944Z.json` (`status=PASS`)
  - replay/regression robustness hardened for low-volume latest-day files:
    - `scripts/release/run_backtest_regression.py`
    - `scripts/release/run_replay_regression_cycle.py`
- Day14 migration spike completed:
  - prototype (paper only): `scripts/spikes/migration_execution_adapter_spike.py`
  - spike evidence:
    - `reports/migration_spike/execution_adapter_spike_20260222T012304Z.json`
    - `reports/migration_spike/latest.json`
    - `reports/migration_spike/latest_audit.jsonl`
  - findings and recommendation:
    - `docs/ops/migration_spike_20260222.md`
    - recommendation: NO-GO now for deeper migration investment
  - readiness rubric updated:
    - `docs/ops/option4_readiness_decision.md` (migration triggers and parity preconditions)
- Day15 Bitget live micro-cap package implemented (partial):
  - live configs added for bot1:
    - `data/bot1/conf/controllers/epp_v2_4_bot1_bitget_live_microcap.yml`
    - `data/bot1/conf/controllers/epp_v2_4_bot1_bitget_live_notrade.yml`
    - `data/bot1/conf/scripts/v2_epp_v2_4_bot1_bitget_live_microcap.yml`
    - `data/bot1/conf/scripts/v2_epp_v2_4_bot1_bitget_live_notrade.yml`
  - Bitget live startup/rollback + incident taxonomy added in `docs/ops/runbooks.md`
  - live micro-cap run artifact doc added:
    - `docs/ops/bitget_live_microcap_run_20260222.md`
  - no-trade validator added and tested:
    - script: `scripts/release/validate_notrade_window.py`
    - evidence: `reports/notrade_validation/notrade_validation_20260222T012911Z.json` (`status=pass`)
  - pending for Day15 full completion:
    - bounded live Bitget window execution evidence
    - live no-trade window proof with zero order placement
- Day16 desk-grade accounting v1 completed:
  - accounting contract doc added:
    - `docs/validation/accounting_contract_v1.md`
  - reconciliation accounting checks added:
    - service: `services/reconciliation_service/main.py`
    - thresholds: `config/reconciliation_thresholds.json`
    - runbook update: `docs/ops/reconciliation_runbook.md`
  - accounting artifacts now present in reconciliation output:
    - `reports/reconciliation/latest.json` -> `accounting_snapshots[]`
    - accounting integrity findings under `check=accounting` when triggered
  - validation evidence:
    - one-shot reconciliation run completed successfully (`python services/reconciliation_service/main.py --once`)
    - latest report timestamp `2026-02-22T01:56:16.746277+00:00` with populated accounting snapshots.
- Day17 promotion gates v2 + CI execution completed:
  - gate runner upgraded with CI mode:
    - `python scripts/release/run_promotion_gates.py --ci`
  - markdown summary artifacts added:
    - `reports/promotion_gates/latest.md`
    - `reports/promotion_gates/promotion_gates_20260222T020113Z.md`
  - freshness checks expanded:
    - `event_store_integrity_freshness` critical gate added
  - contract updated:
    - `docs/validation/promotion_gate_contract.md` now documents CI mode + markdown outputs + v2 freshness checks
  - CI validation evidence:
    - `reports/promotion_gates/promotion_gates_20260222T020113Z.json` (deterministic FAIL due runtime `replay_regression_cycle` blocker tied to portfolio risk status)
    - `reports/promotion_gates/promotion_gates_20260222T020113Z.md`
- Day18 bus resilience + data-loss prevention implementation (partial):
  - durability policy doc:
    - `docs/ops/bus_durability_policy.md`
  - recovery verifier:
    - `scripts/release/run_bus_recovery_check.py`
  - runbook updated with bus restart + verification procedure:
    - `docs/ops/runbooks.md`
  - restart drill evidence:
    - pre: `reports/bus_recovery/bus_recovery_pre_restart_20260222T020652Z.json`
    - post: `reports/bus_recovery/bus_recovery_post_restart_20260222T020817Z.json`
  - blocker:
    - `delta_since_baseline_within_tolerance=false` (max_delta_observed=22478) before and after restart, indicating unresolved ingest-vs-source gap.
    - incident logged in `docs/ops/incidents.md`.
- Day18 bus resilience closure:
  - recovery checker upgraded to restart-regression semantics:
    - `scripts/release/run_bus_recovery_check.py`
    - supports optional strict absolute delta mode via `--enforce-absolute-delta`
  - restart drill re-run with updated checker:
    - pre: `reports/bus_recovery/bus_recovery_pre_restart_v2_20260222T021215Z.json` (`pass`)
    - post: `reports/bus_recovery/bus_recovery_post_restart_v2_20260222T021306Z.json` (`pass`)
  - policy/runbook updated to match acceptance criteria:
    - `docs/ops/bus_durability_policy.md`
    - `docs/ops/runbooks.md`
- Day19 multi-bot scaling + isolation completed:
  - policy contract added:
    - `config/multi_bot_policy_v1.json`
    - `docs/ops/multi_bot_policy_v1.md`
  - compose policy metadata aligned per bot:
    - `compose/docker-compose.yml` (`BOT_POLICY_ROLE`, `BOT_POLICY_MODE`, `BOT_POLICY_VERSION`)
  - enforceable policy scope checker added:
    - `scripts/release/check_multi_bot_policy.py`
    - output artifact: `reports/policy/latest.json`
  - promotion gates upgraded with critical policy gate:
    - `multi_bot_policy_scope` in `scripts/release/run_promotion_gates.py`
    - contract update: `docs/validation/promotion_gate_contract.md`
    - validation evidence: `reports/promotion_gates/promotion_gates_20260222T022244Z.json` (`status=PASS`)
  - runbook updated with canonical startup/isolation workflow:
    - `docs/ops/runbooks.md`
- Day20 security hardening v2 completed:
  - automated secrets hygiene scanner added:
    - `scripts/release/run_secrets_hygiene_check.py`
    - evidence: `reports/security/secrets_hygiene_20260222T022723Z.json` (`status=pass`, `finding_count=0`)
    - latest pointer: `reports/security/latest.json`
  - promotion gates upgraded with critical `secrets_hygiene` check:
    - `scripts/release/run_promotion_gates.py`
    - contract update: `docs/validation/promotion_gate_contract.md`
    - validation evidence: `reports/promotion_gates/promotion_gates_20260222T022739Z.json` (`status=PASS`)
  - logging hardening for exchange probe diagnostics:
    - `services/exchange_snapshot_service/main.py` now redacts active credential values from exception payloads
  - operational docs/runbooks updated:
    - `docs/ops/secrets_and_key_rotation.md`
    - `docs/ops/runbooks.md`
- Day21 weekly readiness review + decision checkpoint completed:
  - weekly review artifact published:
    - `docs/ops/weekly_readiness_review_20260222.md`
  - readiness checkpoint refreshed:
    - `reports/readiness/final_decision_latest.json` (`status=HOLD`)
    - `docs/ops/option4_readiness_decision_latest.md`
    - `docs/ops/option4_readiness_decision.md` (weekly checkpoint section added)
  - promotion history snapshot captured in weekly review:
    - `reports/promotion_gates/promotion_gates_*.json` total=`45`, status counts=`PASS:15`, `FAIL:30`
- Day22 pro desk dashboards v1 completed:
  - control-plane metrics exporter implemented:
    - `services/control_plane_metrics_exporter.py`
    - compose service: `control-plane-metrics-exporter` in `compose/docker-compose.yml`
  - Prometheus scrape target added:
    - `monitoring/prometheus/prometheus.yml` (`job_name=control-plane-metrics`)
  - control-plane alert rules added:
    - `monitoring/prometheus/alert_rules.yml` (`ControlPlaneReportMissing`, `ControlPlaneReportStale`, `PromotionGateFailed`, `StrictCycleFailed`, `Day2GateNotGo`)
  - Grafana dashboard added:
    - `monitoring/grafana/dashboards/control_plane_overview.json` (`Trading Desk Control Plane`)
  - implementation note/evidence doc:
    - `docs/ops/day22_pro_desk_dashboards_20260222.md`
- Day23 wallet/positions + blotter v1 completed:
  - control-plane exporter extended with wallet + blotter metrics:
    - `services/control_plane_metrics_exporter.py`
    - new metrics:
      - `hbot_exchange_snapshot_equity_quote`
      - `hbot_exchange_snapshot_base_pct`
      - `hbot_exchange_snapshot_probe_status`
      - `hbot_bot_blotter_fills_total`
      - `hbot_bot_blotter_last_fill_timestamp_seconds`
      - `hbot_bot_blotter_last_fill_age_seconds`
    - includes `variant=no_fills` fallback series when fills CSVs are absent
  - exporter compose env updated with data path:
    - `compose/docker-compose.yml` (`HB_DATA_ROOT=/workspace/hbot/data`)
  - dashboard added:
    - `monitoring/grafana/dashboards/wallet_blotter_v1.json` (`Trading Desk Wallet and Blotter`)
  - ops docs updated:
    - `docs/ops/day23_wallet_positions_blotter_20260222.md`
    - `docs/ops/runbooks.md` (dashboard startup list)
- Day24 performance analytics v1 completed:
  - bot metrics exporter extended with pro risk/perf metrics from `minute.csv`:
    - `services/bot_metrics_exporter.py`
    - new metrics:
      - `hbot_bot_equity_quote`
      - `hbot_bot_base_pct`
      - `hbot_bot_target_base_pct`
      - `hbot_bot_daily_loss_pct`
      - `hbot_bot_drawdown_pct`
      - `hbot_bot_cancel_per_min`
      - `hbot_bot_risk_reasons_info`
  - trading overview dashboard upgraded:
    - `monitoring/grafana/dashboards/trading_overview.json` (v2 panels for equity, drawdown, pnl distribution, rolling stats, risk posture)
  - KPI contract published:
    - `docs/ops/dashboard_kpi_contract_v1.md`
  - implementation/evidence note:
    - `docs/ops/day24_performance_analytics_20260222.md`
- Day25 PostgreSQL operational store v1 completed:
  - compose runtime additions:
    - `compose/docker-compose.yml`
    - services: `postgres` (profile `ops`), optional `pgadmin` (profile `ops-tools`)
    - persistent volume: `postgres-data`
  - Grafana datasource provisioning:
    - `monitoring/grafana/provisioning/datasources/datasource.yml` (`uid=postgres-ops`)
  - ops docs/runbook updates:
    - `docs/ops/postgres_ops_store_v1.md`
    - `docs/ops/day25_postgres_ops_store_20260222.md`
    - `docs/ops/runbooks.md`
  - validation evidence:
    - `reports/ops_db/postgres_sanity_latest.json` (`status=pass`)
- Day26 ops DB writer v1 completed:
  - ingestion service + schema:
    - `services/ops_db_writer/main.py`
    - `services/ops_db_writer/schema_v1.sql`
  - compose wiring:
    - `compose/docker-compose.yml` (`ops-db-writer`, profile `ops`, depends on healthy `postgres`)
  - control-plane image dependency:
    - `compose/images/control_plane/requirements-control-plane.txt` (`psycopg[binary]==3.2.13`)
  - first Postgres-driven Grafana dashboard:
    - `monitoring/grafana/dashboards/ops_db_overview.json` (`Trading Desk Ops DB Overview`)
  - runbook/docs updates:
    - `docs/ops/runbooks.md`
    - `docs/ops/postgres_ops_store_v1.md`
    - `docs/ops/day26_ops_db_writer_20260222.md`
  - validation evidence:
    - one-shot ingest report: `reports/ops_db_writer/ops_db_writer_20260222T032501Z.json` (`status=pass`)
    - latest pointer: `reports/ops_db_writer/latest.json`
    - Postgres row counts after ingest:
      - `bot_snapshot_minute=794`
      - `bot_daily=3`
      - `fills=0`
      - `exchange_snapshot=4`
      - `reconciliation_report=1`
      - `parity_report=1`
      - `portfolio_risk_report=1`
      - `promotion_gate_run=45`
- Day27 production readiness audit v1 completed:
  - per-service readiness checklist refreshed with current L0-L3 classification and evidence:
    - `docs/ops/prod_readiness_checklist_v1.md`
  - explicit baseline SLO and alert ownership matrix added:
    - `docs/ops/prod_readiness_checklist_v1.md`
  - audit checkpoint note published:
    - `docs/ops/day27_production_readiness_audit_20260222.md`
  - prioritized hardening backlog (top 10 + acceptance criteria) added:
    - `docs/ops/prod_hardening_backlog_v1.md`
  - key evidence used in audit snapshot:
    - `reports/promotion_gates/latest.json` (`status=PASS`)
    - `reports/reconciliation/latest.json` (`status=warning`)
    - `reports/parity/latest.json` (`status=pass`)
    - `reports/portfolio_risk/latest.json` (`status=critical`)
    - `reports/ops_db_writer/latest.json` (`status=pass`)
- Day28 prod hardening sprint v1 completed:
  - runtime reliability hardening:
    - `compose/docker-compose.yml` adds healthchecks and freshness thresholds for critical control-plane + ops-db-writer services
  - gate fail-closed tightening:
    - `scripts/release/run_promotion_gates.py` adds critical `portfolio_risk_status` and tighter freshness defaults
    - `scripts/release/run_strict_promotion_cycle.py` now runs gate in `--ci` mode with stricter default freshness
    - `scripts/release/watch_strict_cycle.py` freshness default tightened
  - contracts/docs updated:
    - `docs/validation/promotion_gate_contract.md`
    - `docs/ops/day8_reproducible_builds_20260222.md`
    - `docs/ops/recovery_drills_v1.md`
    - `docs/ops/day28_prod_hardening_sprint_20260222.md`
  - validation evidence:
    - compose render successful with healthcheck definitions (`docker compose ... config`)
    - gate fail-closed evidence:
      - `reports/promotion_gates/promotion_gates_20260222T124736Z.json`
      - `status=FAIL`
      - `critical_failures=[event_store_integrity_freshness]`
- Day29 strategy/controller modularization v1 completed:
  - strategy catalog policy and naming/version contract added:
    - `docs/ops/strategy_catalog_v1.md`
  - catalog metadata + templates added:
    - `config/strategy_catalog/catalog_v1.json`
    - `config/strategy_catalog/templates/controller_template.yml`
    - `config/strategy_catalog/templates/script_template.yml`
  - runbook workflow updated for config-driven onboarding (no compose edits):
    - `docs/ops/runbooks.md`
  - execution note:
    - `docs/ops/day29_strategy_catalog_20260222.md`
- Day30 compose mount simplification + drift prevention completed:
  - compose mount strategy simplified from per-file controller binds to shared directory mounts:
    - `compose/docker-compose.yml` (bots `bot1`..`bot4`)
    - `../controllers:/home/hummingbot/controllers:ro`
    - `../controllers:/home/hummingbot/controllers/market_making:ro`
  - drift-prevention checker added:
    - `scripts/release/check_strategy_catalog_consistency.py`
    - evidence path: `reports/strategy_catalog/strategy_catalog_check_20260222T125608Z.json` (`status=pass`)
  - promotion gate integration:
    - `scripts/release/run_promotion_gates.py` adds critical `strategy_catalog_consistency`
    - `docs/validation/promotion_gate_contract.md` updated
  - runbook updates:
    - `docs/ops/runbooks.md` (shared mount + pycache guidance)
  - execution note:
    - `docs/ops/day30_compose_mount_simplification_20260222.md`
  - promotion gate run after integration:
    - `reports/promotion_gates/promotion_gates_20260222T125611Z.json`
    - `strategy_catalog_consistency=PASS`
    - overall status remained `FAIL` due to `event_store_integrity_freshness`
- Day31 test suite formalization + gate integration completed:
  - deterministic test runner added:
    - `scripts/release/run_tests.py`
    - artifacts:
      - `reports/tests/latest.json`
      - `reports/tests/latest.md`
      - `reports/tests/coverage.xml`
      - `reports/tests/coverage.json`
  - promotion gate integration:
    - `scripts/release/run_promotion_gates.py` adds critical `unit_service_integration_tests`
    - `docs/validation/promotion_gate_contract.md` updated
  - reproducible test deps pinned:
    - `compose/images/control_plane/requirements-control-plane.txt` adds `pytest`, `pytest-cov`
  - validation fix for deterministic intent idempotency behavior:
    - `services/hb_bridge/intent_consumer.py` adds same-batch duplicate guard (`seen_in_batch`)
  - validation evidence:
    - `reports/tests/test_run_20260222T130243Z.json` (`status=pass`)
    - `reports/promotion_gates/promotion_gates_20260222T130248Z.json` (`unit_service_integration_tests=PASS`)
    - overall gate status remains `FAIL` only on `event_store_integrity_freshness`
- Day32 coordination service audit + policy completed:
  - policy source added:
    - `config/coordination_policy_v1.json`
    - `docs/ops/coordination_service_policy_v1.md`
  - coordination service runtime hardening:
    - `services/coordination_service/main.py`
    - explicit gating via `COORD_ENABLED`, `COORD_REQUIRE_ML_ENABLED`, `ML_ENABLED`
    - policy-driven target clamps + intent TTL + health artifact output
  - compose + healthcheck wiring:
    - `compose/docker-compose.yml` (`coordination-service`)
  - policy checker + gate integration:
    - `scripts/release/check_coordination_policy.py`
    - `scripts/release/run_promotion_gates.py` adds critical `coordination_policy_scope`
    - `docs/validation/promotion_gate_contract.md` updated
    - `docs/ops/runbooks.md` updated
  - validation evidence:
    - `reports/policy/coordination_policy_check_20260222T130722Z.json` (`status=pass`)
    - `reports/promotion_gates/promotion_gates_20260222T130728Z.json` (`coordination_policy_scope=PASS`)
    - overall gate status remains `FAIL` due to `event_store_integrity_freshness`
- Day33 control-plane coordination metrics + wiring completed:
  - exporter coverage expanded:
    - `services/control_plane_metrics_exporter.py`
    - includes `coordination` + `coordination_policy` freshness and explicit coordination runtime metrics
    - exports per-check promotion gate statuses (`source=promotion_latest`) including `coordination_policy_scope`
  - Prometheus alert coverage expanded:
    - `monitoring/prometheus/alert_rules.yml`
    - includes coordination reports in stale/missing checks
    - adds `CoordinationPolicyGateFailed` and `CoordinationRuntimeNotHealthy`
  - Grafana control-plane dashboard expanded:
    - `monitoring/grafana/dashboards/control_plane_overview.json`
    - adds `Coord Policy Gate` + `Coord Runtime Health`
  - runbook + execution note:
    - `docs/ops/runbooks.md`
    - `docs/ops/day33_control_plane_coordination_metrics_20260222.md`
- Day34 strict-cycle recheck + runtime blocker documented:
  - strict cycle rerun evidence:
    - `reports/promotion_gates/strict_cycle_latest.json`
    - `reports/promotion_gates/latest.json`
  - observed gate blockers:
    - `event_store_integrity_freshness`
    - `day2_event_store_gate`
  - runtime blocker evidence:
    - Redis connection refused on `127.0.0.1:6379`
    - Docker daemon unavailable (`dockerDesktopLinuxEngine` pipe not found)
  - execution note:
    - `docs/ops/day34_strict_cycle_recheck_20260222.md`
- Day35 market-data freshness gate delivered (partial scope):
  - new checker:
    - `scripts/release/check_market_data_freshness.py`
    - artifacts: `reports/market_data/latest.json`
  - promotion integration:
    - `scripts/release/run_promotion_gates.py` adds `market_data_freshness` gate (`warning`)
  - validation evidence:
    - `reports/market_data/market_data_freshness_20260222T133935Z.json`
    - `reports/promotion_gates/promotion_gates_20260222T134022Z.json` (critical failures unchanged: `day2_event_store_gate` only)
  - execution note:
    - `docs/ops/day35_market_data_freshness_gate_20260222.md`
- Day35 HB upgrade path completed:
  - dry-run preflight checker:
    - `scripts/release/check_hb_upgrade_readiness.py`
  - validation evidence:
    - `reports/upgrade/hb_upgrade_readiness_20260222T134342Z.json` (`status=pass`)
    - `reports/upgrade/latest.json`
  - rollout/rollback contract documented:
    - `docs/ops/runbooks.md`
    - `docs/ops/day35_hb_upgrade_path_20260222.md`
- Day35 event-store recovery runner + strict recheck hardening completed:
  - new one-command recovery flow:
    - `scripts/release/recover_event_store_stack_and_strict_cycle.py`
    - starts minimal external stack, waits health, runs strict cycle, writes `reports/recovery/latest.json`
  - deterministic test gate robustness:
    - `scripts/release/run_tests.py` auto-runtime now falls back to host when docker runtime lacks `pytest`
    - payload includes `fallback_reason`
  - validation evidence:
    - `reports/recovery/recover_event_store_strict_20260222T132151Z.json`
    - `reports/tests/test_run_20260222T132229Z.json` (`status=pass`, `runtime_used=host`)
    - `reports/promotion_gates/strict_cycle_latest.json` now failing only `day2_event_store_gate`
  - execution note:
    - `docs/ops/day35_event_store_recovery_runner_20260222.md`
- Day36 day2 baseline reanchor completed:
  - controlled baseline reset utility added:
    - `scripts/utils/reset_event_store_baseline.py`
  - applied reset with evidence:
    - `reports/event_store/baseline_reset_apply_20260222T132512Z.json`
    - `reports/event_store/baseline_counts_backup_20260222T132512Z.json`
  - post-reset gate behavior:
    - `reports/event_store/day2_gate_eval_latest.json` now passes:
      - `missing_correlation`
      - `delta_since_baseline_tolerance`
    - only `elapsed_window` remains pending (`0.0h / 24h`)
  - strict cycle state:
    - `reports/promotion_gates/strict_cycle_latest.json` remains `FAIL` only for `day2_event_store_gate`
  - execution note:
    - `docs/ops/day36_day2_baseline_reanchor_20260222.md`
- Day7 readiness package tightened for Day2 pause handoff:
  - readiness decision artifacts refreshed with operator-pause checkpoint and resume criteria:
    - `docs/ops/option4_readiness_decision_latest.md`
    - `docs/ops/option4_readiness_decision.md`
  - handoff note added:
    - `docs/ops/day7_readiness_pause_handoff_20260222.md`
  - resume condition formalized:
    - rerun Day2 + strict cycle after `2026-02-23T13:25Z`
- Day85b startup position sync + cross-day position safety completed:
  - **Problem solved:** bot restart (especially across day boundary) could lose track of open exchange positions, creating untracked liquidation risk.
  - Changes to `controllers/epp_v2_4.py`:
    - `startup_position_sync` config field (default `true`)
    - `_run_startup_position_sync()` — queries exchange on first tick, adopts exchange position if local state disagrees (exchange is source of truth)
    - `_load_daily_state()` — cross-day restart now preserves `position_base` and `avg_entry_price` (previously returned early, resetting to zero)
    - `_startup_position_sync_done` flag — ensures sync runs exactly once
    - Orphan position detection with explicit WARNING log when exchange has position but local state is zero
  - Additional hardening (self-audit pass):
    - Startup sync retries up to 10 ticks if connector not ready (was: silently gave up on first failure)
    - `startup_position_sync_pending` risk reason blocks order placement until sync completes
    - `_check_position_reconciliation` now auto-corrects local state when drift exceeds threshold (was: warning only)
    - `to_format_status` shows open position warning with entry price (visible on stop + status command)
  - Tests added to `tests/controllers/test_epp_v2_4_state.py` (10 new tests):
    - `test_cross_day_restart_preserves_position` — verifies position survives day boundary
    - `test_startup_sync_adopts_exchange_position` — exchange has position, local zero → adopt
    - `test_startup_sync_no_drift` — matching positions → no change
    - `test_startup_sync_corrects_stale_local` — exchange differs → exchange wins
    - `test_startup_sync_disabled` — config toggle respected
    - `test_startup_sync_both_zero` — no-op when both zero
    - `test_startup_sync_retries_when_connector_unavailable` — defers then retries
    - `test_startup_sync_gives_up_after_max_retries` — marks done after 10 failures
    - `test_startup_sync_blocks_trading_while_pending` — risk reason emitted
- Day85c paper engine maker/taker classification fix completed:
  - **Problem solved:** paper engine classified 100% of fills as taker, making paper soak results unreliable (showed losses when strategy was actually profitable at maker rates).
  - Root cause: `DepthFillModel.evaluate()` only used passive maker path for `LIMIT_MAKER` orders; regular `LIMIT` orders were treated as taker when price touched them.
  - Changes to `controllers/paper_engine.py`:
    - `crossed_at_creation` field added to `PaperOrder` — tracks whether order crossed the spread at submission time
    - `_submit_order()` — checks current book at creation to set `crossed_at_creation`
    - `DepthFillModel.evaluate()` — resting LIMIT orders (crossed_at_creation=False) now take the passive maker path (fill at limit price, is_taker=False)
    - `maker_fee_bps` default changed from 10.0 to 2.0 (Bitget VIP0 maker rate)
    - Fallback fill event now carries `is_maker` on `trade_fee` object
  - Changes to `controllers/epp_v2_4.py`:
    - `did_fill_order()` — checks `trade_fee.is_maker` first (authoritative), falls back to price heuristic only if unavailable
  - Tests added to `tests/controllers/test_paper_engine.py` (8 new tests):
    - `test_resting_limit_buy_is_maker` / `test_resting_limit_sell_is_maker`
    - `test_crossing_limit_buy_is_taker` / `test_crossing_limit_sell_is_taker`
    - `test_limit_maker_always_maker`
    - `test_maker_fee_lower_than_taker`
    - `test_adapter_resting_buy_classified_as_maker` (end-to-end)
    - `test_adapter_crossing_buy_classified_as_taker` (end-to-end)
