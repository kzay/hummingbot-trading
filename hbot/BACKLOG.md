# hbot — Active Backlog

> **For AI agents**: this file contains only active and blocked work.
> Completed tracks were moved to `hbot/docs/archive/BACKLOG_ARCHIVE_2026Q1.md`.
> After every change:
> - `python -m py_compile hbot/controllers/epp_v2_4.py`
> - `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration`

**Tiers**: P0 = blocks live/safety or hard promotion gate · P1 = affects PnL/reliability · P2 = quality/simulation realism  
**Status**: `open` · `in-progress (YYYY-MM-DD)` · `blocked (reason)` · `done (YYYY-MM-DD)`

---

## Current Promotion Gates (Go/No-Go)

| Gate | Status | Latest evidence | Pass target | Next action |
|---|---|---|---|---|
| ROAD-1: 20-day paper edge | `in-progress (2026-03-05)` | `reports/strategy/multi_day_summary_latest.json` (15 days, Sharpe < 0, gate FAIL) | >=20 consecutive days, mean daily net pnl bps > 0, Sharpe >= 1.5, max single-day DD < 2%, no hard daily loss hit, spread capture dominant | complete 20-day window and improve expectancy |
| ROAD-5: 4-week testnet live | `in-progress (2026-03-05)` | `reports/strategy/testnet_multi_day_summary_latest.json` (coverage 1 day, gate FAIL) | 20 testnet trading days, no HARD_STOP, slippage < 2 bps vs paper, reject rate < 0.5%, Sharpe >= 0.8x paper | provision keys and run sustained testnet period |
| STRAT_LOOP 2026-03-05 | `in-progress (2026-03-05)` | controller/runtime dossier and verification artifacts | close all cycle acceptance criteria below | execute in cycle order with isolated parameter groups |

## Weekly Execution Board

> Owners are role placeholders for weekly planning. Replace with named owners during standup.

| Item | Tier | Status | Owner | Due | Primary artifact |
|---|---|---|---|---|---|
| ROAD-1 | P0 | `in-progress` | `strategy-eng` | `2026-03-20` | `reports/strategy/multi_day_summary_latest.json` |
| ROAD-5 | P0 | `in-progress` | `ops-eng` | `2026-04-05` | `reports/strategy/testnet_multi_day_summary_latest.json` |
| P0-STRAT-20260305-1 | P0 | `in-progress` | `strategy-eng` | `2026-03-12` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| P0-STRAT-20260305-10 | P0 | `in-progress` | `execution-eng` | `2026-03-12` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-2 | P1 | `in-progress` | `strategy-eng` | `2026-03-12` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| P1-STRAT-20260305-3 | P1 | `in-progress` | `strategy-eng` | `2026-03-12` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-4 | P1 | `in-progress` | `strategy-eng` | `2026-03-10` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-5 | P1 | `in-progress` | `strategy-eng` | `2026-03-11` | `tests/controllers/test_epp_v2_4.py` |
| P1-STRAT-20260305-7 | P1 | `in-progress` | `execution-eng` | `2026-03-11` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-8 | P1 | `in-progress` | `execution-eng` | `2026-03-11` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-9 | P1 | `in-progress` | `execution-eng` | `2026-03-11` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-11 | P1 | `in-progress` | `strategy-eng` | `2026-03-14` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-12 | P1 | `in-progress` | `strategy-eng` | `2026-03-14` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| P1-STRAT-20260305-13 | P1 | `in-progress` | `strategy-eng` | `2026-03-13` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-14 | P1 | `in-progress` | `strategy-eng` | `2026-03-13` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-15 | P1 | `in-progress` | `strategy-eng` | `2026-03-13` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-16 | P1 | `in-progress` | `ops-eng` | `2026-03-14` | `reports/strategy/testnet_multi_day_summary_latest.json` |
| P1-STRAT-20260305-17 | P1 | `in-progress` | `strategy-eng` | `2026-03-14` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-18 | P1 | `in-progress` | `strategy-eng` | `2026-03-14` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| ROAD-12 | P1 | `in-progress` | `platform-eng` | `2026-03-19` | `reports/verification/realtime_l2_data_quality_latest.json` |
| ROAD-13 | P1 | `in-progress` | `frontend-eng` | `2026-03-19` | `apps/realtime_ui/index.html` |
| ROAD-14 | P2 | `in-progress` | `data-eng` | `2026-03-21` | `reports/ops_db_writer/latest.json` |
| P1-STRAT-20260305-19 | P1 | `in-progress` | `platform-eng` | `2026-03-15` | `services/contracts/event_schemas.py` |
| P1-STRAT-20260305-20 | P1 | `in-progress` | `platform-eng` | `2026-03-16` | `services/realtime_ui_api/main.py` |
| P1-STRAT-20260305-21 | P1 | `in-progress` | `frontend-eng` | `2026-03-16` | `apps/realtime_ui/index.html` |
| P1-STRAT-20260305-22 | P1 | `in-progress` | `ops-eng` | `2026-03-17` | `scripts/release/run_promotion_gates.py` |
| P1-STRAT-20260305-23 | P1 | `in-progress` | `ops-eng` | `2026-03-17` | `reports/verification/realtime_l2_data_quality_latest.json` |
| P2-STRAT-20260305-6 | P2 | `in-progress` | `strategy-eng` | `2026-03-10` | `data/bot1/conf/controllers/epp_v2_4_bot_a.yml` |
| P2-STRAT-20260305-7 | P2 | `in-progress` | `data-eng` | `2026-03-18` | `services/ops_db_writer/schema_v1.sql` |
| P2-STRAT-20260305-8 | P2 | `in-progress` | `platform-eng` | `2026-03-18` | `services/event_store/main.py` |
| P2-STRAT-20260305-9 | P2 | `in-progress` | `ops-eng` | `2026-03-20` | `monitoring/OBSERVABILITY_CONTRACT.md` |
| ROAD-10 | blocked | `blocked` | `ml-eng` | `blocked: data` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| ROAD-11 | blocked | `blocked` | `ml-eng` | `blocked: data` | `data/bot1/logs/epp_v24/bot1_a/fills.csv` |
| OPS-PREREQ-1 | blocked | `blocked` | `ops-eng` | `2026-03-08` | `reports/ops/telegram_validation_latest.json` |
| OPS-PREREQ-2 | blocked | `blocked` | `security-eng` | `2026-03-12` | `docs/ops/runbooks.md` |

---

## P0 — Blocks Live / Safety / Promotion

### [ROAD-1] 20-day paper run — prove statistical edge `in-progress (2026-03-05)`
- **Why it matters**: one positive day is noise; promotion requires statistically credible paper edge.
- **Current evidence snapshot**: latest run is short coverage and negative expectancy (`reports/strategy/multi_day_summary_latest.json`).
- **Implementation**:
  1. Run daily summary for each day: `python hbot/scripts/analysis/bot1_paper_day_summary.py --day YYYY-MM-DD`.
  2. Maintain 20-day contiguous tracking table for pnl/drawdown/fills/turnover/regime.
  3. Recompute rolling aggregate: `python hbot/scripts/analysis/bot1_multi_day_summary.py --start YYYY-MM-DD --end YYYY-MM-DD`.
- **Acceptance criteria**:
  - Mean daily `net_pnl_bps` > 0 over 20 days.
  - Annualized Sharpe >= 1.5.
  - Max single-day drawdown < 2%.
  - No day hits `max_daily_loss_pct_hard`.
  - PnL decomposition shows spread capture as dominant source.
- **Do not**: do not promote while `road1_gate` is FAIL.

### [ROAD-5] 4-week testnet live trading `in-progress (2026-03-05)`
- **Why it matters**: paper mode cannot validate real exchange microstructure and API behavior.
- **Prerequisites**:
  - P0 items complete and checklist signed.
  - `KILL_SWITCH_DRY_RUN=false` validated on testnet.
  - Dedicated testnet keys funded with test USDT.
  - Switch bot connector to `bitget_perpetual` only after prerequisites pass.
- **Implementation**:
  1. Produce daily scorecards: `python hbot/scripts/analysis/testnet_daily_scorecard.py`.
  2. Maintain rolling gate artifact: `python hbot/scripts/analysis/testnet_multi_day_summary.py`.
  3. Keep promotion ladder fail-closed on ROAD-5 criteria keys.
- **Acceptance criteria**:
  - 20 testnet trading days.
  - No HARD_STOP incidents.
  - Execution slippage < 2 bps vs paper equivalent.
  - Reject rate < 0.5%.
  - Testnet Sharpe >= 0.8x paper Sharpe.
- **Do not**: do not use mainnet keys for testnet or skip sustained window evidence.

### [P0-STRAT-20260305-1] Tighten inventory cap for bot1 risk stability `in-progress (2026-03-05)`
- **Why it matters**: inventory-limit breaches are the dominant risk-state trigger.
- **Implementation**:
  1. Set `max_base_pct: 0.45` in `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`.
  2. Run minimum 5-day/1500-fill evaluation window.
- **Acceptance criteria**:
  - `base_pct_above_max` row ratio < 20%.
  - Combined `soft_pause + hard_stop` ratio improves vs prior cycle.
- **Do not**: do not increase leverage or quote size in this cycle.

### [P0-STRAT-20260305-10] Stop hard-stop flatten ping-pong churn `in-progress (2026-03-05)`
- **Why it matters**: near-zero residuals can trigger repeated taker rebalance churn and fee drag.
- **Implementation**:
  1. Add minimum rebalance threshold floor in `check_position_rebalance`.
  2. Skip sub-floor residual rebalances while keeping materially non-zero flattening active.
  3. Add unit test for below-floor no-op path.
- **Acceptance criteria**:
  - No rebalance orders for residual below floor.
  - Existing rebalance-path tests stay green.
- **Do not**: do not disable hard-stop flatten for materially non-zero inventory.

### [ROAD-12] Stream-first realtime read-model migration `in-progress (2026-03-05)`
- **Why it matters**: operator reads must come from live streams first, with file snapshots only as controlled fallback.
- **Implementation**:
  1. Extend stream contracts with `hb.market_depth.v1` while preserving `hb.market_data.v1`.
  2. Publish depth snapshots from controller runtime.
  3. Ingest depth stream in event store and include in strict-cycle evidence.
- **Acceptance criteria**:
  - L1 consumers remain backward compatible.
  - `hb.market_depth.v1` has stable ordered payloads with sequence metadata.
  - Event-store integrity includes depth stream coverage.

### [ROAD-13] TradingView-like operator app v1 `in-progress (2026-03-05)`
- **Why it matters**: Grafana is control-plane observability; execution operations need a dedicated realtime trading view.
- **Implementation**:
  1. Run `realtime-ui-api` (`disabled -> shadow -> active`) with SSE updates.
  2. Deliver `apps/realtime_ui` for chart, orders/fills overlays, position panel, and depth ladder.
  3. Keep desk-snapshot fallback for stale stream recovery.
- **Acceptance criteria**:
  - End-to-end live updates for market, fills, orders, positions, and depth.
  - API health/metrics endpoints wired in compose health checks.
  - Shadow rollout validated before `active` mode.

### [ROAD-14] L2 depth ingestion/storage/visualization `in-progress (2026-03-05)`
- **Why it matters**: L2 introduces high-throughput persistence risk and must be bounded by explicit storage and quality budgets.
- **Implementation**:
  1. Persist raw depth events and sampled depth views in ops DB writer.
  2. Build minute rollups for depth metrics.
  3. Add strict gate `realtime_l2_data_quality` for freshness/sequence/sampling/storage controls.
- **Acceptance criteria**:
  - Raw/sampled/rollup depth layers populated with checkpointed ingestion.
  - Strict cycle fails on realtime/L2 regressions.
  - Storage and payload budgets enforced by gate report.

---

## P1 — PnL / Reliability / Execution Quality

### [P1-STRAT-20260305-2] Accelerate derisk force-taker escalation `in-progress (2026-03-05)`
- **Why it matters**: slow derisk escalation extends exposure in non-productive safety states.
- **Implementation**:
  1. Set `derisk_force_taker_after_s: 45`.
  2. Set `derisk_progress_reset_ratio: 0.005`.
  3. Validate derisk dwell reduction in next sample window.
- **Acceptance criteria**:
  - `derisk_force_taker` and `eod_close_pending` frequencies decline vs prior cycle.
  - No worse drawdown tail beyond cycle guardrails.
- **Do not**: do not disable derisk or hard-stop protections.

### [P1-STRAT-20260305-3] Run no-size-boost governor experiment `in-progress (2026-03-05)`
- **Why it matters**: positive size boost under negative edge can amplify churn.
- **Implementation**:
  1. Set `pnl_governor_max_size_boost_pct: 0.00`.
  2. Run one isolated cycle without spread-group changes.
  3. Compare PnL/fill, drawdown, hard-stop ratios vs prior cycle.
- **Acceptance criteria**:
  - PnL/fill improves by >= 0.02 vs short-window baseline.
  - Max drawdown <= 4.5% during evaluation.
- **Do not**: do not change spread parameter group in this validation cycle.

### [P1-STRAT-20260305-4] Publish cancel-before-fill KPI in dossier `in-progress (2026-03-05)`
- **Why it matters**: cancellation churn before fill is a missing quick-read execution KPI.
- **Implementation**:
  1. Add `cancel_before_fill_rows` and `cancel_before_fill_rate` to `hbot/scripts/analysis/performance_dossier.py`.
  2. Add markdown output line for this KPI.
  3. Extend dossier unit tests for deterministic metric computation.
- **Acceptance criteria**:
  - `reports/analysis/performance_dossier_latest.json` includes both fields.
  - Unit tests verify expected values from synthetic inputs.
- **Do not**: keep semantics aligned with scorecard formula.

### [P1-STRAT-20260305-5] Add fill-edge guard for governor size boost `in-progress (2026-03-05)`
- **Why it matters**: deficit-based boost should not activate when realized fill edge is below cost floor.
- **Implementation**:
  1. Guard `_compute_pnl_governor_size_mult` when `fill_edge_ewma < -cost_floor_bps`.
  2. Emit reason `fill_edge_below_cost_floor`.
  3. Add unit test for blocked-boost path.
- **Acceptance criteria**:
  - Size multiplier remains `1.0` in negative-edge condition.
  - Guard reason appears in diagnostics.
- **Do not**: do not disable existing hard/soft caps.

### [P1-STRAT-20260305-7] Stabilize active submit order-id on retries `in-progress (2026-03-05)`
- **Why it matters**: retry submit ID drift increases duplicate-order risk and weakens traceability.
- **Implementation**:
  1. Add short-TTL fingerprint cache for active submit order IDs in bridge state.
  2. Reuse order ID for identical retries in TTL window.
  3. Add tests for reuse and TTL-disabled behavior.
- **Acceptance criteria**:
  - Identical retries inside TTL reuse same `order_id`.
  - TTL `0` produces distinct IDs.
- **Do not**: keep sync-gate and failure-policy behavior intact.

### [P1-STRAT-20260305-8] Stabilize active cancel command id on retries `in-progress (2026-03-05)`
- **Why it matters**: cancel retry command-ID drift bypasses service-side idempotency and adds audit noise.
- **Implementation**:
  1. Add cancel fingerprint/TTL cache.
  2. Reuse `command_event_id` for identical retries in TTL window.
  3. Add tests for reuse and TTL-disabled behavior.
- **Acceptance criteria**:
  - Identical cancel retries inside TTL share same event id.
  - TTL `0` produces distinct ids.
- **Do not**: do not weaken sync gating or failure-policy semantics.

### [P1-STRAT-20260305-9] Stabilize active cancel-all command id on retries `in-progress (2026-03-05)`
- **Why it matters**: `cancel_all` retry ID drift reduces dedupe effectiveness and forensic clarity.
- **Implementation**:
  1. Add dedicated `cancel_all` command-ID cache.
  2. Reuse command ID for identical publishes in TTL window.
  3. Add tests for reuse and TTL-disabled behavior.
- **Acceptance criteria**:
  - Identical active `cancel_all` publishes in TTL share the same event id.
  - TTL `0` produces distinct ids.
- **Do not**: do not bypass privileged metadata checks.

### [P1-STRAT-20260305-11] Add adverse-fill confidence soft-pause gate `in-progress (2026-03-05)`
- **Why it matters**: sustained realized adverse edge should force no-trade state even when spread gates pass.
- **Implementation**:
  1. Add `adverse_fill_soft_pause_*` config knobs.
  2. Emit risk reason `adverse_fill_soft_pause`.
  3. Resolve runtime state to `SOFT_PAUSE` while trigger is active.
  4. Add tests for activation path.
- **Acceptance criteria**:
  - Trigger requires minimum sample + confidence condition.
  - Controller enters `SOFT_PAUSE` when active.
- **Do not**: do not alter hard-stop escalation criteria.

### [P1-STRAT-20260305-12] Gate force-taker escalation by material imbalance `in-progress (2026-03-05)`
- **Why it matters**: force-taker on near-min inventory adds unnecessary taker drag.
- **Implementation**:
  1. Add `derisk_force_taker_min_base_mult`.
  2. Resolve materiality floor from exchange min-base/notional and reference price.
  3. Prevent force mode when inventory is below floor.
  4. Add sub-material inventory tests.
- **Acceptance criteria**:
  - Sub-material inventory never force-escalates after timeout.
  - Existing behavior unchanged for material inventory.
- **Do not**: keep force-taker path for materially non-zero risk inventory.

### [P1-STRAT-20260305-13] Add rolling expectancy CI dossier gate signal `in-progress (2026-03-05)`
- **Why it matters**: net-PnL checks react slowly; confidence intervals catch structural expectancy failure sooner.
- **Implementation**:
  1. Compute per-fill net expectancy series (overall/maker/taker).
  2. Publish rolling CI metrics and gate flag in dossier.
  3. Add check `rolling_expectancy_ci95_upper_non_negative` with min sample threshold.
  4. Extend unit tests.
- **Acceptance criteria**:
  - Dossier artifact includes rolling CI fields and gate signal.
  - Checks fail when CI upper bound stays negative at required sample depth.
- **Do not**: keep backward-compatible dossier fields.

### [P1-STRAT-20260305-14] Add edge-confidence soft-pause gate `in-progress (2026-03-05)`
- **Why it matters**: mean edge can look recoverable while confidence-adjusted upper bound remains below cost floor.
- **Implementation**:
  1. Add `edge_confidence_soft_pause_*` knobs.
  2. Compute confidence upper-bound from EWMA mean/variance/count.
  3. Emit `edge_confidence_soft_pause` and force `SOFT_PAUSE` while active.
  4. Add activation tests.
- **Acceptance criteria**:
  - Reason appears only when confidence trigger is active.
  - Controller pauses while trigger persists.
- **Do not**: do not relax existing hard-stop risk caps.

### [P1-STRAT-20260305-15] Add slippage shock soft-pause guard `in-progress (2026-03-05)`
- **Why it matters**: slippage shock bursts can erase maker edge and dominate day PnL.
- **Implementation**:
  1. Add `slippage_soft_pause_*` knobs.
  2. Compute rolling p95 slippage over recent fills.
  3. Emit `slippage_soft_pause` and force `SOFT_PAUSE` while active.
  4. Add high-p95 trigger tests.
- **Acceptance criteria**:
  - High rolling p95 slippage activates guard.
  - Controller pauses quoting during shock windows.
- **Do not**: keep stale-book and cancel-budget protections active.

### [P1-STRAT-20260305-16] Enforce rolling expectancy CI in promotion gate `in-progress (2026-03-05)`
- **Why it matters**: visibility alone is insufficient; strict cycle must fail when expectancy evidence is statistically negative.
- **Implementation**:
  1. Add promotion helper to refresh dossier artifact.
  2. Add strict-cycle check on `rolling_expectancy_gate_fail`.
  3. Surface diagnostics in promotion summary.
  4. Add tests for helper and decision logic.
- **Acceptance criteria**:
  - Strict summary includes expectancy diagnostics.
  - Negative CI upper bound (with sample threshold met) fails strict cycle.
- **Do not**: do not bypass existing threshold/preflight gates.

### [P1-STRAT-20260305-17] Clamp force-taker derisk by taker expectancy `in-progress (2026-03-05)`
- **Why it matters**: if taker expectancy stays negative, force-taker can lock in losses.
- **Implementation**:
  1. Add `derisk_force_taker_expectancy_*` config knobs.
  2. Compute rolling taker expectancy from fill history.
  3. Block force escalation when expectancy is below threshold (with large-inventory override).
  4. Add tests for block and override paths.
- **Acceptance criteria**:
  - Force mode blocked under poor taker expectancy unless inventory override is met.
  - Hard-stop flatten remains unaffected.
- **Do not**: do not disable hard-stop flatten behavior.

### [P1-STRAT-20260305-18] Extend passive order lifetime to reduce queue reset churn `in-progress (2026-03-05)`
- **Why it matters**: frequent cancel/recreate cycles reset queue progress and suppress passive fill opportunity.
- **Implementation**:
  1. Increase `regime_specs_override.*.refresh_s` for bot1.
  2. Keep force-derisk and soft-pause safety controls unchanged.
  3. Validate reduced cancel churn in logs/telemetry.
- **Acceptance criteria**:
  - Fewer cancel/recreate cycles per 10-minute window.
  - Passive orders rest long enough for queue-model fill opportunity.
- **Do not**: do not remove kill-switch/hard-stop controls.

### [P1-STRAT-20260305-19] Add L2 stream contract + producer wiring `in-progress (2026-03-05)`
- **Why it matters**: without a first-class depth contract, realtime UI cannot render order-book structure.
- **Implementation**:
  1. Add `MARKET_DEPTH_STREAM` and depth event schemas.
  2. Publish depth snapshots from runtime publisher.
  3. Keep L1 schema and stream behavior unchanged.
- **Acceptance criteria**:
  - `hb.market_depth.v1` emits valid payloads.
  - Existing `market_snapshot` consumers continue unchanged.

### [P1-STRAT-20260305-20] Deliver stream-first realtime API service `in-progress (2026-03-05)`
- **Why it matters**: UI clients need a stable API contract over volatile stream internals.
- **Implementation**:
  1. Add `services/realtime_ui_api/main.py` with stateful stream consumers.
  2. Expose `/api/v1/state`, `/api/v1/candles`, `/api/v1/depth`, `/api/v1/positions`, `/api/v1/stream`.
  3. Add auth/CORS/rollout/fallback env controls.
- **Acceptance criteria**:
  - SSE stream and REST endpoints are healthy in compose.
  - Fallback to desk snapshot activates on stream staleness.

### [P1-STRAT-20260305-21] Deliver TradingView-like web UI module `in-progress (2026-03-05)`
- **Why it matters**: operators need one execution-focused pane for chart + depth + position context.
- **Implementation**:
  1. Add static web app under `apps/realtime_ui`.
  2. Integrate lightweight charts and API polling/SSE updates.
  3. Add compose `realtime-ui-web` service for serving UI.
- **Acceptance criteria**:
  - UI renders candles, depth ladder, open orders, fills, and position panel.
  - Works in shadow mode against `realtime-ui-api`.

### [P1-STRAT-20260305-22] Wire realtime/L2 strict gate into promotion cycle `in-progress (2026-03-05)`
- **Why it matters**: live migration needs fail-closed protection against silent data-plane regressions.
- **Implementation**:
  1. Add `scripts/release/check_realtime_l2_data_quality.py`.
  2. Integrate gate execution into promotion and strict-cycle runners.
  3. Include diagnostics in promotion runtime summary.
- **Acceptance criteria**:
  - `realtime_l2_data_quality` appears as a critical gate in strict cycle.
  - Gate report is emitted to verification artifacts.

### [P1-STRAT-20260305-23] Enforce rollout evidence and operator rollback path `in-progress (2026-03-05)`
- **Why it matters**: controlled cutover requires explicit evidence and reversible rollout.
- **Implementation**:
  1. Add runbook + observability contract updates for shadow/active/disabled flow.
  2. Add strict-cycle thresholds for freshness/sequence/sampling/storage.
  3. Keep fallback path documented and testable.
- **Acceptance criteria**:
  - Runbook includes cutover and rollback commands.
  - Strict-cycle evidence references realtime/L2 artifacts.

---

## P2 — Quality / Simulation Realism

### [P2-STRAT-20260305-6] Increase bot1 paper fill realism baseline `in-progress (2026-03-05)`
- **Why it matters**: `best_price` model is optimistic and can overstate expected live performance.
- **Implementation**:
  1. Set `paper_engine.paper_fill_model: latency_aware` in bot1 config.
  2. Keep queue/latency knobs unchanged for controlled delta.
  3. Monitor slippage and maker ratio shift next cycle.
- **Acceptance criteria**:
  - Bot1 uses `latency_aware`.
  - Promotion/analysis scripts continue without parsing regressions.
- **Do not**: do not retune queue participation and slippage penalties in same step.

### [P2-STRAT-20260305-7] Add depth raw/sampled/rollup DB model `in-progress (2026-03-05)`
- **Why it matters**: depth data volume can exhaust storage and query budgets without layered persistence.
- **Implementation**:
  1. Add `market_depth_raw`, `market_depth_sampled`, `market_depth_rollup_minute`.
  2. Add timescale retention/compression defaults for all depth layers.
  3. Add indexed query paths for pair/time windows.
- **Acceptance criteria**:
  - Tables and indexes exist via ops DB schema migration.
  - Retention/compression policies configured through env vars.

### [P2-STRAT-20260305-8] Add checkpointed depth ingestion path `in-progress (2026-03-05)`
- **Why it matters**: full rescans of event JSONL are not safe at L2 throughput.
- **Implementation**:
  1. Add `market_depth_ingest_checkpoint` state table.
  2. Ingest only new rows from event store files.
  3. Keep ingestion idempotent via conflict keys.
- **Acceptance criteria**:
  - Re-runs do not duplicate depth records.
  - Checkpoint advances deterministically across files.

### [P2-STRAT-20260305-9] Harden observability contract for realtime/L2 `in-progress (2026-03-05)`
- **Why it matters**: operators need explicit, auditable SLO-style expectations for realtime/L2 path.
- **Implementation**:
  1. Extend `monitoring/OBSERVABILITY_CONTRACT.md` with depth streams + evidence mapping.
  2. Add runbook steps for shadow/active migration and rollback.
  3. Align architecture docs to new services and stream topology.
- **Acceptance criteria**:
  - Docs include operator-ready migration/rollback procedures.
  - All strict gate artifacts have documented source-of-truth mapping.

---

## Blocked / Waiting on Data or Human Action

### [ROAD-10] AI regime classifier — model training and rollout `blocked (requires >=10k labeled minute rows)`
- **What is done**: infrastructure and wiring are complete.
- **Unblock condition**: enough labeled history to run walk-forward training + OOS validation.
- **Promotion condition**: OOS Sharpe improvement >= 0.3 and runtime latency budget respected.

### [ROAD-11] AI adverse selection classifier — model training and rollout `blocked (requires >=5k fills)`
- **What is done**: infrastructure and bridge hooks are complete.
- **Unblock condition**: enough fills for dataset and walk-forward validation.
- **Promotion condition**: adverse-fill rate reduction >= 15% OOS with no major missed-fill regression.

### [OPS-PREREQ-1] Testnet/API/alerting credentials readiness `blocked (human action)`
- Rotate and set valid Telegram bot token/chat id when configured.
- Provision/fund dedicated Bitget testnet keys.
- Keep strict gate checks fail-closed until credential probes pass.

### [OPS-PREREQ-2] Realtime UI auth/network hardening `blocked (security review)`
- Finalize auth mode for operator UI (`REALTIME_UI_API_AUTH_ENABLED`, token distribution path).
- Confirm bind-IP policy and firewall exposure for API/web ports.
- Complete security sign-off before setting `REALTIME_UI_API_MODE=active`.

---

## Recently Completed (Moved to Archive)

The following completed tracks were removed from this active backlog and summarized in `hbot/docs/archive/BACKLOG_ARCHIVE_2026Q1.md`:
- BUILD_SPEC — Multi-Bot Desk Audit Follow-Up
- BUILD_SPEC — Canonical Data Plane Migration (Timescale)
- BUILD_SPEC — Pro Quality Upgrade Program (ARCH/TECH/PERF/FUNC)
- BUILD_SPEC — Semi-Pro Paper Exchange Service (exchange mirror)
- Legacy P0/P1/P2 + infra/tech-debt/code-quality execution tracks
- STRATEGY_LOOP — Iteration (2026-03-02)

