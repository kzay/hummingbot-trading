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
| P0-STRAT-20260305-1 | P0 | `blocked: fresh observation window` | `strategy-eng` | `2026-03-12` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| P0-STRAT-20260305-10 | P0 | `done (2026-03-10)` | `execution-eng` | `2026-03-12` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-2 | P1 | `blocked: superseded by later bot1 experiments` | `strategy-eng` | `2026-03-12` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| P1-STRAT-20260305-3 | P1 | `blocked: isolated observation window` | `strategy-eng` | `2026-03-12` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-4 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-10` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-5 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-11` | `tests/controllers/test_epp_v2_4.py` |
| P1-STRAT-20260305-7 | P1 | `done (2026-03-10)` | `execution-eng` | `2026-03-11` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-8 | P1 | `done (2026-03-10)` | `execution-eng` | `2026-03-11` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-9 | P1 | `done (2026-03-10)` | `execution-eng` | `2026-03-11` | `reports/verification/paper_exchange_command_journal_latest.json` |
| P1-STRAT-20260305-11 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-14` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-12 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-14` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| P1-STRAT-20260305-13 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-13` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-14 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-13` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-15 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-13` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-16 | P1 | `done (2026-03-10)` | `ops-eng` | `2026-03-14` | `reports/strategy/testnet_multi_day_summary_latest.json` |
| P1-STRAT-20260305-17 | P1 | `done (2026-03-10)` | `strategy-eng` | `2026-03-14` | `reports/analysis/performance_dossier_latest.json` |
| P1-STRAT-20260305-18 | P1 | `blocked: fresh cancel-churn evidence` | `strategy-eng` | `2026-03-14` | `data/bot1/logs/epp_v24/bot1_a/minute.csv` |
| ROAD-12 | P1 | `blocked: fresh L2 quality evidence` | `platform-eng` | `2026-03-19` | `reports/verification/realtime_l2_data_quality_latest.json` |
| ROAD-13 | P1 | `blocked: fresh shadow rollout evidence` | `frontend-eng` | `2026-03-19` | `apps/realtime_ui/index.html` |
| ROAD-14 | P2 | `blocked: fresh depth gate evidence` | `data-eng` | `2026-03-21` | `reports/ops_db_writer/latest.json` |
| P1-STRAT-20260305-19 | P1 | `done (2026-03-10)` | `platform-eng` | `2026-03-15` | `services/contracts/event_schemas.py` |
| P1-STRAT-20260305-20 | P1 | `done (2026-03-10)` | `platform-eng` | `2026-03-16` | `services/realtime_ui_api/main.py` |
| P1-STRAT-20260305-21 | P1 | `done (2026-03-10)` | `frontend-eng` | `2026-03-16` | `apps/realtime_ui/index.html` |
| P1-STRAT-20260305-22 | P1 | `done (2026-03-10)` | `ops-eng` | `2026-03-17` | `scripts/release/run_promotion_gates.py` |
| P1-STRAT-20260305-23 | P1 | `done (2026-03-10)` | `ops-eng` | `2026-03-17` | `reports/verification/realtime_l2_data_quality_latest.json` |
| P1-QUANT-20260309-1 | P1 | `open` | `strategy-eng` | `2026-03-13` | `data/bot7/logs/epp_v24/bot7_a/fills.csv` |
| P2-STRAT-20260305-6 | P2 | `done (2026-03-10)` | `strategy-eng` | `2026-03-10` | `data/bot1/conf/controllers/epp_v2_4_bot_a.yml` |
| P2-STRAT-20260305-7 | P2 | `done (2026-03-10)` | `data-eng` | `2026-03-18` | `services/ops_db_writer/schema_v1.sql` |
| P2-STRAT-20260305-8 | P2 | `done (2026-03-10)` | `platform-eng` | `2026-03-18` | `services/event_store/main.py` |
| P2-STRAT-20260305-9 | P2 | `done (2026-03-10)` | `ops-eng` | `2026-03-20` | `monitoring/OBSERVABILITY_CONTRACT.md` |
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

### [P0-STRAT-20260305-1] Tighten inventory cap for bot1 risk stability `blocked (requires fresh paper observation window)`
- **Why it matters**: inventory-limit breaches are the dominant risk-state trigger.
- **Implementation**:
  1. Set `max_base_pct: 0.45` in `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`.
  2. Run minimum 5-day/1500-fill evaluation window.
- **Acceptance criteria**:
  - `base_pct_above_max` row ratio < 20%.
  - Combined `soft_pause + hard_stop` ratio improves vs prior cycle.
- **Do not**: do not increase leverage or quote size in this cycle.
 - **Current blocker**: later bot1 experiments already tightened `max_base_pct` beyond this original target, so closure now depends on a fresh observation window rather than another code/config edit.

### [P0-STRAT-20260305-10] Stop hard-stop flatten ping-pong churn `done (2026-03-10)`
- **Why it matters**: near-zero residuals can trigger repeated taker rebalance churn and fee drag.
- **Implementation**:
  1. Add minimum rebalance threshold floor in `check_position_rebalance`.
  2. Skip sub-floor residual rebalances while keeping materially non-zero flattening active.
  3. Add unit test for below-floor no-op path.
- **Acceptance criteria**:
  - No rebalance orders for residual below floor.
  - Existing rebalance-path tests stay green.
- **Do not**: do not disable hard-stop flatten for materially non-zero inventory.

### [ROAD-12] Stream-first realtime read-model migration `blocked (requires fresh L2 quality evidence)`
- **Why it matters**: operator reads must come from live streams first, with file snapshots only as controlled fallback.
- **Implementation**:
  1. Extend stream contracts with `hb.market_depth.v1` while preserving `hb.market_data.v1`.
  2. Publish depth snapshots from controller runtime.
  3. Ingest depth stream in event store and include in strict-cycle evidence.
- **Acceptance criteria**:
  - L1 consumers remain backward compatible.
  - `hb.market_depth.v1` has stable ordered payloads with sequence metadata.
  - Event-store integrity includes depth stream coverage.
 - **Current blocker**: the implementation exists, but the authoritative L2 quality artifact is not currently fresh/pass, so rollout closure now depends on refreshed evidence rather than additional feature work.

### [ROAD-13] TradingView-like operator app v1 `blocked (requires fresh shadow rollout validation)`
- **Why it matters**: Grafana is control-plane observability; execution operations need a dedicated realtime trading view.
- **Implementation**:
  1. Run `realtime-ui-api` (`disabled -> shadow -> active`) with SSE updates.
  2. Deliver `apps/realtime_ui` for chart, orders/fills overlays, position panel, and depth ladder.
  3. Keep desk-snapshot fallback for stale stream recovery.
- **Acceptance criteria**:
  - End-to-end live updates for market, fills, orders, positions, and depth.
  - API health/metrics endpoints wired in compose health checks.
  - Shadow rollout validated before `active` mode.
 - **Current blocker**: app/API/build wiring is present, but the backlog still lacks fresh shadow-rollout evidence proving current end-to-end live updates rather than just implementation presence.

### [ROAD-14] L2 depth ingestion/storage/visualization `blocked (requires fresh depth gate pass)`
- **Why it matters**: L2 introduces high-throughput persistence risk and must be bounded by explicit storage and quality budgets.
- **Implementation**:
  1. Persist raw depth events and sampled depth views in ops DB writer.
  2. Build minute rollups for depth metrics.
  3. Add strict gate `realtime_l2_data_quality` for freshness/sequence/sampling/storage controls.
- **Acceptance criteria**:
  - Raw/sampled/rollup depth layers populated with checkpointed ingestion.
  - Strict cycle fails on realtime/L2 regressions.
  - Storage and payload budgets enforced by gate report.
 - **Current blocker**: storage/writer layers are implemented, but closure depends on a fresh passing depth-quality gate rather than more schema/writer work.

---

## P1 — PnL / Reliability / Execution Quality

### [P1-QUANT-20260309-1] Isolate Bot7 thesis from fallback quote states `open`
- **Why it matters**: Bot7's current paper fills are dominated by `indicator_warmup` and `trade_flow_stale`, so the run is not measuring the intended absorption / mean-reversion edge.
- **What exists now**:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py` — warmup fallback quoting existed for both `indicator_warmup` and `trade_flow_stale`
  - `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv` — current fills are mostly fallback-state maker fills with negative net after fees
  - `hbot/reports/desk_snapshot/bot7/latest.json` — latest validation restart shows `open_orders: []` and `quote_side_mode=off`, so the inactive-state persistence blocker is cleared and the next window can focus on thesis-state activity
- **Design decision (pre-answered)**: fail closed on `trade_flow_stale`; keep only a short bootstrap-only warmup quote window; do not retune Bot7 signal thresholds in the same experiment cycle.
- **Implementation steps**:
  1. Update `hbot/controllers/bots/bot7/adaptive_grid_v1.py` and `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml` so stale-trade state places no quotes, all intentional inactive `off` states actively cancel lingering quote executors, and warmup quoting is bounded to the first few bootstrap bars.
  2. Run an isolated Bot7 paper window and compare fill-reason mix plus net pnl/fill after fees using only `probe_*` / `mean_reversion_*` activity.
- **Acceptance criteria**:
  - `indicator_warmup`, `trade_flow_stale`, `regime_inactive`, and `no_entry` produce `0` fills after the bootstrap window / intended fail-closed state.
  - Bot7 records at least `30` fills from `probe_*` or `mean_reversion_*` states.
  - Thesis-state net pnl/fill after fees is `>= 0`.
- **Do not**: do not change Bot7 RSI / ADX / probe thresholds in the same validation cycle.

### [P1-STRAT-20260305-2] Accelerate derisk force-taker escalation `blocked (superseded by later bot1 experiment direction)`
- **Why it matters**: slow derisk escalation extends exposure in non-productive safety states.
- **Implementation**:
  1. Set `derisk_force_taker_after_s: 45`.
  2. Set `derisk_progress_reset_ratio: 0.005`.
  3. Validate derisk dwell reduction in next sample window.
- **Acceptance criteria**:
  - `derisk_force_taker` and `eod_close_pending` frequencies decline vs prior cycle.
  - No worse drawdown tail beyond cycle guardrails.
- **Do not**: do not disable derisk or hard-stop protections.
 - **Current blocker**: later bot1 experiments intentionally moved force-taker behavior in the opposite direction after negative taker-expectancy evidence, so reopening this exact tuning requires a deliberate strategy decision, not another backlog-default config edit.

### [P1-STRAT-20260305-3] Run no-size-boost governor experiment `blocked (requires isolated observation window)`
- **Why it matters**: positive size boost under negative edge can amplify churn.
- **Implementation**:
  1. Set `pnl_governor_max_size_boost_pct: 0.00`.
  2. Run one isolated cycle without spread-group changes.
  3. Compare PnL/fill, drawdown, hard-stop ratios vs prior cycle.
- **Acceptance criteria**:
  - PnL/fill improves by >= 0.02 vs short-window baseline.
  - Max drawdown <= 4.5% during evaluation.
- **Do not**: do not change spread parameter group in this validation cycle.
 - **Current blocker**: the no-size-boost clamp is already reflected in the current bot1 config path; remaining closure depends on a clean post-change observation window rather than further implementation work.

### [P1-STRAT-20260305-4] Publish cancel-before-fill KPI in dossier `done (2026-03-10)`
- **Why it matters**: cancellation churn before fill is a missing quick-read execution KPI.
- **Implementation**:
  1. Add `cancel_before_fill_rows` and `cancel_before_fill_rate` to `hbot/scripts/analysis/performance_dossier.py`.
  2. Add markdown output line for this KPI.
  3. Extend dossier unit tests for deterministic metric computation.
- **Acceptance criteria**:
  - `reports/analysis/performance_dossier_latest.json` includes both fields.
  - Unit tests verify expected values from synthetic inputs.
- **Do not**: keep semantics aligned with scorecard formula.

### [P1-STRAT-20260305-5] Add fill-edge guard for governor size boost `done (2026-03-10)`
- **Why it matters**: deficit-based boost should not activate when realized fill edge is below cost floor.
- **Implementation**:
  1. Guard `_compute_pnl_governor_size_mult` when `fill_edge_ewma < -cost_floor_bps`.
  2. Emit reason `fill_edge_below_cost_floor`.
  3. Add unit test for blocked-boost path.
- **Acceptance criteria**:
  - Size multiplier remains `1.0` in negative-edge condition.
  - Guard reason appears in diagnostics.
- **Do not**: do not disable existing hard/soft caps.

### [P1-STRAT-20260305-7] Stabilize active submit order-id on retries `done (2026-03-10)`
- **Why it matters**: retry submit ID drift increases duplicate-order risk and weakens traceability.
- **Implementation**:
  1. Add short-TTL fingerprint cache for active submit order IDs in bridge state.
  2. Reuse order ID for identical retries in TTL window.
  3. Add tests for reuse and TTL-disabled behavior.
- **Acceptance criteria**:
  - Identical retries inside TTL reuse same `order_id`.
  - TTL `0` produces distinct IDs.
- **Do not**: keep sync-gate and failure-policy behavior intact.

### [P1-STRAT-20260305-8] Stabilize active cancel command id on retries `done (2026-03-10)`
- **Why it matters**: cancel retry command-ID drift bypasses service-side idempotency and adds audit noise.
- **Implementation**:
  1. Add cancel fingerprint/TTL cache.
  2. Reuse `command_event_id` for identical retries in TTL window.
  3. Add tests for reuse and TTL-disabled behavior.
- **Acceptance criteria**:
  - Identical cancel retries inside TTL share same event id.
  - TTL `0` produces distinct ids.
- **Do not**: do not weaken sync gating or failure-policy semantics.

### [P1-STRAT-20260305-9] Stabilize active cancel-all command id on retries `done (2026-03-10)`
- **Why it matters**: `cancel_all` retry ID drift reduces dedupe effectiveness and forensic clarity.
- **Implementation**:
  1. Add dedicated `cancel_all` command-ID cache.
  2. Reuse command ID for identical publishes in TTL window.
  3. Add tests for reuse and TTL-disabled behavior.
- **Acceptance criteria**:
  - Identical active `cancel_all` publishes in TTL share the same event id.
  - TTL `0` produces distinct ids.
- **Do not**: do not bypass privileged metadata checks.

### [P1-STRAT-20260305-11] Add adverse-fill confidence soft-pause gate `done (2026-03-10)`
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

### [P1-STRAT-20260305-12] Gate force-taker escalation by material imbalance `done (2026-03-10)`
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

### [P1-STRAT-20260305-13] Add rolling expectancy CI dossier gate signal `done (2026-03-10)`
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

### [P1-STRAT-20260305-14] Add edge-confidence soft-pause gate `done (2026-03-10)`
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

### [P1-STRAT-20260305-15] Add slippage shock soft-pause guard `done (2026-03-10)`
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

### [P1-STRAT-20260305-16] Enforce rolling expectancy CI in promotion gate `done (2026-03-10)`
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

### [P1-STRAT-20260305-17] Clamp force-taker derisk by taker expectancy `done (2026-03-10)`
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

### [P1-STRAT-20260305-18] Extend passive order lifetime to reduce queue reset churn `blocked (requires fresh cancel-churn evidence)`
- **Why it matters**: frequent cancel/recreate cycles reset queue progress and suppress passive fill opportunity.
- **Implementation**:
  1. Increase `regime_specs_override.*.refresh_s` for bot1.
  2. Keep force-derisk and soft-pause safety controls unchanged.
  3. Validate reduced cancel churn in logs/telemetry.
- **Acceptance criteria**:
  - Fewer cancel/recreate cycles per 10-minute window.
  - Passive orders rest long enough for queue-model fill opportunity.
- **Do not**: do not remove kill-switch/hard-stop controls.
 - **Current blocker**: bot1 refresh intervals are already longer than the original baseline; what remains is evidence collection on cancel/recreate frequency after those changes.

### [P1-STRAT-20260305-19] Add L2 stream contract + producer wiring `done (2026-03-10)`
- **Why it matters**: without a first-class depth contract, realtime UI cannot render order-book structure.
- **Implementation**:
  1. Add `MARKET_DEPTH_STREAM` and depth event schemas.
  2. Publish depth snapshots from runtime publisher.
  3. Keep L1 schema and stream behavior unchanged.
- **Acceptance criteria**:
  - `hb.market_depth.v1` emits valid payloads.
  - Existing `market_snapshot` consumers continue unchanged.

### [P1-STRAT-20260305-20] Deliver stream-first realtime API service `done (2026-03-10)`
- **Why it matters**: UI clients need a stable API contract over volatile stream internals.
- **Implementation**:
  1. Add `services/realtime_ui_api/main.py` with stateful stream consumers.
  2. Expose `/api/v1/state`, `/api/v1/candles`, `/api/v1/depth`, `/api/v1/positions`, `/api/v1/stream`.
  3. Add auth/CORS/rollout/fallback env controls.
- **Acceptance criteria**:
  - SSE stream and REST endpoints are healthy in compose.
  - Fallback to desk snapshot activates on stream staleness.

### [P1-STRAT-20260305-21] Deliver TradingView-like web UI module `done (2026-03-10)`
- **Why it matters**: operators need one execution-focused pane for chart + depth + position context.
- **Implementation**:
  1. Add static web app under `apps/realtime_ui`.
  2. Integrate lightweight charts and API polling/SSE updates.
  3. Add compose `realtime-ui-web` service for serving UI.
- **Acceptance criteria**:
  - UI renders candles, depth ladder, open orders, fills, and position panel.
  - Works in shadow mode against `realtime-ui-api`.

### [P1-STRAT-20260305-22] Wire realtime/L2 strict gate into promotion cycle `done (2026-03-10)`
- **Why it matters**: live migration needs fail-closed protection against silent data-plane regressions.
- **Implementation**:
  1. Add `scripts/release/check_realtime_l2_data_quality.py`.
  2. Integrate gate execution into promotion and strict-cycle runners.
  3. Include diagnostics in promotion runtime summary.
- **Acceptance criteria**:
  - `realtime_l2_data_quality` appears as a critical gate in strict cycle.
  - Gate report is emitted to verification artifacts.

### [P1-STRAT-20260305-23] Enforce rollout evidence and operator rollback path `done (2026-03-10)`
- **Why it matters**: controlled cutover requires explicit evidence and reversible rollout.
- **Implementation**:
  1. Add runbook + observability contract updates for shadow/active/disabled flow.
  2. Add strict-cycle thresholds for freshness/sequence/sampling/storage.
  3. Keep fallback path documented and testable.
- **Acceptance criteria**:
  - Runbook includes cutover and rollback commands.
  - Strict-cycle evidence references realtime/L2 artifacts.

### [P1-EXEC-20260309-1] Unify paper order-state vocabulary across bridge, runtime, and service `done (2026-03-10)`
- **Why it matters**: active-mode runtime currently translates between `working`, `open`, `partial`, `pending_create`, and legacy aliases, which increases artifact drift and makes operator evidence harder to trust.
- **Implementation**:
  1. Define one canonical order FSM vocabulary for paper execution read models.
  2. Align bridge runtime-order states, service `OrderRecord.state`, and operator artifacts on the same terms.
  3. Add compatibility adapters only at boundaries that cannot migrate immediately.
- **Acceptance criteria**:
  - State snapshots, runtime orders, and open-order artifacts use the same resting/terminal labels.
  - No bridge/service test relies on ad hoc state translation tables.

---

## P2 — Quality / Simulation Realism

### [P2-STRAT-20260305-6] Increase bot1 paper fill realism baseline `done (2026-03-10)`
- **Why it matters**: `best_price` model is optimistic and can overstate expected live performance.
- **Implementation**:
  1. Set `paper_engine.paper_fill_model: latency_aware` in bot1 config.
  2. Keep queue/latency knobs unchanged for controlled delta.
  3. Monitor slippage and maker ratio shift next cycle.
- **Acceptance criteria**:
  - Bot1 uses `latency_aware`.
  - Promotion/analysis scripts continue without parsing regressions.
- **Do not**: do not retune queue participation and slippage penalties in same step.

### [P2-STRAT-20260305-7] Add depth raw/sampled/rollup DB model `done (2026-03-10)`
- **Why it matters**: depth data volume can exhaust storage and query budgets without layered persistence.
- **Implementation**:
  1. Add `market_depth_raw`, `market_depth_sampled`, `market_depth_rollup_minute`.
  2. Add timescale retention/compression defaults for all depth layers.
  3. Add indexed query paths for pair/time windows.
- **Acceptance criteria**:
  - Tables and indexes exist via ops DB schema migration.
  - Retention/compression policies configured through env vars.

### [P2-STRAT-20260305-8] Add checkpointed depth ingestion path `done (2026-03-10)`
- **Why it matters**: full rescans of event JSONL are not safe at L2 throughput.
- **Implementation**:
  1. Add `market_depth_ingest_checkpoint` state table.
  2. Ingest only new rows from event store files.
  3. Keep ingestion idempotent via conflict keys.
- **Acceptance criteria**:
  - Re-runs do not duplicate depth records.
  - Checkpoint advances deterministically across files.

### [P2-STRAT-20260305-9] Harden observability contract for realtime/L2 `done (2026-03-10)`
- **Why it matters**: operators need explicit, auditable SLO-style expectations for realtime/L2 path.
- **Implementation**:
  1. Extend `monitoring/OBSERVABILITY_CONTRACT.md` with depth streams + evidence mapping.
  2. Add runbook steps for shadow/active migration and rollback.
  3. Align architecture docs to new services and stream topology.
- **Acceptance criteria**:
  - Docs include operator-ready migration/rollback procedures.
  - All strict gate artifacts have documented source-of-truth mapping.

### [P2-EXEC-20260309-1] Model maker queue priority in active paper exchange `done (2026-03-10)`
- **Why it matters**: active-mode resting orders currently fill as soon as price crosses, which is materially more optimistic than a live queue where earlier resting size has priority.
- **Implementation**:
  1. Apply a queue-ahead model in the service fill loop using configurable participation / queue depletion assumptions.
  2. Use depth-level size and order age to estimate available fillable quantity per snapshot.
  3. Add deterministic tests for queue delay and partial fill progression.
- **Acceptance criteria**:
  - Resting maker orders can remain unfilled after a cross when queue-ahead size is not exhausted.
  - Fill cadence changes are observable in service state and market-fill tests.

### [P2-EXEC-20260309-2] Enforce min-notional and tick-size constraints in paper exchange service `done (2026-03-10)`
- **Why it matters**: the service currently accepts orders that a real exchange would reject for step-size, lot-size, or min-notional violations, overstating strategy viability.
- **Implementation**:
  1. Propagate instrument constraints from bridge registration into service command validation.
  2. Reject out-of-increment, below-min-base, and below-min-notional orders with explicit reasons.
  3. Add tests for valid edge-case rounding and invalid-size rejection.
- **Acceptance criteria**:
  - Service rejects orders below live-equivalent minimums.
  - Validation reasons are visible in command journal artifacts.

### [P2-EXEC-20260309-3] Apply periodic funding debits/credits in active paper execution `done (2026-03-10)`
- **Why it matters**: active-mode orders persist funding-rate metadata, but positions are not periodically charged or credited like they would be on the real venue.
- **Implementation**:
  1. Add funding timestamp tracking and periodic position funding settlement in the service.
  2. Emit funding events and update state snapshots / PnL evidence.
  3. Add regression tests for long/short funding transfer sign and schedule handling.
- **Acceptance criteria**:
  - Active-mode positions accrue funding over time.
  - Funding impact is visible in verification artifacts and downstream desk accounting.

### [P2-EXEC-20260309-4] Verify multi-level market sweep depth in active fills `done (2026-03-10)`
- **Why it matters**: large taking orders should sweep across multiple book levels instead of assuming full execution at the first crossed price.
- **Implementation**:
  1. Audit and complete the service path that consumes multi-level contra depth for market and crossing limit orders.
  2. Add tests for partial first-level depletion and blended execution price across levels.
  3. Surface sweep-depth assumptions in service metrics and docs.
- **Acceptance criteria**:
  - Crossing orders use the configured number of depth levels.
  - Fill notional and average price match the expected multi-level sweep calculation.

---

## TECH — Initial Audit Follow-Through + 9.5 Score Uplift

> Goal: convert the `INITIAL_AUDIT` findings into active engineering work and close the gap from today’s baseline to a sustained `9.5/10` desk across reliability, performance, code health, test coverage, infrastructure, and dependency hygiene.

### 9.5/10 Target State
- **Reliability**: no active-bot reconciliation criticals, no active bots missing canonical snapshots, no stale critical evidence artifacts in strict cycle, and no known freeze-class regression without direct test coverage.
- **Performance**: tick-path, exporter render path, and event-store ingest path all publish bounded latency metrics with stable p95/p99 during normal operation.
- **Code health**: no orchestration god-class remains above the agreed size threshold without a documented boundary plan, and broad `except Exception` / silent `pass` paths are limited to explicitly justified edges.
- **Test coverage**: critical runtime/service failure paths are directly tested, and the release gate coverage floor reflects meaningful confidence rather than minimal smoke coverage.
- **Infrastructure**: strict/promotion gates consume fresh, current evidence; auth/network hardening is complete for operator surfaces; and service health matches artifact truth.
- **Dependencies/tooling**: periodic CVE/outdated audits exist, and any new library adoption is justified by measured operational benefit and bounded migration risk.

### 2-Week Execution Order
- **L-effort anchor**: `P0-TECH-20260309-1` — restore active-bot event parity and snapshot completeness first; this is the highest-leverage reliability blocker and unblocks trustworthy gate interpretation.
- **M-effort item**: `P1-TECH-20260309-4` — align strict-cycle evidence freshness with current artifacts so gates reflect live truth instead of stale evidence selection.
- **M-effort item**: `P1-TECH-20260309-2` — add hot-reload and exporter failure-path regression tests to lock in known incident fixes before deeper refactors.
- **M-effort item**: `P1-TECH-20260309-6` — eliminate silent exception swallowing in runtime and ops-critical paths so parity/exporter/snapshot failures remain visible but non-fatal.
- **Quick wins**:
  - Start `P2-TECH-20260309-8` by publishing bounded p50/p95/p99 metrics for controller tick, exporter render, and event-store ingest.
  - Start `P2-TECH-20260309-9` by adding a repeatable dependency freshness / CVE audit artifact.

### Follow-On Order After Sprint 1
- `P1-TECH-20260309-3` — split exporter render path and add observability budget once failure-path tests and evidence freshness are stable.
- `P2-TECH-20260309-8` — finish runtime performance budgets and wire them into verification/gates.
- `P2-TECH-20260309-7` — raise critical-path test confidence and only then tighten the release coverage floor.
- `P1-TECH-20260309-5` — decompose shared runtime/controller orchestration hotspots after the reliability and observability base is stable.
- `P2-TECH-20260309-9` — keep dependency/tooling governance as bounded hygiene work, not the critical path.

### [P0-TECH-20260309-1] Restore active-bot event parity and snapshot completeness `done (2026-03-10)`
- **Why it matters**: the current audit found `reconciliation_status=critical` and active bots producing fills/minute activity without matching event-store evidence, which undermines operator trust and blocks promotion.
- **Implementation**:
  1. Trace and repair the missing `order_filled` / bot-minute snapshot path across controller publish, paper-exchange event emission, and event-store ingestion.
  2. Add deterministic fixtures for active-day parity failures (`fills_present_without_order_filled_events`) so the current gap is reproducible in tests.
  3. Emit per-bot diagnostics that identify whether a parity gap comes from publisher, ingest, or artifact-selection failure.
- **Acceptance criteria**:
  - `reports/reconciliation/latest.json` has no fill-parity criticals for active bots.
  - No active bot appears under `active_bots_without_snapshots` during healthy runtime.
  - Strict/promotion gates stop failing on reconciliation due to missing event evidence.
- **Do not**:
  - Do not relax reconciliation severity or remove the parity check to make the gate pass.

### [P1-TECH-20260309-2] Add hot-reload and exporter failure-path regression tests `done (2026-03-10)`
- **Why it matters**: known incident classes are only partially protected today because the runtime code exists but the exact failure paths are not directly regression-tested.
- **Implementation**:
  1. Add a direct invalid-config hot-reload suite for `scripts/shared/v2_with_controllers.py` covering validation failure, last-known-good retention, degraded retry, and recovery.
  2. Add an exporter test that forces `_render_prometheus_impl()` to fail after a successful render and verifies stale-cache fallback behavior.
  3. Add one focused Redis stream failure/recovery regression around a real runtime/service boundary if practical in the same pass.
- **Acceptance criteria**:
  - Invalid controller config reload no longer lacks direct regression coverage.
  - Exporter render failure fallback is verified by a deterministic test.
  - New tests pass under `python scripts/release/run_tests.py`.
- **Do not**:
  - Do not redesign the runtime hot-reload path as part of this test-first item.

### [P1-TECH-20260309-3] Split exporter render path and add observability budget `done (2026-03-10)`
- **Why it matters**: `services/bot_metrics_exporter.py` is one of the clearest current hot spots, with scrape-time file scans and large mixed-responsibility rendering logic.
- **Implementation**:
  1. Split exporter internals into collection, history aggregation, and formatting helpers while keeping the external metric contract stable.
  2. Add exporter self-metrics for render duration, cache-hit ratio, stale-cache fallback count, and source-read failures.
  3. Reduce full-history rescans where a bounded or cached computation can safely replace them.
- **Acceptance criteria**:
  - Existing metric names remain backward compatible.
  - Exporter exposes timing/fallback diagnostics.
  - Render cost becomes measurable and improves or is explicitly bounded in the next audit cycle.
- **Do not**:
  - Do not remove cache fallback or hide source-read failures to make metrics look healthier.

### [P1-TECH-20260309-4] Align strict-cycle evidence freshness with current artifacts `done (2026-03-10)`
- **Why it matters**: several critical gate failures are caused by stale or incomplete evidence selection, which makes release status noisier than the live data plane truth.
- **Implementation**:
  1. Audit artifact lookup logic for event-store, parity, realtime L2, and reconciliation checks and prefer the freshest valid evidence.
  2. Distinguish stale artifact selection from true runtime/data-plane failure in gate diagnostics.
  3. Add tests for stale-vs-fresh artifact resolution behavior.
- **Acceptance criteria**:
  - Freshness failures map to actually stale evidence rather than obsolete artifact paths.
  - Gate diagnostics explain stale-selection vs runtime failure clearly.
  - Artifact-selection tests cover the critical evidence families.
- **Do not**:
  - Do not suppress critical gate failures without fixing evidence resolution.

### [P1-TECH-20260309-5] Decompose shared runtime/controller orchestration hotspots `done (2026-03-10)`
- **Why it matters**: `shared_mm_v24.py`, `v2_with_controllers.py`, `hb_bridge.py`, and `paper_exchange_service/main.py` still centralize too many responsibilities, keeping correctness and restart behavior fragile.
- **Implementation**:
  1. Break up the largest orchestration functions into smaller units with explicit state and boundary ownership.
  2. Move duplicated output/shaping logic toward `tick_emitter.py` and duplicated spread handling toward `spread_engine.py`.
  3. Document and enforce the intended ownership boundary for controller tick, bus orchestration, bridge translation, and execution service state.
- **Acceptance criteria**:
  - At least one major god-class hotspot is materially reduced without behavior drift.
  - Duplicate output/spread shaping paths are consolidated behind one canonical owner.
  - Boundary docs and tests reflect the reduced responsibility overlap.
- **Do not**:
  - Do not mix strategy-lane logic back into shared/runtime modules.

### [P1-TECH-20260309-6] Eliminate silent exception swallowing in runtime and ops-critical paths `done (2026-03-10)`
- **Why it matters**: broad `except Exception` and silent `pass` paths are still masking failures in heartbeat writing, open-order snapshots, bridge event consumption, exporter reads, and paper sync logic.
- **Implementation**:
  1. Inventory the highest-risk silent exception sites in runtime, bridge, exporter, and service code.
  2. Replace silent swallows with structured logging, counters, or explicit degraded-state markers where failure should remain non-fatal.
  3. Add regression tests for at least the top failure sites so silent masking cannot return unnoticed.
- **Acceptance criteria**:
  - The highest-risk silent swallow sites are removed or explicitly instrumented.
  - New logs/metrics make operational failure visible without crashing the bot.
  - Tests verify the intended degraded-but-visible behavior.
- **Do not**:
  - Do not turn non-fatal operational errors into hard crashes without an approved failure policy.

### [P2-TECH-20260309-7] Raise critical-path test confidence above the current minimal gate `done (2026-03-10)`
- **Why it matters**: the deterministic suite currently passes with `17.92%` total coverage and a `5%` floor, which is too weak for a `9.5/10` engineering target.
- **Implementation**:
  1. Define a named critical-path coverage set for controller runtime, bridge, paper-exchange service, event-store, reconciliation, and exporter.
  2. Add missing failure-path tests until the critical set has meaningful direct coverage.
  3. Raise the coverage expectation in the release gate once the critical-path suite is in place.
- **Acceptance criteria**:
  - Critical runtime/service paths have explicit direct regression coverage.
  - Release/test artifacts surface critical-path coverage separately from global repo coverage.
  - Coverage floor is increased only after the critical-path suite is stable.
- **Do not**:
  - Do not inflate coverage with low-signal tests that avoid the real failure paths.

### [P2-TECH-20260309-8] Codify runtime performance budgets in artifacts and gates `done (2026-03-10)`
- **Why it matters**: the audit identified likely bottlenecks, but the repo still lacks one consistent, fresh source of truth for tick latency, exporter latency, and event-store ingest cost.
- **Implementation**:
  1. Publish bounded performance metrics for controller tick, exporter render, paper-exchange processing, and event-store ingest.
  2. Add freshness and threshold checks for those metrics in verification artifacts.
  3. Use the next audit cycle to compare measured budgets against current thresholds and tune only with evidence.
- **Acceptance criteria**:
  - Performance artifacts report p50/p95/p99 for the critical paths.
  - The next audit can score performance from fresh metrics rather than inference.
  - Gate diagnostics identify which subsystem violates budget when regressions occur.
- **Do not**:
  - Do not remove safety controls or persistence guarantees just to hit latency targets.

### [P2-TECH-20260309-9] Establish quarterly dependency and CVE review with bounded adoption rules `done (2026-03-10)`
- **Why it matters**: the dependency set is reasonably modern, but there is no current artifact-backed CVE/outdated review and no explicit upgrade policy for performance-oriented libraries.
- **Implementation**:
  1. Add a repeatable dependency audit artifact covering outdated packages, CVEs, and upgrade risk.
  2. Evaluate `orjson` and `redis.asyncio` only behind bounded experiments with rollback.
  3. Keep `structlog` / `anyio` deferred unless there is a measured operational need.
- **Acceptance criteria**:
  - Dependency freshness and CVE status are visible in a report artifact.
  - Any adoption decision includes effort, rollback, and measured benefit.
  - The audit loop can score dependency freshness from evidence rather than assumption.
- **Do not**:
  - Do not add new libraries without a concrete measured benefit and bounded migration plan.

---

## PERF — Initial Audit Follow-Through

> Goal: convert the `INITIAL_AUDIT` findings into bounded performance work so the desk has explicit latency, disk, and UI responsiveness budgets instead of inferred health.

### Performance Target State
- **Trading-critical latency**: controller tick, paper-sync, fill handling, and event-store ingest publish fresh `p50/p95/p99/max` metrics with stable bounded tails during normal load.
- **Disk efficiency**: event-store, exporter, and UI fallback paths avoid repeated whole-history rescans and keep append/rewrite pressure proportional to live workload.
- **Redis/inter-service efficiency**: consumer lag, stream depth, and ack cost remain bounded under normal and 2x replay traffic.
- **Frontend responsiveness**: the default realtime route ships measured chunk sizes, avoids avoidable rerender fan-out, and stays stable during long operator sessions.
- **Artifact hygiene**: stale green readiness/performance evidence cannot remain authoritative, and high-growth artifacts/logs are retained on explicit bounded policies.

### 2-Week Execution Order
- **L-effort anchor**: `P1-PERF-20260309-1` — bound event-store ingest and Redis ack cost first because it is the clearest depth-era saturation risk and currently lacks fresh passing budget evidence.
- **M-effort item**: `P1-PERF-20260309-2` — move exporter history work off the scrape path so observability does not compete with trading runtime as history grows.
- **M-effort item**: `P1-PERF-20260309-3` — add bounded realtime API fallback readers so degraded-mode operator recovery does not rely on repeated whole-file scans.
- **M-effort item**: `P1-PERF-20260309-4` — reduce realtime dashboard rerender fan-out and split the heavy realtime bundle after the backend hot paths have measurable budgets.
- **Quick wins**:
  - Start `P2-PERF-20260309-5` by failing closed on stale readiness/performance artifacts.
  - Use `hbot/tests/scripts/test_check_runtime_performance_budgets.py` and related release checks as the acceptance harness for new budget evidence where possible.

### Follow-On Order After Sprint 1
- `P1-TECH-20260309-3` — split exporter internals further once scrape-path work is bounded and measurable.
- `P2-TECH-20260309-8` — extend runtime budgets to additional sub-steps such as paper sync and fill handling.
- `P1-TECH-20260309-5` — decompose orchestration hot spots after the highest-cost paths have timing evidence.
- `P1-TECH-20260309-4` — keep artifact freshness work aligned so performance regressions cannot hide behind obsolete green evidence.

### [P1-PERF-20260309-1] Bound event-store ingest and Redis ack path `done (2026-03-10)`
- **Why it matters**: depth-era event volume can saturate Redis round trips and sync disk I/O before the current budget artifact shows actionable latency evidence.
- **What exists now**:
  - `hbot/services/event_store/main.py` appends JSONL with `fsync`, rewrites stats atomically, and acknowledges entries one-by-one.
  - `hbot/services/hb_bridge/redis_client.py` already exposes `ack_many`, but the event-store hot path does not use it.
  - `hbot/reports/verification/runtime_performance_budgets_latest.json` is `warning` because `event_store_ingest_p95_budget` has `samples=0`.
- **Implementation**:
  1. Replace per-entry ack loops with grouped `ack_many()` calls per stream after durable persistence succeeds.
  2. Publish fresh event-store ingest duration and lag evidence on every healthy cycle so the budget check has non-zero samples.
  3. Add a bounded replay/load test for normal and 2x depth traffic.
- **Acceptance criteria**:
  - `event_store_ingest_ms` reports non-zero samples in the next runtime budget artifact.
  - Ingest `p95` stays within the agreed budget during bounded replay.
  - Pending lag and sequence-integrity diagnostics do not regress.
- **Do not**:
  - Do not acknowledge events before file/DB persistence succeeds.

### [P1-PERF-20260309-2] Move exporter history work off scrape path `done (2026-03-10)`
- **Why it matters**: scrape-time rescans of `minute.csv` and `fills.csv` make observability cost grow with artifact size and can steal CPU/disk from trading services.
- **What exists now**:
  - `hbot/services/bot_metrics_exporter.py` computes minute/fill history from file scans during render.
  - `hbot/reports/verification/runtime_performance_budgets_latest.json` shows exporter render within budget, but only with `5` samples.
- **Implementation**:
  1. Cache or incrementally maintain minute/fill history summaries instead of rebuilding them on each scrape.
  2. Split scrape rendering from source collection so `/metrics` formats already-prepared state.
  3. Expose render-cost and source-read counters as first-class self-metrics.
- **Acceptance criteria**:
  - Exporter render `p95` improves or remains explicitly bounded at the same history size.
  - Source reads per scrape are measurably reduced.
  - Existing metric names remain backward compatible.
- **Do not**:
  - Do not hide source-read failures or remove stale-cache fallback.

### [P1-PERF-20260309-3] Add bounded realtime API fallback readers `done (2026-03-10)`
- **Why it matters**: degraded-mode UI recovery currently relies on expensive whole-file CSV scans that get slower as logs grow.
- **What exists now**:
  - `hbot/services/realtime_ui_api/main.py` rebuilds candles, fills, daily review, and journal review from CSVs when stream/DB paths are stale.
  - `hbot/apps/realtime_ui_v2/` depends on those endpoints for degraded operator workflows.
- **Implementation**:
  1. Introduce incremental or tail-based readers for `minute.csv` and `fills.csv` with bounded day-range caching.
  2. Add per-endpoint diagnostics for rows scanned, fallback source, and latency.
  3. Use DB or cached slices first, then CSV only as a bounded last resort.
- **Acceptance criteria**:
  - `/api/v1/state` and review endpoint `p95` improve under forced degraded mode.
  - Maximum scanned rows per request are bounded by configuration.
  - Fallback diagnostics show which source was used and how expensive it was.
- **Do not**:
  - Do not remove degraded-mode fallback entirely.

### [P1-PERF-20260309-4] Reduce realtime dashboard rerender fan-out and split bundle `done (2026-03-10)`
- **Why it matters**: the default operator route eagerly loads the heaviest panels, and store-wide updates can trigger avoidable render work during live traffic.
- **What exists now**:
  - `hbot/apps/realtime_ui_v2/src/store/useDashboardStore.ts` snapshot/event/rest ingestion rewrites many top-level slices at once.
  - `hbot/apps/realtime_ui_v2/src/App.tsx` eagerly loads the realtime dashboard path.
  - `hbot/apps/realtime_ui_v2/vite.config.ts` has no chunk strategy or bundle reporting.
- **Implementation**:
  1. Narrow store selectors and avoid rebuilding unchanged slices on snapshot/rest updates.
  2. Split the realtime route or its heaviest panels into lazy chunks.
  3. Add a bundle report artifact and one browser-profile smoke check.
- **Acceptance criteria**:
  - Initial JS payload decreases from the current build baseline.
  - React commit or long-task cost drops during a bounded live-session profile.
  - Realtime data fidelity and panel correctness remain unchanged.
- **Do not**:
  - Do not reduce event fidelity or truncate critical operator data to improve benchmark numbers.

### [P2-PERF-20260309-5] Enforce freshness and retention hygiene for performance evidence `done (2026-03-10)`
- **Why it matters**: stale green artifacts and weak retention coverage hide regressions and increase disk/log growth.
- **What exists now**:
  - `hbot/reports/readiness/final_decision_latest.json` still reports stale `GO` while newer strict/perf artifacts are red or warning.
  - `hbot/config/artifact_retention_policy.json` defaults to `dry_run` and only covers part of the artifact surface.
  - `hbot/monitoring/promtail/promtail-config.yml` ingests `epp_v24` CSV artifacts into Loki.
- **Implementation**:
  1. Add freshness validation for readiness and performance `latest` artifacts so stale green evidence cannot remain authoritative.
  2. Expand retention coverage and schedule real `--apply` runs for high-growth artifact paths.
  3. Stop ingesting low-value CSV artifact streams into Loki unless a measured operator use case requires them.
- **Acceptance criteria**:
  - No stale `GO` artifact remains authoritative when newer strict evidence is red.
  - Retention reports show actual deletions or bounded expirations.
  - Artifact and Loki daily growth decline in the next audit cycle.
- **Do not**:
  - Do not delete current source-of-truth artifacts needed for promotion, reconciliation, or auditability.

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

