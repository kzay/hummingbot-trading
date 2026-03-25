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
| ROAD-13 | P1 | `done (2026-03-11)` | `frontend-eng` | `2026-03-19` | `apps/realtime_ui_v2/` |
| ROAD-14 | P2 | `blocked: fresh depth gate evidence` | `data-eng` | `2026-03-21` | `reports/ops_db_writer/latest.json` |
| P1-STRAT-20260305-19 | P1 | `done (2026-03-10)` | `platform-eng` | `2026-03-15` | `services/contracts/event_schemas.py` |
| P1-STRAT-20260305-20 | P1 | `done (2026-03-10)` | `platform-eng` | `2026-03-16` | `services/realtime_ui_api/main.py` |
| P1-STRAT-20260305-21 | P1 | `done (2026-03-10)` | `frontend-eng` | `2026-03-16` | `apps/realtime_ui/index.html` |
| P1-STRAT-20260305-22 | P1 | `done (2026-03-10)` | `ops-eng` | `2026-03-17` | `scripts/release/run_promotion_gates.py` |
| P1-STRAT-20260305-23 | P1 | `done (2026-03-10)` | `ops-eng` | `2026-03-17` | `reports/verification/realtime_l2_data_quality_latest.json` |
| P1-QUANT-20260309-1 | P1 | `blocked: ADX gate — see P1-QUANT-20260311-1` | `strategy-eng` | `2026-03-13` | `data/bot7/logs/epp_v24/bot7_a/fills.csv` |
| P1-QUANT-20260311-1 | P1 | `done (2026-03-11)` | `strategy-eng` | `2026-03-13` | `data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml` |
| P2-STRAT-20260305-6 | P2 | `done (2026-03-10)` | `strategy-eng` | `2026-03-10` | `data/bot1/conf/controllers/epp_v2_4_bot_a.yml` |
| P2-STRAT-20260305-7 | P2 | `done (2026-03-10)` | `data-eng` | `2026-03-18` | `services/ops_db_writer/schema_v1.sql` |
| P2-STRAT-20260305-8 | P2 | `done (2026-03-10)` | `platform-eng` | `2026-03-18` | `services/event_store/main.py` |
| P2-STRAT-20260305-9 | P2 | `done (2026-03-10)` | `ops-eng` | `2026-03-20` | `infra/monitoring/OBSERVABILITY_CONTRACT.md` |
| ROAD-10 | P1 | `done (2026-03-25)` | `ml-eng` | `2026-03-25` | `data/ml/models/regime/` |
| ROAD-11 | P1 | `done (2026-03-25)` | `ml-eng` | `2026-03-25` | `data/ml/models/adverse/` |
| OPS-PREREQ-1 | blocked | `blocked` | `ops-eng` | `2026-03-08` | `reports/ops/telegram_validation_latest.json` |
| OPS-PREREQ-2 | blocked | `blocked` | `security-eng` | `2026-03-12` | `docs/ops/runbooks.md` |
| P0-QUANT-20260311-1 | P0 | `done (2026-03-11)` | `strategy-eng` | `2026-03-11` | `data/bot1/conf/controllers/epp_v2_4_bot_a.yml` |
| P0-QUANT-20260311-2 | P0 | `done (2026-03-11)` | `strategy-eng` | `2026-03-11` | `data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml` |
| P1-QUANT-20260311-2 | P1 | `done (2026-03-11)` | `strategy-eng` | `2026-03-13` | `data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml` |
| P1-QUANT-20260311-3 | P1 | `done (2026-03-11)` | `strategy-eng` | `2026-03-14` | `data/bot5/logs/epp_v24/bot5_a/fills.csv` |
| P1-QUANT-20260311-4 | P1 | `done (2026-03-12)` | `strategy-eng` | `2026-03-14` | `controllers/bots/bot5/ift_jota_v1.py` |
| P1-QUANT-20260311-5 | P1 | `done (2026-03-11)` | `strategy-eng` | `2026-03-14` | `controllers/bots/bot6/cvd_divergence_v1.py` |
| P1-QUANT-20260311-6 | P1 | `done (2026-03-12)` | `strategy-eng` | `2026-03-18` | `controllers/bots/bot6/cvd_divergence_v1.py` |
| P2-QUANT-20260311-1 | P2 | `in-progress (2026-03-12)` | `strategy-eng` | `2026-03-18` | `data/bot1/conf/controllers/epp_v2_4_bot1_wider_spread_exp.yml` |
| P2-QUANT-20260311-2 | P2 | `blocked (requires P1-QUANT-20260311-2 probe evidence)` | `strategy-eng` | `2026-03-20` | `controllers/bots/bot7/adaptive_grid_v1.py` |
| P0-STRAT-20260312-1 | P0 | `done (2026-03-12)` | `strategy-eng` | `2026-03-14` | `controllers/bots/bot7/adaptive_grid_v1.py` |
| P0-STRAT-20260312-2 | P0 | `done (2026-03-12)` | `strategy-eng` | `2026-03-14` | `controllers/shared_mm_v24.py` |
| P1-STRAT-20260312-1 | P1 | `done (2026-03-12)` | `strategy-eng` | `2026-03-12` | `data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml` |
| P1-STRAT-20260312-2 | P1 | `done (2026-03-12)` | `execution-eng` | `2026-03-18` | `controllers/paper_engine_v2/hb_bridge.py` |
| P0-TECH-20260312-1 | P0 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/paper_engine_v2/desk.py` |
| P1-TECH-20260312-1 | P1 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/telemetry_mixin.py` |
| P2-TECH-20260312-1 | P2 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/paper_engine_v2/portfolio.py` |
| P2-TECH-20260312-2 | P2 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/daily_state_store.py` |
| P1-PERF-20260312-1 | P1 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/paper_engine_v2/state_store.py` |
| P1-PERF-20260312-2 | P1 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/risk_mixin.py` |
| P1-PERF-20260312-3 | P1 | `done (2026-03-12)` | `execution-eng` | `2026-03-12` | `controllers/paper_engine_v2/hb_bridge.py` |
| P2-PERF-20260312-4 | P2 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/components/` |
| P2-PERF-20260312-5 | P2 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/utils/realtimeParsers.ts` |
| P2-PERF-20260312-6 | P2 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `controllers/paper_engine_v2/desk.py` |
| P1-OPS-20260312-1 | P1 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `services/control_plane_metrics_exporter.py` |
| P1-OPS-20260312-2 | P1 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `infra/compose/docker-compose.yml` |
| P1-OPS-20260312-3 | P1 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `docs/ops/incident_playbooks/` |
| P1-OPS-20260312-4 | P1 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `infra/monitoring/prometheus/alert_rules.yml` |
| P1-OPS-20260312-5 | P1 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `infra/monitoring/promtail/promtail-config.yml` |
| P2-OPS-20260312-6 | P2 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `infra/monitoring/grafana/provisioning/datasources/datasource.yml` |
| P2-OPS-20260312-7 | P2 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `infra/compose/docker-compose.yml` |
| P2-OPS-20260312-8 | P2 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `docs/ops/incident_playbooks/` |
| P2-OPS-20260312-9 | P2 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `infra/compose/docker-compose.yml` |
| P2-OPS-20260312-10 | P2 | `done (2026-03-12)` | `ops-eng` | `2026-03-12` | `config/artifact_retention_policy.json` |
| P1-FRONT-20260312-1 | P1 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/components/TopBar.tsx` |
| P1-FRONT-20260312-2 | P1 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/utils/fetch.ts` |
| P2-FRONT-20260312-3 | P2 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/components/Panel.tsx` |
| P2-FRONT-20260312-4 | P2 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/constants.ts` |
| P2-FRONT-20260312-5 | P2 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/components/` |
| P2-FRONT-20260312-6 | P2 | `done (2026-03-12)` | `frontend-eng` | `2026-03-12` | `apps/realtime_ui_v2/src/hooks/useRealtimeTransport.test.ts` |
| P0-STRAT-20260316-1 | P0 | `done (2026-03-17)` | `execution-eng` | `2026-03-18` | `controllers/fill_handler_mixin.py` |
| P0-STRAT-20260316-2 | P0 | `done (2026-03-17)` | `strategy-eng` | `2026-03-17` | `controllers/auto_calibration_mixin.py` |
| P1-STRAT-20260316-3 | P1 | `done (2026-03-17)` | `strategy-eng` | `2026-03-20` | `controllers/bots/bot6/cvd_divergence_v1.py` |
| P1-STRAT-20260316-4 | P1 | `done (2026-03-17)` | `strategy-eng` | `2026-03-20` | `controllers/bots/bot6/cvd_divergence_v1.py` |
| P1-STRAT-20260316-5 | P1 | `done (2026-03-17)` | `strategy-eng` | `2026-03-20` | `controllers/shared_mm_v24.py` |
| P1-STRAT-20260316-6 | P1 | `done (2026-03-17)` | `strategy-eng` | `2026-03-20` | `controllers/position_mixin.py` |
| P1-STRAT-20260316-7 | P1 | `done (2026-03-17)` | `execution-eng` | `2026-03-20` | `controllers/fill_handler_mixin.py` |
| P2-STRAT-20260316-8 | P2 | `done (2026-03-17)` | `strategy-eng` | `2026-03-23` | `controllers/bots/bot6/cvd_divergence_v1.py` |
| P2-STRAT-20260316-9 | P2 | `done (2026-03-17)` | `strategy-eng` | `2026-03-23` | `controllers/bots/bot6/cvd_divergence_v1.py` |
| P2-STRAT-20260316-10 | P2 | `done (2026-03-17)` | `strategy-eng` | `2026-03-23` | `controllers/daily_state_store.py` |
| P2-STRAT-20260316-11 | P2 | `done (2026-03-17)` | `strategy-eng` | `2026-03-25` | `(multiple)` |
| **INITIAL AUDIT — Semi-Pro Hardening (2026-03-17)** | | | | | |
| P0-QUANT-20260317-1 | P0 | `done (2026-03-17)` | `strategy-eng` | `2026-03-19` | `data/bot1/conf/controllers/epp_v2_4_bot_a.yml` |
| P1-OPS-20260317-1 | P1 | `done (2026-03-17)` | `ops-eng` | `2026-03-21` | `infra/monitoring/grafana/dashboards/` |
| P1-OPS-20260317-2 | P1 | `done (2026-03-17)` | `ops-eng` | `2026-03-20` | `config/artifact_retention_policy.json` |
| P1-OPS-20260317-3 | P1 | `done (2026-03-17)` | `ops-eng` | `2026-03-20` | `infra/compose/docker-compose.yml` |
| P1-OPS-20260317-4 | P1 | `done (2026-03-17)` | `ops-eng` | `2026-03-21` | `infra/compose/docker-compose.yml` |
| P1-OPS-20260317-5 | P1 | `done (2026-03-17)` | `ops-eng` | `2026-03-19` | `reports/ops/telegram_validation_latest.json` |
| P1-TECH-20260317-1 | P1 | `done (2026-03-17)` | `platform-eng` | `2026-03-21` | `hbot/tests/` |
| P1-TECH-20260317-2 | P1 | `done (2026-03-17)` | `platform-eng` | `2026-03-24` | `infra/compose/images/control_plane/requirements-control-plane.txt` |
| P1-TECH-20260317-3 | P1 | `done (2026-03-17)` | `platform-eng` | `2026-03-28` | `controllers/shared_mm_v24.py` |
| P1-PERF-20260317-1 | P1 | `done (2026-03-17)` | `execution-eng` | `2026-03-24` | `controllers/tick_emitter.py` |
| P1-PERF-20260317-2 | P1 | `done (2026-03-17)` | `execution-eng` | `2026-03-21` | `controllers/shared_mm_v24.py` |
| P1-PERF-20260317-3 | P1 | `done (2026-03-17)` | `execution-eng` | `2026-03-24` | `controllers/paper_engine_v2/portfolio.py` |
| P1-FRONT-20260317-1 | P1 | `done (2026-03-17)` | `frontend-eng` | `2026-03-21` | `apps/realtime_ui_v2/src/components/TopBar.tsx` |
| P1-FRONT-20260317-2 | P1 | `done (2026-03-17)` | `frontend-eng` | `2026-03-20` | `apps/realtime_ui_v2/package.json` |
| P1-QUANT-20260317-1 | P1 | `done (2026-03-17)` | `strategy-eng` | `2026-03-28` | `controllers/bots/bot7/pullback_v1.py` |
| P1-QUANT-20260317-2 | P1 | `done (2026-03-17)` | `strategy-eng` | `2026-03-28` | `controllers/paper_engine_v2/fill_models.py` |
| P2-OPS-20260317-1 | P2 | `done (2026-03-17)` | `ops-eng` | `2026-03-24` | `infra/compose/docker-compose.yml` |
| P2-OPS-20260317-2 | P2 | `done (2026-03-17)` | `ops-eng` | `2026-03-21` | `infra/compose/docker-compose.yml` |
| P2-OPS-20260317-3 | P2 | `done (2026-03-17)` | `ops-eng` | `2026-03-28` | `hbot/tests/integration/` |
| P2-FRONT-20260317-1 | P2 | `done (2026-03-17)` | `frontend-eng` | `2026-03-24` | `apps/realtime_ui_v2/src/store/useDashboardStore.ts` |
| P2-FRONT-20260317-2 | P2 | `done (2026-03-17)` | `frontend-eng` | `2026-03-28` | `apps/realtime_ui_v2/src/hooks/useRealtimeTransport.ts` |
| P2-FRONT-20260317-3 | P2 | `done (2026-03-17)` | `frontend-eng` | `2026-03-28` | `apps/realtime_ui_v2/src/components/` |
| P2-FRONT-20260317-4 | P2 | `done (2026-03-17)` | `frontend-eng` | `2026-03-28` | `apps/realtime_ui_v2/src/components/` |
| P2-PERF-20260317-1 | P2 | `done (2026-03-17)` | `frontend-eng` | `2026-03-24` | `apps/realtime_ui_v2/` |
| P2-TECH-20260317-1 | P2 | `done (2026-03-17)` | `platform-eng` | `2026-04-04` | `controllers/paper_engine_v2/hb_bridge.py` |
| P2-TECH-20260317-2 | P2 | `done (2026-03-17)` | `platform-eng` | `2026-04-04` | `services/paper_exchange_service/main.py` |
| P2-QUANT-20260317-1 | P2 | `done (2026-03-17)` | `strategy-eng` | `2026-03-28` | `controllers/bots/bot5/ift_jota_v1.py` |
| P2-QUANT-20260317-2 | P2 | `done (2026-03-17)` | `strategy-eng` | `2026-03-28` | `controllers/bots/bot6/cvd_divergence_v1.py` |

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

### [ROAD-13] TradingView-like operator app v1 `done (2026-03-11)`
- **Why it matters**: Grafana is control-plane observability; execution operations need a dedicated realtime trading view.
- **Implementation**:
  1. Run `realtime-ui-api` (`disabled -> shadow -> active`) with SSE updates.
  2. Deliver `apps/realtime_ui_v2` (React/TypeScript/Vite) for chart, orders/fills overlays, position panel, and depth ladder.
  3. Keep desk-snapshot fallback for stale stream recovery.
- **Acceptance criteria**:
  - End-to-end live updates for market, fills, orders, positions, and depth.
  - API health/metrics endpoints wired in compose health checks.
  - Shadow rollout validated before `active` mode.
- **Closure evidence (2026-03-11)**:
  - API mode `active`, source `stream`, stream age 64 ms, Redis/DB available, 8 instances tracked.
  - Live data verified: market (`BTC-USDT`, mid `70015.15`), depth, position, 2 open orders, 376 fills, 300 candles.
  - UI: 10 panels rendered, WS `connected`, API `ok`, 47 msg/min, 0 console/page errors.
  - Performance: ScriptDuration 0.29s/60s (down from 48.6s), heap 10-15 MB stable, no crashes or memory leaks.
  - All views (Realtime, Service, History, Daily Review, Weekly Review, Journal) render correctly.
  - Audit findings (H1-H7, M1-M10) implemented: runtimeEvents ring buffer, memoized table/depth data, cached formatNumber, deduplicated instance fetching, nginx hardening, error boundary retry.

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

### [P1-QUANT-20260309-1] Isolate Bot7 thesis from fallback quote states `blocked (ADX gate too tight — see P1-QUANT-20260311-1)`
- **Why it matters**: Bot7's current paper fills are dominated by `indicator_warmup` and `trade_flow_stale`, so the run is not measuring the intended absorption / mean-reversion edge.
- **What exists now**:
  - `hbot/controllers/bots/bot7/adaptive_grid_v1.py` — warmup fallback quoting bounded to `bot7_warmup_quote_max_bars=3` bars; `trade_flow_stale` and other non-thesis states now fail closed (fixed in EXP-20260311-02)
  - `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv` — 159 lifetime fills (2026-03-09 to 2026-03-11); only 1 thesis fill (probe_long); non-thesis fills were primarily runtime-order bug (now fixed) and `regime_inactive` from ADX > 22
  - `hbot/reports/desk_snapshot/bot7/latest.json` — post-fix restart confirmed `open_orders: []`, `quote_side_mode=off`; runtime-order leak fully closed
- **Design decision (pre-answered)**: fail closed on `trade_flow_stale` — DONE. Warmup quoting bounded — DONE. Runtime-order cleanup — DONE. Remaining blocker is that `bot7_adx_activate_below=22` is too tight to ever produce thesis fills in ranging BTC markets; see P1-QUANT-20260311-1.
- **Current blocker**: operational isolations are complete; the strategy now correctly idles, but the ADX < 22 regime gate prevents all thesis activity even in low-volatility BTC conditions; 1/159 fills is thesis-state (0.6%); cannot reach 30 thesis fills without a threshold change.

### [P1-QUANT-20260311-1] Bot7 ADX threshold relaxation experiment `done (2026-03-11)`
- **Why it matters**: After operational fixes, Bot7 has produced only 1 thesis fill in 3 days of runtime; the `bot7_adx_activate_below=22` regime gate blocks ~63% of all fill windows even when BTC is ranging; the strategy cannot be viability-assessed without more signal.
- **Closure evidence (2026-03-11)**:
  - `bot7_adx_activate_below` raised 22 → 28 (config confirmed).
  - `bot7_adx_neutral_fallback_below` raised 30 → 35 (EXP-20260311-03) to unlock gate at current BTC ADX-14 levels (34–38 observed in minute.csv post-restart).
  - `time_limit` extended 900 → 1200s to reduce fee-burning time-limit exits with new TP target (45 bps).
  - TP/SL re-calibrated: take_profit 0.003 → 0.0045, stop_loss 0.004 → 0.0028 (EXP-20260311-02); net RR improved from 0.59 to 1.28; break-even win rate drops from 63% to 44%.
  - Fee-adjusted reversion gate added in code: entries blocked when |bb_basis − mid| / mid < 16 bps.
  - Ledger entries: EXP-20260311-02, EXP-20260311-03.
- **Remaining**: restart bot7, run 48h observation window, audit fills.csv for ≥ 10 thesis fills and avg pnl/fill > 0 net of fees.

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
  1. Initial static app lived under `apps/realtime_ui` (removed); current UI is `apps/realtime_ui_v2` (React/Vite).
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
  1. Extend `infra/monitoring/OBSERVABILITY_CONTRACT.md` with depth streams + evidence mapping.
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
  - `hbot/infra/monitoring/promtail/promtail-config.yml` ingests `epp_v24` CSV artifacts into Loki.
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

### PERF Audit Cycle 2 — 2026-03-12 Baseline

> Goal: address the remaining hot-path I/O, CPU waste, and frontend render bottlenecks
> identified by the `INITIAL_AUDIT` run on 2026-03-12, after the 20260309 cycle items were
> all closed. Focus on fill-path sync I/O, bounded percentile computation, Redis timeout
> tail risk, and frontend render efficiency.

#### Performance Target State (Cycle 2)
- **Fill-path I/O**: sync disk writes on the fill hot path are batched or deferred so fill-handling p95 stays under 5 ms.
- **CPU efficiency**: per-tick CPU waste from sorting and redundant validation is eliminated; `_auto_calibration_p95` uses O(n) percentile.
- **Redis tail risk**: worst-case tick stall from Redis I/O is bounded at 500 ms, not 2 s.
- **Frontend render**: panel re-renders only occur when subscribed data changes; WebSocket buffer is capped; high-frequency events skip Zod validation.
- **Disk hygiene**: Prometheus, Loki, and TimescaleDB volumes have explicit bounded retention; `desk._event_log` is capped.

#### 2-Week Execution Order
- **L-effort anchor**: `P1-PERF-20260312-1` — buffer sync disk writes on the fill path because 3 sync writes per fill is the clearest latency tail risk on the trading-critical path.
- **M-effort items**:
  - `P1-PERF-20260312-2` — replace `_auto_calibration_p95()` sort with bounded percentile.
  - `P1-PERF-20260312-3` — reduce `drive_desk_tick` Redis I/O timeout from 2 s to 500 ms.
  - `P2-PERF-20260312-4` — add `React.memo` to dashboard panels and cap WebSocket buffer.
- **Quick wins**:
  - `P2-PERF-20260312-5` — skip Zod validation for high-frequency WS events.
  - `P2-PERF-20260312-6` — bound `desk._event_log` and document volume retention.

### [P1-PERF-20260312-1] Buffer sync disk writes on fill path `closed`

**Why it matters**: Each fill triggers 3 synchronous disk writes (EventJournal flush, fill WAL flush, DailyStateStore forced fsync) in the trading-critical tick path. Under burst fills, cumulative sync I/O can stall the tick loop beyond the 100 ms alert threshold.

**What exists now**:
- `hbot/controllers/paper_engine_v2/state_store.py` — `EventJournal.append()` calls `flush()` after every write
- `hbot/controllers/epp_logging.py` — fill WAL does sync append + flush per fill
- `hbot/controllers/daily_state_store.py` — forced saves run `os.fsync()` synchronously on fill

**Design decision (pre-answered)**: Batch EventJournal writes with a 100 ms flush timer. Keep fill WAL sync (durability non-negotiable). Convert DailyStateStore forced saves to background thread with join-on-shutdown guarantee.

**Implementation steps**:
1. Add a `_flush_timer` to `EventJournal` that flushes every 100 ms instead of per-write. Use a daemon thread or `threading.Timer`.
2. In `DailyStateStore.save(force=True)`, submit to the existing `_bg_thread` pattern but join immediately only on shutdown/clear, not on every forced save.
3. Add a `_fill_io_latency_ms` metric to `_LATENCY_TRACKER` in `drive_desk_tick` to measure fill I/O cost.
4. Verify journal replay still works with buffered writes (existing test coverage).

**Acceptance criteria**:
- Fill-handling latency p95 drops by ≥30 % under burst (10 fills in 60 s)
- No data loss: journal entries and WAL entries survive process crash within 100 ms window
- `TickDurationHigh` alert does not fire during fill bursts

**Do not**:
- Remove fill WAL sync guarantee
- Remove DailyStateStore's crash-recovery guarantee (must still have durable state on clean shutdown)

### [P1-PERF-20260312-2] Replace `_auto_calibration_p95()` with bounded percentile `closed`

**Why it matters**: `sorted()` on a 20k-element list runs O(n log n) per tick when any soft-pause check is active. At ~1 Hz tick rate, this is ~290k comparisons/second of avoidable CPU work.

**What exists now**:
- `hbot/controllers/risk_mixin.py:38-43` — `_auto_calibration_p95()` does `sorted(values)` where `values` is a deque up to 20k elements

**Design decision (pre-answered)**: Use `heapq.nsmallest` which is O(n) with a smaller constant, or maintain a running approximate percentile.

**Implementation steps**:
1. Replace `sorted(values)` with `heapq.nsmallest(max(1, len(values) - int(len(values) * 0.95)), values)[-1]` or equivalent O(n) approach.
2. Add a micro-benchmark in `hbot/tests/controllers/` confirming the new approach matches `sorted()` output for representative data.
3. Verify soft-pause behavior is unchanged with existing test suite.

**Acceptance criteria**:
- `_auto_calibration_p95()` call time < 0.1 ms at 20k elements (vs current ~2-5 ms)
- Soft-pause thresholds produce identical results for known test vectors

**Do not**:
- Change the semantics of what p95 means (must be exact or ≤1 % error)
- Remove the soft-pause safety check

### [P1-PERF-20260312-3] Reduce `drive_desk_tick` Redis I/O timeout from 2 s to 500 ms `closed`

**Why it matters**: The thread pool `fut.result(timeout=2.0)` in `drive_desk_tick` can block the entire tick path for up to 2 seconds if any Redis consumer hangs. A 2 s stall is 20x the 100 ms tick budget.

**What exists now**:
- `hbot/controllers/paper_engine_v2/hb_bridge.py:2582` — `fut.result(timeout=2.0)` for each of 4 parallel Redis I/O futures

**Design decision (pre-answered)**: Reduce timeout to 500 ms. Add a counter metric for timeout events.

**Implementation steps**:
1. Change `timeout=2.0` to `timeout=0.5` in `drive_desk_tick`.
2. Add `_LATENCY_TRACKER.observe("bridge_redis_timeout_count", 1)` when a `TimeoutError` is caught.
3. Observe in paper environment for 24 h; confirm no increase in `bridge_parallel_io_ms` p95 or timeout count.

**Acceptance criteria**:
- Worst-case tick stall from Redis I/O drops from 2 s to 0.5 s
- No increase in Redis timeout count under normal load (timeout count should be 0)

**Do not**:
- Remove the timeout entirely (must not block forever)
- Remove any of the 4 parallel Redis consumers

### [P2-PERF-20260312-4] Add `React.memo` to dashboard panels and cap WebSocket buffer `closed`

**Why it matters**: Every store update re-renders all mounted panels because none use `React.memo`. The WebSocket `pendingMessages` array has no cap, creating a burst memory risk.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/components/` — MarketChartPanel, FillsPanel, OrdersPanel, DepthLadderPanel, EventFeedPanel, PayloadInspectorPanel, InstancesPreviewStrip — none wrapped in `React.memo`
- `hbot/apps/realtime_ui_v2/src/hooks/useRealtimeTransport.ts` — `pendingMessages` array with no cap

**Design decision (pre-answered)**: Wrap each panel export in `React.memo`. Cap `pendingMessages` at 500, dropping oldest non-snapshot messages on overflow.

**Implementation steps**:
1. Wrap each panel component's default export in `React.memo()`.
2. In `useRealtimeTransport.ts`, add a `MAX_PENDING = 500` constant. In `enqueueMessage()`, if `pendingMessages.length >= MAX_PENDING`, drop the oldest non-snapshot message before pushing.
3. Run existing Vitest suite to confirm no regressions.

**Acceptance criteria**:
- No panel renders when its subscribed store slices are unchanged (verifiable via React DevTools)
- `pendingMessages` never exceeds 500 entries during burst reconnect

**Do not**:
- Drop snapshot messages (they carry full state)
- Change store selector logic

### [P2-PERF-20260312-5] Skip Zod validation for high-frequency WS events `closed`

**Why it matters**: Zod `safeParse` runs on every incoming WebSocket message (~8-10/sec under normal load). For stable, high-frequency schemas like `market_quote` and `market_depth_snapshot`, this is avoidable CPU cost.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/utils/realtimeParsers.ts` — `parseWsInboundMessage()` runs Zod on every message
- `hbot/apps/realtime_ui_v2/src/hooks/useRealtimeTransport.ts` — calls parser in `onmessage`

**Design decision (pre-answered)**: Type-assert (not validate) `market_quote` and `market_depth_snapshot` after `JSON.parse`. Keep Zod for snapshots, control messages, and REST responses.

**Implementation steps**:
1. In `realtimeParsers.ts`, add a fast-path: if `parsed.type === "market_quote" || parsed.type === "market_depth_snapshot"`, return the typed object without Zod parse.
2. Keep Zod parse for all other message types.
3. Add a test verifying the fast-path returns the same shape as Zod parse for sample payloads.

**Acceptance criteria**:
- WS message processing time for `market_quote` drops measurably (DevTools Performance tab)
- No runtime type errors from skipped validation (covered by existing snapshot/event tests)

**Do not**:
- Remove Zod validation for snapshot or control messages
- Remove the throttle on `market_quote` (200 ms) or depth (333 ms)

### [P2-PERF-20260312-6] Bound `desk._event_log` and document volume retention `closed`

**Why it matters**: `desk._event_log` has no explicit cap and grows if `drain_events()` stalls. Prometheus, Loki, and TimescaleDB volumes have no documented retention limits, creating unbounded disk growth risk.

**What exists now**:
- `hbot/controllers/paper_engine_v2/desk.py` — `_event_log.extend(all_events)` with no maxlen
- `hbot/infra/compose/docker-compose.yml` — Prometheus, Loki, TimescaleDB volumes with no retention config

**Design decision (pre-answered)**: Convert `_event_log` to `collections.deque(maxlen=10000)`. Add Prometheus `--storage.tsdb.retention.time=30d`, Loki retention period, and TimescaleDB `drop_chunks` policy.

**Implementation steps**:
1. In `desk.py`, change `_event_log: list` to `collections.deque(maxlen=10000)`.
2. In `docker-compose.yml`, add `--storage.tsdb.retention.time=30d` to Prometheus command.
3. Add Loki `retention_period: 720h` (30d) to Loki config.
4. Add a TimescaleDB retention policy via init SQL or ops script.
5. Document expected disk usage per volume in `hbot/docs/architecture/system_architecture.md`.

**Acceptance criteria**:
- `desk._event_log` never exceeds 10k entries
- Prometheus, Loki, TimescaleDB volumes are bounded by explicit retention policies
- Disk growth rate documented

**Do not**:
- Remove event logging (needed for postmortem)
- Set retention too aggressively (< 14 days for any volume)

---

## OPS — Initial Audit (2026-03-12)

> Goal: establish the complete ops baseline — observability, alerting, runbook coverage,
> infrastructure hygiene, recovery readiness, and security posture — so the weekly ops loop
> has a scored starting point and a prioritized gap list.

### Ops Maturity Scorecard

| Dimension | Score | Evidence | Top gap |
|---|---|---|---|
| Metrics coverage | 8/10 | 80+ metrics across bot-metrics-exporter and control-plane-metrics-exporter. Core trading KPIs, paper engine, Redis client health all scraped at 15s. Recording rules for mid, exposure, skew. | `hbot_bot_kill_switch_count` not exported — `KillSwitchTriggered` alert is dead |
| Alert coverage | 7/10 | 45+ alerts across 7 groups. Thresholds mostly calibrated. Critical/warning severity routing to Telegram via webhook sink. Inhibition rules present. | Dead `KillSwitchTriggered` alert; no exchange API latency alert; no order placement failure alert; no reconciliation drift alert |
| Dashboard coverage | 8/10 | 5 Grafana dashboards: trading overview, control plane, FTUI bot monitor, paper engine supervision, bot deep dive. All useful. | 2 panels broken (postgres-ops datasource commented out); no kill switch status panel; no open orders panel |
| Service health | 8/10 | 38+ services with restart policies, CPU/mem limits, health checks. Most health checks are meaningful (Redis ping, HTTP health, file freshness). autoheal restarts unhealthy containers. | 4 services without health checks (telegram-bot, desk-snapshot-service, bot-watchdog, promtail); signal/risk service health checks are Redis ping only (placeholder) |
| Logging & searchability | 5/10 | Promtail scrapes bot logs → Loki (7d retention). `configure_logging()` provides consistent format. Grafana log panels exist. | Plain text only (no JSON structured logs); no service logs in Loki (only bot logs); no correlation IDs (bot_id/order_id/fill_id) in log format; event_store/reconciliation_service skip `configure_logging()` |
| Infrastructure hygiene | 7/10 | Resource limits on all critical services. Docker log rotation (50m/5). Artifact retention policy with 20 rules. All ports bound to 127.0.0.1. | Redis unauthenticated; no `start_period` on Redis/Postgres health checks; desk-snapshot/bot-watchdog missing log rotation; Prometheus has no explicit retention; some report paths missing from retention policy |
| Runbook coverage | 7/10 | 6 incident playbooks (bot stopped, kill switch, Redis down, unexpected position, exchange API, daily loss). Go-live checklist with 24 items. Recovery scripts for event-store, bus, Postgres. | No playbook for: total power loss, host reboot, Grafana wipe, bot container OOM, network partition, disk full, misconfiguration deployment |
| Recovery readiness | 5/10 | Event-store recovery script. Bus recovery check. Postgres backup/restore scripts exist. Day2 baseline reanchor documented. Runbooks.md covers startup, shutdown, degraded mode, rollback. | No disaster recovery plan. No Redis backup drill. No documented full restart sequence. No Grafana backup/restore. No OOM recovery procedure. Postgres backup drill listed but not verified. |
| Security posture | 4/10 | All ports on 127.0.0.1. Grafana auth enabled. Monitoring/trading network separation. | Redis no password. MQTT `allow_anonymous`. realtime-ui-api auth disabled. No TLS anywhere. Weak defaults for OPS_DB, Grafana admin, pgadmin. Docker socket mounted on autoheal + bot-watchdog. |
| Process maturity | 6/10 | Strict promotion cycle. Soak monitor. Daily ops reporter. Artifact retention running. Telegram alerts configured. | No scheduled promotion gate runs (strict_cycle_latest.json missing). Telegram untested status unknown. No OOM/disk-full automated remediation. No post-incident template enforcement. |

### Top 20 Gaps (Prioritized by Impact)

| # | Gap | Dimension | Impact | Effort |
|---|---|---|---|---|
| 1 | `KillSwitchTriggered` alert dead — metric not exported | Metrics/Alerts | **Critical**: kill switch fires silently with no alert | S |
| 2 | No Redis authentication | Security | **High**: any process on host can read/write all trading streams | S |
| 3 | No disaster recovery plan / full restart sequence documented | Recovery | **High**: total power loss leaves operator guessing | M |
| 4 | No structured (JSON) logging | Logging | **High**: log search/parsing unreliable; no correlation | L |
| 5 | Service logs not in Loki (only bot logs) | Logging | **High**: kill-switch, event-store, reconciliation errors invisible in Grafana | M |
| 6 | realtime-ui-api auth disabled by default | Security | **Medium**: dashboard API exposed without auth on localhost | S |
| 7 | No exchange API latency/failure alert | Alerts | **Medium**: slow or failing exchange calls go undetected | S |
| 8 | Broken Postgres-backed dashboard panels | Dashboards | **Medium**: `Last 100 Fills` and `Equity History` show "No data" | S |
| 9 | 4 services without health checks (telegram-bot, desk-snapshot, bot-watchdog, promtail) | Services | **Medium**: these services can fail silently; autoheal cannot restart them | S |
| 10 | signal-service/risk-service health checks are placeholder (Redis ping only) | Services | **Medium**: service-level failures not detected | M |
| 11 | No `start_period` on Redis/Postgres health checks | Infra | **Medium**: restart loops during slow AOF/DB load | S |
| 12 | Prometheus retention not configured (default 15d) | Infra | **Medium**: either too short for trend analysis or unbounded disk growth | S |
| 13 | Missing incident playbooks (power loss, OOM, disk full, network partition, Grafana wipe, misconfig) | Runbooks | **Medium**: no documented response for 6+ realistic failure modes | M |
| 14 | desk-snapshot-service/bot-watchdog missing Docker log rotation | Infra | **Low**: unbounded log growth on these containers | S |
| 15 | No reconciliation drift alert (beyond report presence) | Alerts | **Medium**: recon failure detected only by operator checking report | S |
| 16 | Artifact retention missing some report paths (exchange_snapshots, market_data, coordination, desk_snapshot) | Infra | **Low**: these directories grow unbounded | S |
| 17 | MQTT `allow_anonymous true` | Security | **Low**: MQTT unauthenticated (low risk if localhost-only) | S |
| 18 | No Redis RDB snapshots | Infra | **Low**: AOF-only; no periodic point-in-time snapshot | S |
| 19 | Promtail path mismatch with host logrotate | Logging | **Low**: Promtail scrapes `/workspace/hbot/data/`, host logrotate targets `/opt/hbot/data/` | S |
| 20 | `strict_cycle_latest.json` missing — soak/dashboard panels report false-negative | Process | **Medium**: no scheduled promotion gate run; gate panels show stale/no data | M |

### 2-Week Execution Order

- **L-effort anchor**: none in this cycle (structured logging is L but deferred to a dedicated cycle)
- **M-effort items**:
  - `P1-OPS-20260312-3` — document disaster recovery plan and full restart sequence
  - `P1-OPS-20260312-5` — add service logs to Loki via Promtail
  - `P2-OPS-20260312-8` — add 6 missing incident playbooks
- **Quick wins (S-effort)**:
  - `P1-OPS-20260312-1` — export kill switch metric and fix dead alert
  - `P1-OPS-20260312-2` — add Redis authentication
  - `P1-OPS-20260312-4` — add exchange API latency/failure alert
  - `P2-OPS-20260312-6` — fix broken Postgres dashboard panels
  - `P2-OPS-20260312-7` — add health checks to 4 services
  - `P2-OPS-20260312-9` — add `start_period` to Redis/Postgres health checks
  - `P2-OPS-20260312-10` — set Prometheus retention and add missing artifact retention rules

### [P1-OPS-20260312-1] Export kill switch metric and fix dead `KillSwitchTriggered` alert `closed`

**Why it matters**: The `KillSwitchTriggered` alert references `hbot_bot_kill_switch_count` which is never exported. If the kill switch fires, no Telegram alert is sent — the most critical safety event goes undetected by monitoring.

**What exists now**:
- `hbot/infra/monitoring/prometheus/alert_rules.yml` — `KillSwitchTriggered` alert with `for: 0m`
- `hbot/services/bot_metrics_exporter.py` — does not export `hbot_bot_kill_switch_count`
- `hbot/services/kill_switch/main.py` — writes `reports/kill_switch/latest.json` on activation

**Design decision (pre-answered)**: Add the metric to the control-plane-metrics-exporter by reading `reports/kill_switch/latest.json` for activation count. Alternatively, add a counter in the kill-switch service itself that the exporter scrapes.

**Implementation steps**:
1. In `hbot/services/control_plane_metrics_exporter.py`, add a gauge `hbot_bot_kill_switch_count` that reads `reports/kill_switch/latest.json` and exposes activation count.
2. Verify the alert expression in `alert_rules.yml` matches the new metric name and labels.
3. Test by simulating a kill switch activation in paper mode.

**Acceptance criteria**:
- `hbot_bot_kill_switch_count` appears on `/metrics` endpoint
- `KillSwitchTriggered` alert fires when kill switch activates (verified in paper)
- Telegram receives the alert

**Do not**:
- Change kill switch safety logic
- Remove the `for: 0m` (kill switch must alert immediately)

### [P1-OPS-20260312-2] Add Redis authentication `closed`

**Why it matters**: Redis holds all event bus traffic (signals, risk decisions, execution intents, fills, telemetry) and is accessible without authentication. Any process on the host can read or write trading streams.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — Redis started with `--requirepass ""` (no password)
- `hbot/infra/env/.env.template` — `REDIS_PASSWORD=` (empty default)
- All service Redis clients use `redis://redis:6379/0` without auth

**Design decision (pre-answered)**: Set `REDIS_PASSWORD` in `.env`, update Redis command to `--requirepass ${REDIS_PASSWORD}`, update all service Redis URLs to include password.

**Implementation steps**:
1. Set a non-empty default in `.env.template`: `REDIS_PASSWORD=kzay_redis_paper_2026`.
2. Update Redis command in compose: `--requirepass ${REDIS_PASSWORD}`.
3. Update `REDIS_URL` in `.env.template` to `redis://:${REDIS_PASSWORD}@redis:6379/0`.
4. Verify all services connect successfully after the change.

**Acceptance criteria**:
- `redis-cli` without password is rejected
- All services connect and pass health checks
- No Redis-related alerts fire after deployment

**Do not**:
- Use the same password for production (document password rotation procedure)
- Break any service that hardcodes `redis://redis:6379/0`

### [P1-OPS-20260312-3] Document disaster recovery plan and full restart sequence `closed`

**Why it matters**: No documented procedure exists for total power loss, host reboot, or complete stack restart. An operator discovering the system down must reconstruct the startup sequence from compose file and runbooks.

**What exists now**:
- `hbot/docs/ops/runbooks.md` — covers startup, shutdown, degraded mode, bus recovery
- `hbot/scripts/release/recover_event_store_stack_and_strict_cycle.py` — partial recovery
- No document covers: full power loss recovery, data integrity verification after unclean shutdown, Grafana/Prometheus data recovery

**Design decision (pre-answered)**: Create `hbot/docs/ops/incident_playbooks/07_disaster_recovery.md` covering total power loss, host reboot, and complete stack restart with verification steps.

**Implementation steps**:
1. Write `07_disaster_recovery.md` with: pre-start checklist (disk, volumes, network), startup order (redis → postgres → services → bots → monitoring), post-start verification (health checks, Redis streams, report freshness), data integrity checks.
2. Include rollback steps for each phase.
3. Add RPO/RTO estimates for each data store.

**Acceptance criteria**:
- Playbook covers total power loss, host reboot, and volume loss scenarios
- Startup sequence is tested end-to-end at least once
- RPO/RTO documented for Redis, Postgres, bot state

**Do not**:
- Remove existing runbook content (extend, don't replace)

### [P1-OPS-20260312-4] Add exchange API latency and order failure alert `closed`

**Why it matters**: No alert exists for slow or failing exchange API calls. Slow exchange responses degrade tick latency and can cause stale order book data without triggering existing alerts until the situation is severe.

**What exists now**:
- `hbot/infra/monitoring/prometheus/alert_rules.yml` — `ConnectorIOSlow` alert exists (>50ms) but no order placement failure alert
- `hbot/services/bot_metrics_exporter.py` — exports `hbot_bot_tick_connector_io_seconds`
- No metric for order placement failures or exchange API errors

**Design decision (pre-answered)**: Add an alert for sustained connector I/O slowness and add a new metric for exchange order failures if not already tracked.

**Implementation steps**:
1. Add alert `ExchangeOrderFailureSpike`: `increase(hbot_bot_order_failures_total[15m]) > 3` with `severity: critical`, `for: 5m`.
2. If `hbot_bot_order_failures_total` doesn't exist, add it to the bot-metrics-exporter by parsing error log lines or desk snapshot fields.
3. Test the alert threshold against paper exchange reject rates.

**Acceptance criteria**:
- Alert fires when order failures exceed threshold
- Telegram receives the alert
- No false positives under normal paper operation

**Do not**:
- Set threshold so low that normal paper exchange rejects cause noise

### [P1-OPS-20260312-5] Add service logs to Loki via Promtail `closed-na` (Loki/Promtail removed from stack)

**Why it matters**: Only bot logs are ingested by Promtail. Kill-switch, event-store, reconciliation, and other service errors are invisible in Grafana, making incident diagnosis slow.

**What exists now**:
- `hbot/infra/monitoring/promtail/promtail-config.yml` — scrapes `data/bot*/logs/*.log` only
- Service logs go to Docker `json-file` driver (not Loki)
- Grafana log panels query `{job="bot_logs"}` only

**Design decision (pre-answered)**: Add Docker log scraping to Promtail config for critical services (kill-switch, event-store, reconciliation, paper-exchange, market-data, realtime-ui-api). Use Docker log driver labels.

**Implementation steps**:
1. Add Docker log scraping section to `promtail-config.yml` using the Docker socket or Docker log files in `/var/lib/docker/containers/`.
2. Add labels: `job: service_logs`, `service: <service-name>`.
3. Add a Grafana log panel for service logs on the control plane dashboard.
4. Verify kill-switch and event-store errors appear in Grafana.

**Acceptance criteria**:
- Service logs queryable in Grafana with `{job="service_logs", service="kill-switch"}`
- At least kill-switch, event-store, reconciliation services ingested
- No increase in Loki disk usage beyond 2x current (monitor for 7 days)

**Do not**:
- Ingest all 38+ container logs (start with 6 critical services)
- Remove existing bot log scraping

### [P2-OPS-20260312-6] Fix broken Postgres-backed dashboard panels `closed-na` (Grafana dashboards removed from stack)

**Why it matters**: The `Last 100 Fills` and `Equity History` panels on the control-plane dashboard use the `postgres-ops` datasource, which is commented out in provisioning. Operators see "No data" for these panels.

**What exists now**:
- `hbot/infra/monitoring/grafana/provisioning/datasources/datasource.yml` — `postgres-ops` section commented out (lines 26–39)
- `hbot/infra/monitoring/grafana/dashboards/control_plane_health.json` — 2 panels reference `postgres-ops`

**Design decision (pre-answered)**: Uncomment the postgres-ops datasource and wire it to the existing ops-db-writer Postgres instance.

**Implementation steps**:
1. Uncomment the `postgres-ops` datasource block in `datasource.yml`.
2. Ensure env vars `OPS_DB_HOST`, `OPS_DB_PORT`, `OPS_DB_USER`, `OPS_DB_PASSWORD`, `OPS_DB_NAME` are set in `.env.template`.
3. Restart Grafana and verify both panels show data.

**Acceptance criteria**:
- `Last 100 Fills` panel shows recent fill data
- `Equity History` panel shows equity time series
- No Grafana provisioning errors on startup

**Do not**:
- Expose Postgres externally (keep 127.0.0.1 binding)

### [P2-OPS-20260312-7] Add health checks to telegram-bot, desk-snapshot-service, bot-watchdog, promtail `closed`

**Why it matters**: These 4 services have no health checks. If they crash or hang, autoheal cannot detect or restart them, and no alert fires.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — these 4 services have no `healthcheck` block
- autoheal only restarts containers marked `unhealthy`

**Design decision (pre-answered)**: Add lightweight health checks: telegram-bot (heartbeat file), desk-snapshot-service (report freshness), bot-watchdog (report freshness), promtail (HTTP `/ready`).

**Implementation steps**:
1. telegram-bot: `test: ["CMD-SHELL", "test -f /tmp/telegram_heartbeat && find /tmp/telegram_heartbeat -mmin -5 | grep -q ."]` — write heartbeat in main loop.
2. desk-snapshot-service: `test: ["CMD-SHELL", "python -c \"...\""]` — check report age < 120s.
3. bot-watchdog: `test: ["CMD-SHELL", "python -c \"...\""]` — check watchdog report age < 120s.
4. promtail: `test: ["CMD-SHELL", "wget -qO- http://localhost:9080/ready || exit 1"]`.

**Acceptance criteria**:
- All 4 services show `healthy` in `docker ps`
- autoheal restarts them if they become `unhealthy`

**Do not**:
- Add heavy health checks that consume resources

### [P2-OPS-20260312-8] Add missing incident playbooks (power loss, OOM, disk full, network partition, Grafana wipe, misconfig) `closed`

**Why it matters**: 6 realistic failure modes have no documented response procedure. An operator encountering any of these must improvise, increasing time-to-recovery.

**What exists now**:
- `hbot/docs/ops/incident_playbooks/` — 6 playbooks (01–06)
- No coverage for: total power loss/host reboot, bot container OOM, disk full/ENOSPC, network partition, Grafana data loss, misconfiguration deployment

**Design decision (pre-answered)**: Write 4 new playbooks (combine related scenarios).

**Implementation steps**:
1. `07_disaster_recovery.md` — total power loss, host reboot (shared with P1-OPS-20260312-3)
2. `08_resource_exhaustion.md` — OOM kill, disk full, ENOSPC
3. `09_network_partition.md` — network partition, DNS failure, exchange unreachable
4. `10_misconfiguration_rollback.md` — bad config deployment, Grafana wipe/restore

**Acceptance criteria**:
- Each playbook includes: detection, diagnosis, mitigation steps, post-incident checklist
- All 10 playbook scenarios are referenced in a master incident response index

**Do not**:
- Duplicate content from existing playbooks (reference them instead)

### [P2-OPS-20260312-9] Add `start_period` to Redis and Postgres health checks; add logging to desk-snapshot/bot-watchdog `closed`

**Why it matters**: Redis and Postgres health checks can fail during AOF/DB load, causing unnecessary restart loops. desk-snapshot-service and bot-watchdog lack Docker log rotation, risking unbounded log growth.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — Redis/Postgres health checks have no `start_period`
- desk-snapshot-service and bot-watchdog use default Docker logging (no rotation)

**Design decision (pre-answered)**: Add `start_period: 30s` to Redis and Postgres. Add `logging: *default-logging` to desk-snapshot-service and bot-watchdog.

**Implementation steps**:
1. Add `start_period: 30s` to Redis healthcheck block.
2. Add `start_period: 30s` to Postgres healthcheck block.
3. Add `logging: *default-logging` to desk-snapshot-service.
4. Add `logging: *default-logging` to bot-watchdog.

**Acceptance criteria**:
- Redis and Postgres do not restart-loop during cold start
- desk-snapshot-service and bot-watchdog logs are rotated (50m/5)

**Do not**:
- Change health check commands or intervals

### [P2-OPS-20260312-10] Set Prometheus retention and add missing artifact retention rules `closed`

**Why it matters**: Prometheus uses default retention (15d), which may be too short for trend analysis or too long for disk capacity. Several report directories (`exchange_snapshots`, `market_data_service`, `coordination`, `desk_snapshot`) have no retention rules.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — Prometheus command has no `--storage.tsdb.retention.time`
- `hbot/config/artifact_retention_policy.json` — 20 rules; 4+ report paths missing

**Design decision (pre-answered)**: Set Prometheus retention to 30d. Add retention rules for missing report paths at 30d.

**Implementation steps**:
1. Add `--storage.tsdb.retention.time=30d` to Prometheus command in compose.
2. Add rules to `artifact_retention_policy.json`:
   - `reports/exchange_snapshots/*` — 30 days
   - `reports/market_data_service/*` — 14 days
   - `reports/coordination/*` — 30 days
   - `reports/desk_snapshot/**/*` — 14 days (excluding `latest.json`)
3. Add `latest.json` files for new paths to `protect_latest` list.

**Acceptance criteria**:
- Prometheus volume stays under 5 GB at 30d retention
- All report directories are covered by retention rules
- `artifact-retention` service cleans up old files on next run

**Do not**:
- Set retention below 14 days for any path
- Delete `latest.json` files

---

### Assumptions and Data Gaps

| Item | Type | Impact |
|---|---|---|
| No live metrics available (system not running during audit) | DATA_GAP | All scores based on code/config analysis, not runtime observation |
| Telegram alerting not tested during audit | DATA_GAP | Alert delivery unverified; `TELEGRAM_BOT_TOKEN` may be empty |
| Container restart count and OOM history unknown | DATA_GAP | Service health score could be lower |
| Disk usage per volume unknown | DATA_GAP | Infrastructure score based on config, not measured usage |
| `strict_cycle_latest.json` may have been generated and removed by retention | ASSUMPTION | Scored as missing; may exist intermittently |
| Promtail deployment path matches compose config | ASSUMPTION | `../data/botN/logs/` vs `/opt/hbot/data/` mismatch unverified |
| Redis memory usage is within the 1.5 GB cap | ASSUMPTION | Stream maxlens should prevent overflow under normal load |
| All health checks pass under normal operation | ASSUMPTION | Cold-start issues with Redis/Postgres unverified |

### Metrics to Track in Weekly Loop

| Metric | Source | Target |
|---|---|---|
| Alert true-positive rate | Alertmanager / Telegram | > 90% (no false positive noise) |
| Service restart count / week | cAdvisor | 0 (excluding planned restarts) |
| Report staleness (max age by service) | control-plane-metrics-exporter | < 2x configured interval |
| Disk usage per volume | `du -sh` / node-exporter | Documented + bounded |
| Redis memory usage | `INFO memory` | < 1 GB of 1.5 GB cap |
| Loki ingest rate / retention | Loki /metrics | Stable at 7d retention |
| Telegram test alert (weekly) | Manual | Confirmed received each week |
| Incident count / MTTR | Manual log | Trending down |

---

## FRONT — Initial Audit (2026-03-12)

> Goal: establish the frontend baseline — UX correctness, runtime reliability, performance,
> code health, accessibility, dependency hygiene, and test coverage — so the weekly frontend
> loop has a scored starting point and a prioritized gap list.

### Frontend Health Scorecard

| Dimension | Score | Evidence | Top risk |
|---|---|---|---|
| UX clarity | 7/10 | 6 views reachable via TopBar dropdown + keyboard shortcuts (1–6). Connection/health pills visible. AlertsStrip with severity styling. InstancesPreviewStrip shows instance cards. | Degraded/fallback mode not surfaced in TopBar; several panels lack loading/empty/error states; view switching unmounts Realtime and drops live state |
| Runtime reliability | 7/10 | WS reconnect with exponential backoff (1.5s→10s cap). Session ID filters stale messages. Stale REST rejected vs WS freshness. Fill/order deduplication sound. `ViewErrorBoundary` catches render errors. | `pendingMessages` unbounded under burst; no global unhandled rejection handler; no fetch timeout wrapper; useReviewData has no retry; reconnect does not clear state (possible divergence) |
| Performance | 7/10 | Lazy loading for 5 views. Vendor chunks split (lightweight-charts, @tanstack/react-table). `useShallow` selectors on heavy panels. Market quote throttled at 200ms, depth at 333ms. Candle update debounced at 250ms. | No `React.memo` on panels; Zod parse on every WS message; `ingestEventMessage` (250 lines) runs on every event and updates many store slices; `normalizeFill` runs over full array each update |
| Code health | 6/10 | Strict TypeScript (no `any`, no `@ts-ignore`). Zod schemas for all external payloads. Clean component/hook separation. No unsafe casts in production code. | `useDashboardStore.ts` is 1,251-line god file mixing state, ingestion, normalization, formatting. `toNum` and `depthMid` duplicated between store and utils. 50+ inline magic numbers across components. No dedicated selectors layer. |
| Accessibility | 4/10 | `ShortcutHelp` has `role="dialog"`, `aria-modal`. `AlertsStrip` has `role="alert"`, `aria-live`. Focus-visible styles present. Status pills show text (not color-only). Table headers use `<th>`. | No `scope="col"` on table headers. No `htmlFor` on labels. No `prefers-reduced-motion`. No `aria-label` on connection/health indicators. No contrast audit. Focus styles use `outline: none` on `:focus`. |
| Dependency hygiene | 9/10 | All deps current (React 19, Vite 6, TS 5.9, Zustand 5, Zod 4, Vitest 4, Playwright 1.58). No known CVEs. Lean dependency tree (6 runtime, 16 dev). Lockfile present. | No `engines` or `.nvmrc` for Node version. No `.dockerignore`. No `gzip_vary` or `index.html` no-cache in nginx. |

### Product/UX Findings (Ranked by Operator Impact)

| # | Finding | Impact | Severity |
|---|---|---|---|
| 1 | **Degraded/fallback mode not visible in TopBar** — when `fallbackActive` is true or WS is disabled due to auth token, the operator must navigate to DataInPanel to discover degraded mode | Operator may not realize data is stale | P1 |
| 2 | **Several panels lack loading/empty/error states** — MarketChartPanel, EventFeedPanel, BotGateBoardPanel have no loading state; no shared error UI in Panel wrapper | Operator sees blank panels during initial load | P2 |
| 3 | **View switching unmounts Realtime** — switching to History/Service/Review unmounts the realtime view, dropping accumulated WS state (fills, events, chart); returning requires full re-hydration from snapshot | Operator loses context when checking other views | P2 |
| 4 | **Instance/pair not in TopBar** — active instance and trading pair not shown in the main header bar; only in InstancesPreviewStrip below | Less visible at a glance | P2 |
| 5 | **InstancesPreviewStrip empty state is invisible** — returns `null` when no instances found, no indication of loading/error | Operator doesn't know if data is loading or missing | P2 |
| 6 | **No persistent shortcut hint** — `?` toggles help overlay but no visible hint exists in the UI | Discoverability is low | P3 |

### Reliability Findings

| # | Finding | Impact | Severity |
|---|---|---|---|
| 1 | **`pendingMessages` unbounded** — WS message buffer has no cap; burst events can grow it indefinitely | Memory spike during reconnect burst | P1 |
| 2 | **No global unhandled rejection handler** — `window.onunhandledrejection` not set; async errors in `refreshLiveState` and other fetches can fail silently | Silent failures in transport | P2 |
| 3 | **No fetch timeout wrapper** — `fetch.ts` only exports `buildHeaders`; all fetch calls rely on ad-hoc `AbortController` or no timeout | Hanging requests block state updates | P2 |
| 4 | **useReviewData has no retry on failure** — REST fetch for daily/weekly/journal review has no automatic retry | Review panels stuck in error state until view switch | P2 |
| 5 | **Reconnect does not clear accumulated state** — after WS reconnect, existing fills/orders/events persist until new snapshot overwrites them; if server state diverged, UI can show stale data | Possible divergence after disconnect | P2 |

### Performance Findings

(Covered in detail by the PERF audit items P2-PERF-20260312-4 and P2-PERF-20260312-5; summarized here for frontend loop context.)

| # | Finding | Impact |
|---|---|---|
| 1 | No `React.memo` on panel components | Avoidable re-renders on every store update |
| 2 | Zod `safeParse` on every WS message (~8-10/sec) | Avoidable CPU for stable schemas |
| 3 | `ingestEventMessage` (250 lines) updates many store slices per event | Broad re-render trigger |
| 4 | `normalizeFill` runs over full fills array each update | O(n) on every fill event |
| 5 | `MarketChartPanel` does `JSON.stringify` for overlay signature on every render | Avoidable serialization |

### Code Health Findings

| # | Finding | File | Lines | Impact |
|---|---|---|---|---|
| 1 | **God file**: `useDashboardStore.ts` mixes state, ingestion, normalization, formatting, constants, and domain logic | `src/store/useDashboardStore.ts` | 1,251 | Hard to test, review, and modify safely |
| 2 | **Duplicate utilities**: `toNum` in both `format.ts` and store; `depthMid` in both `metrics.ts` and store | Multiple files | — | Divergence risk |
| 3 | **50+ inline magic numbers** across components: chart dimensions, thresholds, timeouts, colors, slice limits | Most components | — | Hard to tune and audit |
| 4 | **No selectors layer**: components use inline `useShallow` with object selectors; no shared selector definitions | Store consumers | — | Selector duplication across components |
| 5 | **CSS**: 859 lines in `App.css` with hardcoded colors and duplicated panel patterns | `src/App.css` | 859 | Hard to theme or refactor |

### Dependency Decisions Table

| Package | Current | Latest | Risk / Opportunity | Decision |
|---|---|---|---|---|
| react | ^19.2.0 | 19.2.x | Current | **defer** — no action needed |
| react-dom | ^19.2.0 | 19.2.x | Current | **defer** |
| zustand | ^5.0.11 | 5.x | Current | **defer** |
| zod | ^4.3.6 | 4.x | Current | **defer** |
| lightweight-charts | ^5.1.0 | 5.x | Current | **defer** |
| @tanstack/react-table | ^8.21.3 | 8.x | Current | **defer** |
| vite | ^6.4.1 | 6.x | Current | **defer** |
| typescript | ~5.9.3 | 5.9.x | Current | **defer** |
| vitest | ^4.0.18 | 4.x | Current | **defer** |
| @playwright/test | ^1.58.2 | 1.x | Current | **defer** |
| — | — | — | Add `@tanstack/react-virtual` if fills/orders tables grow beyond 500 rows | **evaluate** in next cycle |
| — | — | — | Add `rollup-plugin-visualizer` for bundle analysis | **adopt** — quick win |

### Testing Gaps and Release Blockers

**Current test coverage:**

| Scope | Coverage |
|---|---|
| Store ingestion (REST vs WS freshness, fills, orders) | Covered |
| Candle helpers | Covered |
| Format/metrics/parsers utilities | Covered |
| TopBar, InstancesPreviewStrip | Covered (RTL) |
| Playwright smoke test | Exists |

**Gaps:**

| # | Gap | Risk |
|---|---|---|
| 1 | **No test for `useRealtimeTransport`** — reconnect, session filtering, message buffering untested | Transport regressions go undetected |
| 2 | **No tests for 10+ panel components** — MarketChartPanel, FillsPanel, OrdersPanel, AccountPnlPanel, DepthLadderPanel, EventFeedPanel, DataInPanel, PayloadInspectorPanel, PositionExposurePanel, BotGateBoardPanel, AlertsStrip, ServiceMonitorPanel | Panel regressions undetected |
| 3 | **No partial/malformed payload tests** — panels not tested with missing fields | Crash risk on API shape change |
| 4 | **No disconnect/reconnect journey test** — end-to-end reconnect behavior untested | Critical operator scenario |
| 5 | **No nginx/Docker deployment smoke test** — Playwright runs on `npm run preview`, not Docker | Deploy-path issues undetected |

**Release blockers:** None identified. Build passes, lint passes, no known console errors.

### Sprint Plan (1–2 Week Scope)

**L-effort (> 1 day):**

**L1. Surface degraded/fallback mode in TopBar and add shared Panel error/empty/loading states**
- Add fallback/degraded indicator to TopBar. Add `error`, `empty` props to `Panel.tsx` wrapper. Propagate to all panels.
- Rollback: Revert TopBar and Panel changes.

**M-effort (half-day to 1 day):**

**M1. Add fetch timeout wrapper and global unhandled rejection handler**
- Create `fetchWithTimeout()` in `fetch.ts`. Add `window.onunhandledrejection` in `main.tsx`. Wire into all fetch calls.
- Rollback: Revert `fetch.ts` and `main.tsx`.

**M2. Extract constants from components into a shared constants file**
- Move chart dimensions, thresholds, slice limits, timeout values to `src/constants.ts`.
- Rollback: Revert constants file and component imports.

**M3. Add `scope="col"` to table headers and `htmlFor` to labels**
- Quick accessibility pass across all components.
- Rollback: Revert attribute changes.

**Quick wins (< 2h):**

- **Q1.** Add `.nvmrc` with `20` and `engines` to `package.json`.
- **Q2.** Add `gzip_vary on` and `index.html` no-cache to `nginx.conf`.
- **Q3.** Add `prefers-reduced-motion: reduce` media query to `App.css` to disable animations.
- **Q4.** Add `aria-label` to TopBar connection/health status pills.
- **Q5.** Add shortcut hint text (e.g. `? shortcuts`) to TopBar or footer.

---

### [P1-FRONT-20260312-1] Surface degraded/fallback mode in TopBar `closed`

**Why it matters**: When `fallbackActive` is true or WS is disabled due to auth token, the operator must navigate to DataInPanel to discover degraded mode. On a live trading desk, not knowing data is stale is a safety risk.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/components/TopBar.tsx` — shows WS and API status pills but not `fallbackActive`
- `hbot/apps/realtime_ui_v2/src/components/DataInPanel.tsx` — shows fallback status but is a secondary panel

**Design decision (pre-answered)**: Add a degraded-mode banner/pill to TopBar when `health.fallbackActive === true` or when in REST-only mode. Use the existing `connection-lost-banner` pattern with a distinct "Degraded — using fallback data" message.

**Implementation steps**:
1. In `TopBar.tsx`, subscribe to `health.fallbackActive` and `connection.restOnlyMode` from the store.
2. Add a banner below the status row when either is true: `"⚠ Degraded mode — data may be delayed"`.
3. Style with `severity-warn` class for visual prominence.

**Acceptance criteria**:
- Banner visible when `fallbackActive === true`
- Banner visible when REST-only mode is active (auth token set)
- Banner disappears when full WS connection restores

**Do not**:
- Remove existing DataInPanel fallback display
- Change connection/health status pill logic

### [P1-FRONT-20260312-2] Add fetch timeout wrapper and global unhandled rejection handler `closed`

**Why it matters**: No fetch calls have a timeout. A hanging request can block state updates indefinitely. Async errors in transport hooks fail silently with no operator-visible signal.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/utils/fetch.ts` — only exports `buildHeaders()`
- `hbot/apps/realtime_ui_v2/src/main.tsx` — no `window.onunhandledrejection`
- Fetch calls use ad-hoc `AbortController` or no timeout

**Design decision (pre-answered)**: Add `fetchWithTimeout(url, options, timeoutMs)` to `fetch.ts`. Add `window.onunhandledrejection` in `main.tsx` that logs to console.error and adds an event line to the store.

**Implementation steps**:
1. In `fetch.ts`, add `fetchWithTimeout()` that wraps `fetch` with `AbortController` + `setTimeout`. Default timeout 10s.
2. In `main.tsx`, add `window.addEventListener("unhandledrejection", ...)` that calls `console.error` and `useDashboardStore.getState().addEventLine(...)`.
3. Migrate `useRealtimeTransport`, `useReviewData`, `InstancesPreviewStrip`, and `ServiceMonitorPanel` fetch calls to use `fetchWithTimeout()`.

**Acceptance criteria**:
- All fetch calls time out after configurable duration
- Unhandled promise rejections logged and visible in event feed
- Build passes, existing tests pass

**Do not**:
- Add retry logic in this item (separate concern)
- Change WebSocket timeout handling

### [P2-FRONT-20260312-3] Add shared Panel error/empty/loading states `closed`

**Why it matters**: 5+ panels lack explicit loading, empty, or error states. The operator sees blank panels during initial load or when data is missing, with no indication of whether the panel is loading or broken.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/components/Panel.tsx` — supports `loading` prop only; no `error` or `empty` props
- MarketChartPanel, EventFeedPanel, BotGateBoardPanel have no loading state

**Design decision (pre-answered)**: Extend `Panel.tsx` with `error` (ReactNode) and `empty` (ReactNode) props. When `error` is set, show error UI. When `empty` is set and no children content, show empty UI. Add these to all panels.

**Implementation steps**:
1. Add `error?: ReactNode` and `empty?: ReactNode` props to `Panel.tsx`.
2. Render error state (with retry button) when `error` is set; empty state when `empty` is set and `!loading`.
3. Wire error/empty props into MarketChartPanel, EventFeedPanel, BotGateBoardPanel, and InstancesPreviewStrip.

**Acceptance criteria**:
- All panels show meaningful loading, empty, or error state instead of blank
- Panel error state includes a retry mechanism where applicable
- Build passes, existing tests pass

**Do not**:
- Change panel data logic
- Add error boundaries inside panels (ViewErrorBoundary already handles crashes)

### [P2-FRONT-20260312-4] Extract inline magic numbers to shared constants `closed`

**Why it matters**: 50+ inline magic numbers across components (chart dimensions, thresholds, timeouts, slice limits, colors) make the dashboard hard to tune, audit, and keep consistent.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/components/MarketChartPanel.tsx` — `250` (debounce), `320`/`640`/`260`/`360` (chart dims), `12` (orders slice), `60` (fill markers)
- `hbot/apps/realtime_ui_v2/src/components/DataInPanel.tsx` — `3_000`, `60_000`, `30_000`, `10_000`, `5_000`
- `hbot/apps/realtime_ui_v2/src/components/DepthLadderPanel.tsx` — `15` (MAX_DEPTH_ROWS)
- `hbot/apps/realtime_ui_v2/src/store/useDashboardStore.ts` — `MAX_EVENT_LINES=100`, `MAX_FILLS=220`, `MAX_CANDLES=300`, etc.

**Design decision (pre-answered)**: Create `src/constants.ts` with named exports for all numeric constants. Import in components and store.

**Implementation steps**:
1. Create `src/constants.ts` with all extracted constants (chart dimensions, timeouts, thresholds, limits, debounce delays).
2. Replace inline numbers in components and store with named imports.
3. Verify build passes and no behavioral changes.

**Acceptance criteria**:
- No inline numeric literals for thresholds, limits, or timing in components (except trivial ones like `0`, `1`, `100` for percentages)
- All constants have descriptive names
- Build passes, existing tests pass

**Do not**:
- Change any constant values (extract only)
- Move CSS-related numbers to constants (keep in CSS)

### [P2-FRONT-20260312-5] Accessibility pass: table scope, label association, reduced motion `closed`

**Why it matters**: Table headers lack `scope="col"`, labels lack `htmlFor`, and no `prefers-reduced-motion` media query exists. These are basic accessibility requirements for any production web app.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/components/` — `<th>` without `scope`; `<label>` without `htmlFor`
- `hbot/apps/realtime_ui_v2/src/App.css` — 6 animations with no reduced-motion override
- `hbot/apps/realtime_ui_v2/src/components/TopBar.tsx` — connection/health pills without `aria-label`

**Design decision (pre-answered)**: Add `scope="col"` to all `<th>`. Add `htmlFor` and `id` to all label/input pairs. Add `prefers-reduced-motion` media query. Add `aria-label` to status indicators.

**Implementation steps**:
1. Add `scope="col"` to every `<th>` in tables across all components.
2. Add `htmlFor`/`id` pairs to all label/input associations in TopBar, FillsPanel, OrdersPanel, MarketChartPanel, DailyReviewPanel, JournalReviewPanel.
3. Add `@media (prefers-reduced-motion: reduce)` to `App.css` that sets `animation: none !important; transition: none !important;` on `*`.
4. Add `aria-label` to TopBar WS/API status pills.

**Acceptance criteria**:
- All table headers have `scope="col"`
- All form labels are associated with their inputs via `htmlFor`/`id`
- Animations disabled when user prefers reduced motion
- Status indicators have screen-reader-accessible labels

**Do not**:
- Change visual design or layout
- Add full WCAG 2.1 AA compliance (that is a separate project)

### [P2-FRONT-20260312-6] Add `useRealtimeTransport` test coverage `closed`

**Why it matters**: The realtime transport hook handles WebSocket connect/disconnect, reconnect backoff, session filtering, message buffering, REST fallback, and throttling — all untested. Transport regressions are the highest-risk undetected failure mode.

**What exists now**:
- `hbot/apps/realtime_ui_v2/src/hooks/useRealtimeTransport.ts` — 412 lines, zero test coverage
- `hbot/apps/realtime_ui_v2/src/store/useDashboardStore.test.ts` — tests store but not transport

**Design decision (pre-answered)**: Add a Vitest test file using `vi.mock` for WebSocket and fetch. Test: connect, reconnect backoff, session ID filtering, stale message drop, REST fallback activation, cleanup on unmount.

**Implementation steps**:
1. Create `src/hooks/useRealtimeTransport.test.ts`.
2. Mock `WebSocket` and `fetch`.
3. Test cases: connect/close lifecycle, reconnect delay increases, session ID rejects stale messages, REST fallback when auth token set, cleanup clears timers.
4. Run with `npm run test:unit`.

**Acceptance criteria**:
- At least 5 test cases covering core transport scenarios
- Tests pass in CI (Vitest)
- No flaky tests from timing dependencies

**Do not**:
- Test full store ingestion (covered by existing store tests)
- Mock real WebSocket servers (use `vi.mock`)

---

### Metrics to Track Next Cycle

| Metric | Source | Target |
|---|---|---|
| Bundle size (main + vendor chunks) | `npm run build` output | Documented baseline; no regression |
| Build time | `npm run build` timing | < 15s |
| Lint errors | `npm run lint` | 0 |
| Type errors | `tsc --noEmit` | 0 |
| Test count and pass rate | `npm run test:unit` | 100% pass; test count increasing |
| Largest component file | Manual / grep | < 400 lines (track `useDashboardStore.ts` separately) |
| Panel re-render count (DevTools) | React DevTools Profiler | No unnecessary re-renders |
| Accessibility issues | Manual check | `scope`, `htmlFor`, `prefers-reduced-motion` resolved |

### Assumptions and Data Gaps

| Item | Type | Impact |
|---|---|---|
| No live dashboard available for runtime testing | DATA_GAP | All findings from code analysis only; no Lighthouse, no DevTools profiling |
| Bundle size unknown (no build output available) | DATA_GAP | Cannot score initial load performance precisely |
| Frontend console errors in period unknown | DATA_GAP | Reliability score could be lower if runtime errors exist |
| Browser support target assumed as latest Chrome only | ASSUMPTION | Accessibility and compatibility scores based on modern browser |
| Operator complaints assumed as none | ASSUMPTION | UX score could be lower with real operator feedback |
| All dependencies assumed current based on version numbers | ASSUMPTION | No `npm audit` run; no CVE scan |
| Contrast ratios not measured | DATA_GAP | Accessibility score could be lower |

---

## TECH AUDIT 20260311 — 9.5/10 Dimension Uplift (Cycle 2)

> **Context**: the 20260309 cycle items (above) are all `done`. This second cycle addresses
> the remaining gaps identified by the `INITIAL_AUDIT` run on 2026-03-11 and defines the
> full roadmap to reach **9.5/10 on every dimension**.

### Current vs Target Scorecard

| Dimension | Current | Gap | Target | Key blockers |
|---|---|---|---|---|
| Reliability | 7 | +2.5 | 9.5 | No top-level `on_tick` guard; ~60 silent `except Exception: pass` sites; no Redis health counters |
| Performance | 6 | +3.5 | 9.5 | Blocking Redis I/O in tick; stdlib `json` in hot path; sync CSV writes; no indicator caching; no micro-benchmark gate |
| Code health | 4→8 | +1.5 | 9.5 | ~~`shared_mm_v24.py` 5,687-line god file~~ decomposed to `runtime/kernel/` (7 mixins). ~~`hb_bridge` 2,796 lines with copy-paste~~ refactored to `simulation/bridge/`. ~~~90 `Any` types~~ reduced; mypy overrides configured. ~~no ruff/mypy CI gate~~ `.github/workflows/architecture_contracts.yml` added. Remaining: ruff integration, further `Any` reduction |
| Test coverage | 7→8 | +1.5 | 9.5 | ~~no parametrized boundary tests~~ `test_import_boundaries.py` + `test_coverage_minimums.py` enforce boundaries. ~~6+ source modules untested~~ added kernel, sim_broker, bridge tests. Remaining: risk_evaluator dedicated tests, further coverage in bridge paths |
| Infrastructure | 8 | +1.5 | 9.5 | 9 services missing memory limits; no CSV retention; no VPS logrotate config |
| Dependency freshness | 8 | +1.5 | 9.5 | No automated CVE scan; no `orjson`; no bounded `redis.asyncio` experiment |

> **Pro-grade refactoring completed (2026-03-22)**: 14-phase refactoring covering directory restructure, module decomposition (epp_v2_4.py→kernel mixins, paper_engine_v2→simulation/, services/common→platform_lib/), error handling hardening (all silent except:pass justified), concurrency safety (bridge_state thread contracts, atexit cleanup), type safety (mypy overrides, type:ignore codes), 57 new tests, import boundary CI enforcement. See `openspec/changes/pro-grade-code-refactoring/tasks.md` for full manifest.

### Phased Execution Order

**Phase 1 — Reliability + Test Regression (weeks 1-2)**
> Fix what can break the bot first; close active test regressions.

- `P0-TECH-20260311-1` on_tick guard with circuit breaker *(L-effort)*
- `P1-TECH-20260311-14` fix 4 failing candle tests *(M-effort)*
- `P1-TECH-20260311-15` close kill-switch + recon test gaps *(M-effort)*
- `P1-TECH-20260311-18` memory limits for all services *(quick win)*

**Phase 2 — Performance + Infrastructure (weeks 3-4)**
> Remove the biggest latency sources; close infra gaps.

- `P1-TECH-20260311-4` ThreadPoolExecutor for Redis reads *(L-effort)*
- `P1-TECH-20260311-5` orjson for hot-path JSON *(quick win)*
- `P1-TECH-20260311-6` background CSV + indicator memoization *(M-effort)*
- `P1-TECH-20260311-19` CSV retention + logrotate *(M-effort)*

**Phase 3 — Code Health: God-File Decomposition (weeks 5-8)**
> Systematic extraction from `shared_mm_v24.py` in safe, test-backed phases.

- `P1-TECH-20260311-8` extract RiskOrchestrator + TelemetryEmitter *(L-effort)*
- `P1-TECH-20260311-9` extract FillHandler + PositionManager *(L-effort)*
- `P1-TECH-20260311-10` unify `_patched_buy/_sell` + split hb_bridge *(M-effort)*
- `P1-TECH-20260311-11` split realtime_ui_api into route modules *(M-effort)*

**Phase 4 — Type Safety + Static Analysis (weeks 9-10)**
> Harden type contracts and enforce lint/type gates.

- `P2-TECH-20260311-12` TypedDict for snapshots + return annotations *(M-effort)*
- `P2-TECH-20260311-13` enforce ruff + mypy in CI *(M-effort)*

**Phase 5 — Test Depth + Coverage Floor (weeks 11-12)**
> Parametrize boundaries, cover untested services, raise floor.

- `P1-TECH-20260311-16` parametrized boundary tests *(M-effort)*
- `P2-TECH-20260311-17` untested services + datetime mock + coverage floor *(L-effort)*

**Phase 6 — Hardening + Governance (weeks 13-14)**
> Finish infra hardening, dep governance, chaos baseline.

- `P1-TECH-20260311-2` systematic silent-exception elimination *(L-effort)*
- `P1-TECH-20260311-3` Redis health counters *(quick win)*
- `P2-TECH-20260311-7` tick-loop micro-benchmark gate *(M-effort)*
- `P2-TECH-20260311-20` Redis connection pool + chaos smoke test *(M-effort)*
- `P2-TECH-20260311-21` automated quarterly CVE/outdated audit *(quick win)*

---

### RELIABILITY (7 → 9.5)

### [P0-TECH-20260311-1] Guard `on_tick` with top-level exception circuit breaker `done (2026-03-11)`

**Why it matters**: an unguarded exception in any sub-step of `on_tick` kills the tick loop, effectively freezing the bot. This is the single highest reliability risk found in the audit — all 5 past incident fixes are bypassed if the tick loop dies.

**What exists now**:
- `hbot/scripts/shared/v2_with_controllers.py:1510-1552` — `on_tick()` calls `super().on_tick()` without a top-level exception guard
- Individual sub-steps have try/except but gaps exist between them

**Design decision (pre-answered)**: wrap the entire `on_tick` body in `try/except Exception` that logs via `logger.exception()` and increments a consecutive-error counter. After N consecutive failures (default 5), trigger emergency soft-pause rather than silently swallowing. Do NOT catch `SystemExit` or `KeyboardInterrupt`.

**Implementation steps**:
1. Add `_tick_consecutive_error_count: int = 0` field and `_TICK_ERROR_CIRCUIT_BREAKER: int = 5` constant
2. Wrap `on_tick()` body in `try: ... except Exception: self.logger().exception("on_tick unhandled"); self._tick_consecutive_error_count += 1`
3. Reset counter to 0 on successful tick completion
4. If count exceeds breaker threshold, set `_emergency_soft_pause = True` and log at CRITICAL
5. Expose `tick_error_count` and `tick_circuit_breaker_tripped` in heartbeat JSON
6. Add test `tests/scripts/test_v2_with_controllers_tick_guard.py`: inject exception, verify tick continues, verify circuit breaker trips after threshold

**Acceptance criteria**:
- Injecting an exception in any `on_tick` sub-step does not crash the tick loop
- Consecutive errors above threshold trigger soft-pause
- Error count is visible in heartbeat JSON and bot-watchdog can observe it
- Score delta: 7 → 8.0

**Do not**:
- Catch `SystemExit` or `KeyboardInterrupt`
- Silence errors without logging
- Remove existing sub-step guards

### [P1-TECH-20260311-2] Systematic silent-exception elimination (60+ sites → <10) `done (2026-03-11)`

**Why it matters**: ~60+ `except Exception: pass` or silent-fallback sites mask operational failures across `hb_bridge.py` (27 sites), `portfolio.py` (8), `data_feeds.py` (5), `desk.py` (4), `state_store.py` (5), `shared_mm_v24.py` (8), and `matching_engine.py` (2). Silent masking allowed the original event-store data-loss and exporter-stale-cache incidents.

**What exists now**:
- `hbot/controllers/paper_engine_v2/hb_bridge.py` — 27 `except Exception: pass` or silent fallback sites
- `hbot/controllers/paper_engine_v2/portfolio.py` — 8 sites
- `hbot/controllers/paper_engine_v2/data_feeds.py` — 5 sites
- `hbot/controllers/paper_engine_v2/desk.py` — 4 sites
- `hbot/controllers/paper_engine_v2/state_store.py` — 5 sites
- `hbot/controllers/shared_mm_v24.py` — 8 sites
- `hbot/controllers/paper_engine_v2/matching_engine.py` — 2 sites

**Design decision (pre-answered)**: batch by file, one PR per batch. Replace each `except Exception: pass` with one of: (a) `logger.warning(..., exc_info=True)` for non-critical ops, (b) `logger.exception(...)` + degraded-state counter for critical ops, or (c) document as intentionally silent with `# INTENTIONAL: ...` comment for the <10 justified cases.

**Implementation steps**:
1. Batch 1: `hb_bridge.py` — classify all 27 sites, replace with structured logging or justified comment
2. Batch 2: `portfolio.py` + `desk.py` + `state_store.py` + `data_feeds.py` — 22 sites
3. Batch 3: `shared_mm_v24.py` + `matching_engine.py` — 10 sites
4. Add `rg "except Exception.*pass" hbot/controllers/ | wc -l` check to promotion gate with threshold <10
5. Add regression tests for top 5 most critical sites (heartbeat write, open-order snapshot, bridge event consumption)

**Acceptance criteria**:
- `rg "except Exception.*pass" hbot/controllers/` returns fewer than 10 matches
- Every remaining `pass` site has an `# INTENTIONAL:` justification comment
- No new silent failures hide operational issues
- Score delta: 8.0 → 9.0

**Do not**:
- Turn non-fatal operational errors into hard crashes
- Remove degraded-mode fallbacks; make them visible instead

### [P1-TECH-20260311-3] Redis health counters and service reconnect observability `done (2026-03-11)`

**Why it matters**: `RedisStreamClient` has reconnect logic with backoff, but there are no exposed counters for reconnect attempts, reconnect successes, or current connection health per service. Operators cannot distinguish Redis blips from sustained outages without these metrics.

**What exists now**:
- `hbot/services/hb_bridge/redis_client.py` — reconnect with 1-30s backoff, but no counters or health metric exposed
- Prometheus scrapes bot and control-plane metrics but has no Redis client health signals

**Design decision (pre-answered)**: add counters to `RedisStreamClient`: `reconnect_attempts_total`, `reconnect_successes_total`, `connection_errors_total`, `current_connected` boolean. Expose via a `health()` method that services can publish to their metrics endpoints.

**Implementation steps**:
1. Add counter fields to `RedisStreamClient.__init__`
2. Increment in `_ensure_connected()` on attempt/success/failure
3. Add `health() -> dict` method returning counters + uptime
4. Wire into `bot_metrics_exporter` and `control_plane_metrics_exporter` as `hbot_redis_client_*` gauges/counters
5. Add Grafana alert rule for `reconnect_attempts_total` rate > 5/min

**Acceptance criteria**:
- Redis health counters visible in Prometheus
- Reconnect events generate log + counter increment
- Grafana alert fires on sustained reconnect churn
- Score delta: 9.0 → 9.5

**Do not**:
- Change the existing reconnect backoff behavior
- Add high-cardinality labels (one counter set per service instance is sufficient)

---

### PERFORMANCE (6 → 9.5)

### [P1-TECH-20260311-4] ThreadPoolExecutor bridge for blocking Redis reads in tick loop `done (2026-03-11)`

**Why it matters**: all Redis reads in the tick path use blocking `RedisStreamClient`, which blocks the Hummingbot event loop during each I/O round trip. This is the single largest latency source identified in the audit. Full async migration is infeasible (Hummingbot's controller is synchronous), but a thread pool bridge is bounded and reversible.

**What exists now**:
- `hbot/services/hb_bridge/redis_client.py` — blocking `redis.Redis` client
- `hbot/controllers/shared_mm_v24.py` — tick path calls Redis for signal reads, telemetry publishes
- `hbot/controllers/paper_engine_v2/hb_bridge.py` — bridge calls Redis for order commands

**Design decision (pre-answered)**: wrap blocking Redis calls in `concurrent.futures.ThreadPoolExecutor` with a bounded pool (max 2 threads). Keep the synchronous API surface; callers use `executor.submit(...).result(timeout=...)` with a conservative timeout. Rollback: remove executor wrapper, revert to direct calls.

**Implementation steps**:
1. Add `ThreadPoolExecutor(max_workers=2)` to `RedisStreamClient.__init__`
2. Add `_execute_threaded(fn, *args, timeout_s=1.0)` internal helper
3. Wrap `xadd`, `xread`, `get`, `set` calls through the threaded executor
4. Add timeout handling: if thread times out, log warning and return cached/default value
5. Add `redis_io_latency_ms` histogram to self-metrics
6. Benchmark: measure tick latency p50/p99 before vs after

**Acceptance criteria**:
- Tick loop is not blocked during Redis I/O
- `redis_io_latency_ms` p99 < 50ms under normal load
- Rollback to direct calls takes <5 minutes
- Score delta: 6 → 7.5

**Do not**:
- Refactor the entire tick path to async/await
- Use unbounded thread pools
- Remove the timeout — unbounded waits are worse than blocking

### [P1-TECH-20260311-5] Adopt `orjson` for hot-path JSON serialization `done (2026-03-11)`

**Why it matters**: `_emit_tick_output` serializes a full state snapshot to JSON every tick (~1s). `orjson` is 3-10x faster than stdlib `json` for typical payloads. Bounded migration, easy rollback.

**What exists now**:
- `hbot/controllers/tick_emitter.py` — uses `json.dumps()` for tick output
- `hbot/controllers/shared_mm_v24.py` — uses `json.dumps()` in `_build_tick_snapshot` and event payloads
- `hbot/services/event_store/main.py` — uses `json.loads()` for event parsing

**Design decision (pre-answered)**: add `orjson>=3.10` to requirements. Replace `json.dumps/loads` in tick-hot paths only. Use `orjson.dumps(..., option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY, default=str).decode()` to handle `Decimal` and numpy types. Keep stdlib `json` in non-hot paths.

**Implementation steps**:
1. Add `orjson>=3.10` to `requirements-control-plane.txt` and `pyproject.toml`
2. Replace `json.dumps()` in `tick_emitter.py` and `_build_tick_snapshot` with `orjson.dumps(...).decode()`
3. Replace `json.loads()` in event-store ingest hot path with `orjson.loads()`
4. Add `Decimal` serialization test (ensure `default=str` handles it)
5. Benchmark: JSON serialization time before vs after on representative tick snapshot

**Acceptance criteria**:
- Tick output JSON is content-identical before/after
- Measurable serialization speedup (target: >3x for tick snapshot)
- All existing tests pass without modification
- Score delta: 7.5 → 8.0

**Do not**:
- Replace `json` globally in one shot — only hot paths
- Change JSON output format, key ordering, or encoding

### [P1-TECH-20260311-6] Background-thread CSV writes and indicator memoization `done (2026-03-11)`

**Why it matters**: `tick_emitter.py` does synchronous file I/O every tick for `minute.csv` and telemetry. Indicator recomputation across ticks may be redundant when market data hasn't changed. Together these consume ~10-20% of tick budget under normal conditions.

**What exists now**:
- `hbot/controllers/tick_emitter.py:374 lines` — sync `csv.writer.writerow()` on every tick
- `hbot/controllers/shared_mm_v24.py` — `_compute_adaptive_spread_knobs` (~192 lines) called every tick; unclear if inputs are cached

**Design decision (pre-answered)**: (a) move CSV writes to a bounded queue + background writer thread with flush-on-shutdown; (b) add input-hash memoization to `_compute_adaptive_spread_knobs` so it short-circuits when inputs haven't changed.

**Implementation steps**:
1. Add `_csv_write_queue: queue.Queue[tuple]` and background `_csv_writer_thread` to `TickEmitter`
2. `emit()` enqueues row; background thread writes + flushes at configurable interval (default 5s)
3. Add `shutdown()` that flushes remaining queue items
4. Add input-hash check to `_compute_adaptive_spread_knobs`: hash key = `(mid, volatility, regime, imbalance, spread_state)` → skip recomputation if unchanged
5. Add tick-output timing breakdown: `csv_write_ms`, `spread_compute_ms`, `snapshot_build_ms`

**Acceptance criteria**:
- CSV write no longer blocks tick loop
- `_compute_adaptive_spread_knobs` skips when inputs unchanged (verified by counter)
- No data loss on shutdown (queue fully flushed)
- Score delta: 8.0 → 9.0

**Do not**:
- Use unbounded queues (cap at 1000 rows, drop with warning if full)
- Remove sync flush on shutdown — data integrity is non-negotiable

### [P2-TECH-20260311-7] Tick-loop micro-benchmark gate artifact `done (2026-03-11)`

**Why it matters**: without a repeatable benchmark, performance improvements cannot be verified and regressions cannot be caught. The audit relied on inference rather than measurement.

**What exists now**:
- `hbot/tests/scripts/test_check_runtime_performance_budgets.py` — checks budget artifact but doesn't generate benchmark data
- `hbot/reports/verification/runtime_performance_budgets_latest.json` — exists but has limited samples

**Design decision (pre-answered)**: add a deterministic micro-benchmark that runs a representative tick cycle (snapshot build + spread compute + JSON serialize + CSV emit) against synthetic data. Publish results to `reports/verification/tick_benchmark_latest.json`. Wire as a non-blocking gate (warn, don't fail) in promotion cycle.

**Implementation steps**:
1. Add `scripts/release/run_tick_benchmark.py` that constructs synthetic tick state and runs 1000 iterations
2. Report p50/p95/p99/max for each sub-step and total
3. Emit `reports/verification/tick_benchmark_latest.json`
4. Add threshold check: total tick p99 < 50ms (warn), < 100ms (fail)
5. Add to promotion cycle as non-blocking gate

**Acceptance criteria**:
- Benchmark is deterministic and repeatable (synthetic data, no external deps)
- Results published as gate artifact
- Performance regressions are detectable between releases
- Score delta: 9.0 → 9.5

**Do not**:
- Make this a blocking gate until baselines are established (warn only for first 2 cycles)
- Benchmark against live Redis or live market data

---

### CODE HEALTH (4 → 9.5)

### [P1-TECH-20260311-8] Split `shared_mm_v24.py` Phase 1 — extract RiskOrchestrator and TelemetryEmitter `done (2026-03-11)`

**Why it matters**: `shared_mm_v24.py` at 5,687 lines is a god file mixing risk evaluation, spread computation, execution planning, telemetry output, fill handling, position management, and config reload. Phase 1 extracts the two most separable concerns: risk orchestration (which calls `risk_evaluator.py` + `risk_policy.py`) and telemetry emission (which calls `tick_emitter.py`).

**What exists now**:
- `hbot/controllers/shared_mm_v24.py` — `SharedRuntimeKernel` with 100+ methods
- Risk-related methods: `_evaluate_risk_state`, `_apply_risk_decision`, `_check_edge_gate`, and ~15 risk helper methods
- Telemetry-related methods: `_emit_tick_output` (261 lines), `_build_tick_snapshot` (162 lines), and ~10 telemetry helper methods

**Design decision (pre-answered)**: extract `RiskOrchestrator` class into `controllers/risk_orchestrator.py` and `TelemetryEmitter` class into `controllers/telemetry_emitter.py`. Both are instantiated by `SharedRuntimeKernel.__init__` and receive a reference to the kernel for state access. Public API surface of `SharedRuntimeKernel` remains unchanged (methods delegate).

**Implementation steps**:
1. Create `controllers/risk_orchestrator.py` with `RiskOrchestrator` class containing all risk evaluation methods
2. Create `controllers/telemetry_emitter.py` with `TelemetryEmitter` class containing `_emit_tick_output`, `_build_tick_snapshot`, and helpers
3. Replace method bodies in `SharedRuntimeKernel` with delegation calls: `self._risk_orchestrator.evaluate_risk_state(...)`
4. Move tests to `tests/controllers/test_risk_orchestrator.py` and `tests/controllers/test_telemetry_emitter.py`
5. Verify: `shared_mm_v24.py` drops below 4,500 lines

**Acceptance criteria**:
- All existing tests pass without modification to assertions
- `shared_mm_v24.py` reduced by ≥1,000 lines
- No circular imports between new modules and `shared_mm_v24.py`
- Score delta: 4 → 5.5

**Do not**:
- Change external API or behavior of `SharedRuntimeKernel`
- Mix strategy-lane logic into the extracted modules
- Extract methods that have heavy bidirectional state coupling (defer those to Phase 2)

### [P1-TECH-20260311-9] Split `shared_mm_v24.py` Phase 2 — extract FillHandler and PositionManager `done (2026-03-11)`

**Why it matters**: after Phase 1, `shared_mm_v24.py` is still ~4,500 lines. The next most separable concerns are fill handling (`did_fill_order` at 324 lines + helper methods) and position management (`check_position_rebalance`, `_run_startup_position_sync` at 157 lines + helpers).

**What exists now**:
- `hbot/controllers/shared_mm_v24.py` — `did_fill_order` (~324 lines), `did_cancel_order`, `did_fail_order`, position sync and rebalance methods
- These methods have moderate coupling to kernel state but communicate through well-defined events and position snapshots

**Design decision (pre-answered)**: extract `FillHandler` into `controllers/fill_handler.py` and `PositionManager` into `controllers/position_manager.py`. Both receive kernel reference. Public event callbacks on `SharedRuntimeKernel` remain but delegate.

**Implementation steps**:
1. Create `controllers/fill_handler.py` with `FillHandler` — owns `did_fill_order`, `did_cancel_order`, `did_fail_order` and their helpers
2. Create `controllers/position_manager.py` with `PositionManager` — owns `check_position_rebalance`, `_run_startup_position_sync`, position accounting helpers
3. Update `SharedRuntimeKernel` to delegate: `def did_fill_order(self, event): self._fill_handler.handle(event)`
4. Move/extend tests correspondingly
5. Verify: `shared_mm_v24.py` drops below 3,200 lines

**Acceptance criteria**:
- All existing tests pass
- `shared_mm_v24.py` reduced by ≥1,200 additional lines (cumulative ≥2,200 from baseline)
- Fill handling and position management have dedicated test files
- Score delta: 5.5 → 6.5

**Do not**:
- Break the Hummingbot `did_fill_order` callback contract
- Move `_compute_adaptive_spread_knobs` (too coupled; save for Phase 3 if ever)

### [P1-TECH-20260311-10] Unify `_patched_buy`/`_patched_sell` and split `hb_bridge.py` `done (2026-03-11)`

**Why it matters**: `hb_bridge.py` (2,796 lines) contains `_patched_buy` and `_patched_sell` which are near-identical 222-line methods — a duplication and divergence risk. The file also mixes budget checking, order patching, and event plumbing.

**What exists now**:
- `hbot/controllers/paper_engine_v2/hb_bridge.py:2213-2657` — `_patched_buy` and `_patched_sell` differ only in trade type and side constants
- `PaperBudgetChecker` class (focused, 6 methods) is already separable

**Design decision (pre-answered)**: (a) extract shared order logic into `_patched_order(self, side: TradeType, ...)`, reduce `_patched_buy/_sell` to 5-line wrappers; (b) move `PaperBudgetChecker` to `paper_engine_v2/budget_checker.py`.

**Implementation steps**:
1. Create `_patched_order(self, side, connector_name, trading_pair, amount, order_type, price, position_action)` with shared logic
2. Reduce `_patched_buy`/`_patched_sell` to wrappers that call `_patched_order` with `TradeType.BUY`/`SELL`
3. Move `PaperBudgetChecker` to `paper_engine_v2/budget_checker.py` with re-export
4. Run `test_hb_bridge_signal_routing.py` and `test_hb_bridge_event_isolation.py`

**Acceptance criteria**:
- All hb_bridge tests pass unchanged
- `hb_bridge.py` reduced by ≥300 lines
- No duplication between buy and sell order paths
- Score delta: 6.5 → 7.0

**Do not**:
- Change external API or argument signatures
- Modify test expectations

### [P1-TECH-20260311-11] Split `realtime_ui_api/main.py` into route modules `done (2026-03-11)`

**Why it matters**: `realtime_ui_api/main.py` at 4,530 lines is a second god file containing all REST/SSE endpoints, state management, stream consumers, and fallback readers in one module.

**What exists now**:
- `hbot/services/realtime_ui_api/main.py` — REST endpoints (`/api/v1/state`, `/api/v1/candles`, `/api/v1/depth`, `/api/v1/positions`, `/api/v1/stream`), stream consumers, CSV fallback readers, health endpoints

**Design decision (pre-answered)**: extract into sub-modules: `routes_state.py` (market/position/order state), `routes_history.py` (candles/fills/review), `routes_stream.py` (SSE), `stream_consumer.py` (Redis consumer logic), `fallback_readers.py` (CSV/DB fallback). Main file becomes wiring + startup only.

**Implementation steps**:
1. Create `realtime_ui_api/routes_state.py` — state, depth, positions endpoints
2. Create `realtime_ui_api/routes_history.py` — candles, fills, daily/weekly review
3. Create `realtime_ui_api/routes_stream.py` — SSE stream endpoint
4. Create `realtime_ui_api/stream_consumer.py` — Redis stream consumer thread logic
5. Create `realtime_ui_api/fallback_readers.py` — CSV/DB bounded readers
6. Reduce `main.py` to app startup, middleware, and route registration (<300 lines)

**Acceptance criteria**:
- All `test_realtime_ui_api.py` tests pass
- `main.py` reduced to <300 lines
- Each route module is independently testable
- Score delta: 7.0 → 7.5

**Do not**:
- Change REST API contract or endpoint paths
- Remove fallback readers (they are operational safety nets)

### [P2-TECH-20260311-12] TypedDict for tick snapshots and return type annotations `done (2026-03-11)`

**Why it matters**: `Dict[str, Any]` is used for tick snapshots, execution plans, and custom info — making it impossible to catch key-name typos or missing fields at dev time. 10+ public functions lack return type annotations.

**What exists now**:
- `hbot/controllers/shared_mm_v24.py` — `_build_tick_snapshot() -> Dict[str, Any]`, `get_custom_info() -> dict`, `get_executor_config(...)` with no return type
- `hbot/controllers/runtime/data_context.py` — `RuntimeDataContext` is a dataclass but tick snapshot is still raw dict

**Design decision (pre-answered)**: define `TickSnapshot(TypedDict)` in `controllers/core.py`, `ExecutionPlan(TypedDict)` in `runtime/execution_context.py`. Add return type annotations to all public methods in `SharedRuntimeKernel`.

**Implementation steps**:
1. Define `TickSnapshot` TypedDict with all known keys from `_build_tick_snapshot`
2. Define `ExecutionPlan` TypedDict for `get_executor_config` return
3. Update `_build_tick_snapshot` return type to `TickSnapshot`
4. Add return type annotations to the top 20 public methods by call frequency
5. Run mypy on `shared_mm_v24.py` and fix type errors

**Acceptance criteria**:
- `_build_tick_snapshot` and `get_executor_config` have typed returns
- All public methods in `SharedRuntimeKernel` have return type annotations
- `mypy hbot/controllers/shared_mm_v24.py` passes with `--strict` on annotated functions
- Score delta: 7.5 → 8.5

**Do not**:
- Use `Any` as a cop-out annotation — if the type is truly dynamic, use `Union` or document why
- Change runtime behavior; this is a type-annotation-only change

### [P2-TECH-20260311-13] Enforce `ruff` and `mypy` in CI gate `done (2026-03-11)`

**Why it matters**: `ruff>=0.5` and `mypy>=1.11` are in optional deps but not enforced. Without CI enforcement, unused imports, dead code, type errors, and style drift accumulate unchecked.

**What exists now**:
- `hbot/pyproject.toml` — `ruff>=0.5` and `mypy>=1.11` listed as optional dev dependencies
- No CI gate, no pre-commit hook, no `[tool.ruff]` or `[tool.mypy]` configuration

**Design decision (pre-answered)**: add `[tool.ruff]` with `select = ["E", "F", "W", "I"]` (errors, pyflakes, warnings, isort). Add `[tool.mypy]` with `--ignore-missing-imports` and strict mode for `controllers/` only (gradual). Add both to promotion gate.

**Implementation steps**:
1. Add `[tool.ruff]` section to `pyproject.toml` with selected rules and `exclude` for tests
2. Add `[tool.mypy]` section with `ignore_missing_imports = true` and per-module overrides for `controllers/`
3. Run `ruff check hbot/controllers/ hbot/services/` and fix immediate failures
4. Add `ruff check` and `mypy hbot/controllers/` steps to `scripts/release/run_strict_promotion_cycle.py`
5. Add pre-commit hook config (optional, for developer convenience)

**Acceptance criteria**:
- `ruff check` passes on controllers/ and services/ with selected rules
- `mypy` passes on controllers/ with gradual strict mode
- Promotion gate includes both checks
- Score delta: 8.5 → 9.5

**Do not**:
- Enable all ruff rules at once (start conservative, expand next cycle)
- Block on mypy for services/ (controllers first, services follow)

---

### TEST COVERAGE (7 → 9.5)

### [P1-TECH-20260311-14] Fix 4 failing candle tests in `test_realtime_ui_api.py` `done (2026-03-11)`

**Why it matters**: 4 tests fail actively, reducing test suite confidence and masking future regressions in candle/chart logic which is operator-facing.

**What exists now**:
- `hbot/tests/services/test_realtime_ui_api.py` — `test_realtime_state_candles_from_market_history`, `test_realtime_state_candles_include_depth_mid_history`, `test_realtime_state_get_candles_uses_instance_pair_when_pair_omitted`, `test_realtime_state_get_connector_candles_scopes_same_pair_to_requested_connector` — all fail with assertion errors (empty candle list returned)

**Design decision (pre-answered)**: investigate whether candle construction logic or test setup diverged. Fix tests if behavior is correct; fix logic if tests are correct. Root cause is likely a test-setup mismatch after candle API refactoring in ROAD-13.

**Implementation steps**:
1. Read failing tests and trace candle construction path in `realtime_ui_api/main.py`
2. Identify API/data-structure divergence between test setup and current implementation
3. Fix test setup or production code as appropriate
4. Run full test suite to confirm zero regressions

**Acceptance criteria**:
- All 4 tests pass
- Full test suite passes with `--ignore=hbot/tests/integration`
- Score delta: 7 → 7.5

**Do not**:
- Skip or delete failing tests
- Change candle logic without understanding the intended behavior

### [P1-TECH-20260311-15] Close safety-critical test gaps (kill-switch, reconciliation, risk_evaluator) `done (2026-03-11)`

**Why it matters**: three safety-critical paths lack complete test coverage: (a) kill switch partial-cancel ERROR logging assertion, (b) reconciliation with empty CSV + events, (c) `risk_evaluator.py` has no dedicated unit tests (only tested indirectly).

**What exists now**:
- `hbot/tests/services/test_kill_switch.py` — `test_some_orders_fail_partial_status` checks status but does NOT assert `logger.error("Kill switch escalation...")` is called
- `hbot/tests/services/test_reconciliation_service.py` — only single-row CSV tested, no empty-CSV edge case
- `hbot/controllers/risk_evaluator.py` (198 lines) — no `tests/controllers/test_risk_evaluator.py`

**Design decision (pre-answered)**: add logger mock assertions, new edge-case tests, and a dedicated unit test file for `risk_evaluator.py`.

**Implementation steps**:
1. In `test_kill_switch.py`: add `mock_logger.error.assert_called_once_with(...)` to `test_some_orders_fail_partial_status`
2. In `test_reconciliation_service.py`: add `test_run_once_empty_csv_with_events_no_crash` with header-only CSV + fill events
3. Create `tests/controllers/test_risk_evaluator.py` with tests for edge-gate blocking, risk-state evaluation, and boundary conditions
4. Run all three test files in isolation

**Acceptance criteria**:
- Kill switch test asserts ERROR log on partial cancel
- Reconciliation test proves empty CSV + events produces no crash and correct parity
- `risk_evaluator.py` has ≥10 dedicated unit tests
- Score delta: 7.5 → 8.0

**Do not**:
- Modify production code in this item (test-only)
- Add flaky time-dependent assertions

### [P1-TECH-20260311-16] Add parametrized boundary tests for risk, sizing, and regime `done (2026-03-11)`

**Why it matters**: only 1 test across 119 files uses `@pytest.mark.parametrize`. Boundary values in risk policy (spread = 0, size = min, drawdown = max), order sizing (Kelly extremes), and regime transitions are under-tested.

**What exists now**:
- `hbot/tests/controllers/test_risk_policy.py` — 9 tests, no parametrize
- `hbot/tests/controllers/test_epp_v2_4_core.py` — ~100 tests, no parametrize for boundaries
- `hbot/tests/services/test_paper_exchange_thresholds.py` — no parametrize

**Design decision (pre-answered)**: add `@pytest.mark.parametrize` to existing test files for boundary values. Focus on: risk_policy (threshold boundaries), spread_engine (zero/negative/extreme spreads), order_sizer (min/max/zero sizes), regime transitions (edge-of-threshold ADX/volatility), protective_stop (stop at exact level).

**Implementation steps**:
1. `test_risk_policy.py`: parametrize threshold tests with `[0, min-epsilon, min, min+epsilon, max, max+epsilon]`
2. `test_spread_engine.py`: parametrize spread inputs with `[0, negative, very_small, normal, extreme]`
3. `test_epp_v2_4_core.py`: parametrize regime transition tests with boundary ADX/vol values
4. `test_protective_stop.py`: parametrize stop-level tests with `[at_level, above_level, below_level, zero]`
5. Target: ≥30 new parametrized test cases across these files

**Acceptance criteria**:
- At least 30 new parametrized boundary test cases
- All boundary cases pass
- Edge cases that previously had no coverage are now tested
- Score delta: 8.0 → 8.5

**Do not**:
- Add parametrize to non-boundary tests where a single case is sufficient
- Generate excessive combinatorial tests that slow the suite

### [P2-TECH-20260311-17] Add tests for untested services, mock `datetime.now`, and raise coverage floor `done (2026-03-11)`

**Why it matters**: 6+ source modules have no test file: `telegram_bot`, `signal_service`, `shadow_execution`, `exchange_snapshot_service`, `risk_service`, `epp_logging`. 20+ test files use `datetime.now()` without mocking (flaky near midnight/DST). The coverage floor needs to reflect meaningful confidence.

**What exists now**:
- No test files for the modules listed above
- `datetime.now()` used unfreezed in `test_build_paper_exchange_threshold_inputs.py` (20+ uses), `test_reconciliation_service.py` (8), `test_reliability_slo.py` (7), and others
- Coverage floor at 5% (`test_check_runtime_performance_budgets.py`)

**Design decision (pre-answered)**: add basic smoke tests for each untested service (import, init, main-loop-with-mocked-deps). Replace raw `datetime.now()` with `freezegun` or `unittest.mock.patch` across test suite. Raise coverage floor to 30% in promotion gate.

**Implementation steps**:
1. Add `tests/services/test_telegram_bot.py`, `test_signal_service.py`, `test_shadow_execution.py`, `test_exchange_snapshot_service.py`, `test_risk_service.py`
2. Add `tests/controllers/test_epp_logging.py`
3. Each test file: ≥3 tests (import, init with mocks, one happy-path function)
4. Add `freezegun>=1.3` to dev dependencies
5. Replace `datetime.now()` with `@freeze_time` in top 10 affected test files
6. Raise coverage floor from 5% to 30% in `scripts/release/run_tests.py`

**Acceptance criteria**:
- Every source module under `services/` and `controllers/` has at least a basic test file
- No test uses `datetime.now()` without freezing/mocking
- Coverage floor is 30% and passes
- Score delta: 8.5 → 9.5

**Do not**:
- Write low-signal "test that it imports" tests beyond the smoke baseline
- Set coverage floor higher than actual measured coverage

---

### INFRASTRUCTURE (8 → 9.5)

### [P1-TECH-20260311-18] Add memory limits to all control-plane services `done (2026-03-11)`

**Why it matters**: 9 control-plane services have no memory limit. A leak in any one can OOM the host and crash all bots. This is a configuration-only change with high safety impact.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — missing `deploy.resources.limits.memory` on: `paper-exchange-service`, `signal-service`, `risk-service`, `coordination-service`, `event-store-service`, `event-store-monitor`, `market-data-service`, `realtime-ui-api`, `kill-switch`

**Design decision (pre-answered)**: `512M` for `paper-exchange-service` and `realtime-ui-api` (higher workload); `256M` for `market-data-service`, `event-store-service`, `signal-service`, `risk-service`, `coordination-service`; `128M` for `kill-switch`, `event-store-monitor`.

**Implementation steps**:
1. Add `deploy.resources.limits.memory` and `deploy.resources.reservations.memory` to each service in `docker-compose.yml`
2. Validate with `docker compose config`
3. Deploy and monitor for 24h — no OOM kills under normal load

**Acceptance criteria**:
- `docker compose config | Select-String "memory"` shows limits on every service
- No service OOM-kills on normal workload after 24h
- Score delta: 8 → 8.5

**Do not**:
- Set limits below minimum viable memory
- Change limits on services that already have them

### [P1-TECH-20260311-19] CSV/data retention policy and VPS logrotate hardening `done (2026-03-11)`

**Why it matters**: `minute.csv` and `fills.csv` in `data/bot*/logs/` grow unbounded with no retention policy. On a long-running VPS, this will eventually fill the disk. The VPS logrotate is installed but has no custom config for bot application logs.

**What exists now**:
- `hbot/config/artifact_retention_policy.json` — covers `reports/` but NOT `data/bot*/logs/`
- `hbot/data/bot*/logs/epp_v24/*/minute.csv` and `fills.csv` — grow unbounded
- VPS: `logrotate` installed via `deploy.sh` but no custom config

**Design decision (pre-answered)**: (a) add CSV rotation: when `minute.csv` > 100MB or > 30 days old, archive to `minute_YYYYMMDD.csv.gz` and start fresh; (b) add logrotate config for bot application logs (daily, 7 backups, compress); (c) add size-warning metric in bot_metrics_exporter when CSV > 50MB.

**Implementation steps**:
1. Add `scripts/ops/rotate_csv_logs.py` — archives old CSVs, compresses, keeps last 30 days
2. Add `infra/compose/logrotate.d/hbot` config file for application logs
3. Add `hbot_csv_file_size_bytes` gauge to bot_metrics_exporter
4. Add cron or container for CSV rotation (daily run)
5. Add Grafana alert when `hbot_csv_file_size_bytes > 100MB`

**Acceptance criteria**:
- CSV files are automatically rotated when exceeding size/age limits
- VPS application logs rotate with compression
- Operators are alerted before disk fills
- Score delta: 8.5 → 9.0

**Do not**:
- Delete current-day CSVs (only rotate completed days)
- Remove the artifact retention policy — extend it

### [P2-TECH-20260311-20] Redis connection pool and chaos/DR smoke test `done (2026-03-11)`

**Why it matters**: `RedisStreamClient` creates a single connection per instance — no pooling. A chaos/DR smoke test baseline ensures reconnect and failover patterns actually work under simulated failure.

**What exists now**:
- `hbot/services/hb_bridge/redis_client.py` — single `redis.Redis()` connection per client
- No chaos/fault-injection test for Redis disconnect recovery

**Design decision (pre-answered)**: (a) add `connection_pool` parameter to `RedisStreamClient` with `max_connections=4` default; (b) add a bounded chaos smoke test that kills Redis mid-stream-read and verifies all services reconnect within 60s.

**Implementation steps**:
1. Add `redis.ConnectionPool(max_connections=4)` to `RedisStreamClient.__init__`
2. Pass pool to `redis.Redis(connection_pool=...)`
3. Add `tests/integration/test_redis_chaos_smoke.py` — start Redis, connect N services, kill Redis, restart, verify reconnect
4. Mark as `@pytest.mark.integration` (excluded from normal runs)

**Acceptance criteria**:
- Connection pool is used by default
- Chaos test verifies reconnect within 60s for all services
- No regression in normal operation
- Score delta: 9.0 → 9.5

**Do not**:
- Run chaos test in CI (integration-only, manual trigger)
- Set pool size larger than needed (4 is sufficient for current service count)

---

### DEPENDENCY FRESHNESS (8 → 9.5)

### [P2-TECH-20260311-21] Automated quarterly CVE and outdated dependency audit `done (2026-03-11)`

**Why it matters**: there is no artifact-backed CVE/outdated review. The audit scored dependency freshness by manual inspection — this is not sustainable. A repeatable audit ensures freshness and security are tracked with evidence.

**What exists now**:
- `hbot/infra/compose/images/control_plane/requirements-control-plane.txt` — all packages pinned
- `hbot/pyproject.toml` — optional dev deps listed
- No CVE scanning, no outdated-package report, no audit artifact

**Design decision (pre-answered)**: add `scripts/release/run_dependency_audit.py` that uses `pip-audit` for CVE scanning and `pip list --outdated` for freshness. Emit `reports/verification/dependency_audit_latest.json`. Wire as non-blocking gate in promotion cycle.

**Implementation steps**:
1. Add `pip-audit>=2.7` to dev dependencies
2. Create `scripts/release/run_dependency_audit.py` — runs `pip-audit` + `pip list --outdated`, emits JSON report
3. Report fields: `cve_count`, `outdated_count`, `outdated_packages[]`, `cve_packages[]`, `audit_date`
4. Add to promotion cycle as non-blocking gate (warn on CVEs, info on outdated)
5. Schedule quarterly review: human reviews report and makes adopt/update/defer decisions

**Acceptance criteria**:
- `dependency_audit_latest.json` is emitted on each promotion run
- CVEs are surfaced with package name, version, and advisory link
- Outdated packages are listed with current vs latest version
- Score delta: 8 → 9.0

**Do not**:
- Auto-upgrade packages without human review
- Block promotion on outdated-but-not-vulnerable packages

### [P2-TECH-20260311-22] Bounded `orjson` and `redis.asyncio` adoption experiments `done (2026-03-11)`

**Why it matters**: `orjson` and `redis.asyncio` (via ThreadPoolExecutor bridge) are the two highest-value library adoptions identified. Both need measured evidence and bounded rollback plans before full adoption.

**What exists now**:
- `orjson` not in requirements (stdlib `json` used everywhere)
- `redis` 7.2.0 includes `redis.asyncio` but it is unused; all calls are blocking
- No experiment framework for measuring library migration impact

**Design decision (pre-answered)**: `orjson` is implemented in P1-TECH-20260311-5; `redis.asyncio` bridge is implemented in P1-TECH-20260311-4. This item tracks the evidence collection and adoption decision. Both experiments produce before/after benchmark artifacts. Decision framework: adopt if ≥30% improvement in target metric, rollback if any regression.

**Implementation steps**:
1. After P1-TECH-20260311-5: collect 48h of tick serialization timing evidence
2. After P1-TECH-20260311-4: collect 48h of Redis I/O latency evidence
3. Compare against pre-experiment baselines
4. Document decision in experiment ledger: adopt/defer/reject with evidence
5. Update `dependency_audit_latest.json` with adoption status

**Acceptance criteria**:
- Each experiment has before/after benchmark evidence in `reports/verification/`
- Adoption decision is documented in experiment ledger with measured evidence
- Rollback procedure tested before adoption is finalized
- Score delta: 9.0 → 9.5

**Do not**:
- Adopt without measured evidence
- Skip rollback testing

---

### Dimension Score Projection (cumulative)

| Dimension | Current | After Phase 1 | After Phase 2 | After Phase 3 | After Phase 4 | After Phase 5 | After Phase 6 | Final |
|---|---|---|---|---|---|---|---|---|
| Reliability | 7 | 8.0 | 8.0 | 8.0 | 8.0 | 8.0 | 9.5 | **9.5** |
| Performance | 6 | 6 | 9.0 | 9.0 | 9.0 | 9.0 | 9.5 | **9.5** |
| Code health | 4 | 4 | 4 | 7.5 | 9.5 | 9.5 | 9.5 | **9.5** |
| Test coverage | 7 | 8.0 | 8.0 | 8.0 | 8.0 | 9.5 | 9.5 | **9.5** |
| Infrastructure | 8 | 8.5 | 9.0 | 9.0 | 9.0 | 9.0 | 9.5 | **9.5** |
| Dep. freshness | 8 | 8 | 9.0 | 9.0 | 9.0 | 9.0 | 9.5 | **9.5** |

---

## Blocked / Waiting on Data or Human Action

### [ROAD-10] AI regime classifier — model training and rollout `done (2026-03-25)`
- **Closure evidence (2026-03-25)**:
  - Regime classifier trained via purged walk-forward CV (5 folds, embargo gap) on `regime_train_20260324.parquet` (47,371 rows).
  - Mean OOS accuracy: **58.83%** (threshold 55%) — deployment gates PASS.
  - Feature stability: 13 features in 60%+ windows — PASS.
  - Model deployed to `ml-feature-service`, `deployment_ready=true`, live predictions active (class probabilities published to `hb.ml_features.v1`).
  - 50+ features active: multi-TF (1m/5m/15m/1h), cross-TF confluence, microstructure, basis, volatility, calendar.
  - Model version: `2026-03-25T01:21:38.075018+00:00`.

### [ROAD-11] AI adverse selection classifier — model training and rollout `done (2026-03-25)`
- **Closure evidence (2026-03-25)**:
  - Adverse fill classifier trained via purged walk-forward CV on `adverse_fill_train_20260324.parquet` (13,662 rows, 21.5% adverse rate).
  - Mean OOS accuracy: **78.73%** (threshold 65%) — deployment gates PASS.
  - Feature stability: 9 features in 60%+ windows — PASS.
  - Model loaded in `ml-feature-service`, `deployment_ready=true`.
  - Shadow mode infrastructure ready (`ML_SHADOW_MODE` env var, dual inference, comparison logging).
  - Offline shadow evaluator deferred until soak data accumulates.

### [OPS-PREREQ-1] Testnet/API/alerting credentials readiness `blocked (human action)`
- Rotate and set valid Telegram bot token/chat id when configured.
- Provision/fund dedicated Bitget testnet keys.
- Keep strict gate checks fail-closed until credential probes pass.

### [OPS-PREREQ-2] Realtime UI auth/network hardening `blocked (security review)`
- Finalize auth mode for operator UI (`REALTIME_UI_API_AUTH_ENABLED`, token distribution path).
- Confirm bind-IP policy and firewall exposure for API/web ports.
- Complete security sign-off before setting `REALTIME_UI_API_MODE=active`.

---

## QUANT LOOP 2026-03-11 — Strategy Viability Review

> **Mode**: ITERATION · **Scope**: bot1, bot5, bot6, bot7 · **Review date**: 2026-03-11
>
> **Verdicts**: bot1 `freeze` · bot5 `keep` · bot6 `freeze` · bot7 `improve`

### [P0-QUANT-20260311-1] Freeze bot1 paper trading to stop loss accumulation `done (2026-03-11)`

**Why it matters**: 20-day ROAD-1 window failed all criteria (Sharpe -6.5, 0% win-rate days, -2.5 bps expectancy/fill, spread capture negative). Continuing accumulates ~-0.36 USDT/day with no path to edge recovery at current spread/fee configuration.

**What exists now**:
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml` — `no_trade: false`, active two-sided MM at 6-13.5 bps neutral spreads
- `hbot/reports/analysis/performance_dossier_latest.json` — 284 fills over 20 days, expectancy/fill -0.0251 USDT

**Design decision (pre-answered)**: set `no_trade: true` until a redesigned spread config produces positive theoretical edge.

**Implementation steps**:
1. Set `no_trade: true` in `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`
2. Restart bot1 and verify no new fills appear in `data/bot1/logs/epp_v24/bot1_a/fills.csv`
3. Confirm equity is flat in next desk snapshot

**Acceptance criteria**:
- No new fills after config change
- Equity stops declining
- Bot1 desk snapshot shows `state: no_trade`

**Do not**:
- Delete fill history or reset paper equity
- Restart with no_trade=false before a redesigned wider-spread config is validated theoretically

---

### [P0-QUANT-20260311-2] Flatten bot6 stuck inventory (77.7% base exposure) `done (2026-03-11)`

**Why it matters**: bot6 is in `soft_pause` with 77.7% base exposure against a 0% target. The CVD divergence signal is idle (`score_below_threshold`). Cannot evaluate the strategy while the position is stuck.

**What exists now**:
- `hbot/data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml` — strategy config
- Desk snapshot: `base_pct: 0.777`, `state: soft_pause`, `realized_pnl_today: 0`

**Design decision (pre-answered)**: force-cancel all open bot6 orders; wait for time_limit expiry to close position naturally; if stuck > 4h, set `no_trade: true` and document open position.

**Implementation steps**:
1. Cancel all open bot6 orders via paper exchange service or config change
2. Wait up to 4h for time_limit-based position closure
3. If position persists: set `no_trade: true` in bot6 config
4. Confirm `base_pct < 1%` in next desk snapshot

**Acceptance criteria**:
- `base_pct < 1%` in desk snapshot
- Bot6 state is `running` or `no_trade` (not `soft_pause`)
- No new directional fills while inventory is clearing

**Do not**:
- Add aggressive taker orders to flatten — use natural time_limit expiry
- Restart strategy logic until inventory is confirmed flat

---

### [P1-QUANT-20260311-2] Enable bot7 probes for thesis fill collection `done (2026-03-11)`

**Why it matters**: bot7 has only 1 thesis fill (probe_long) in 159 total fills. The entire -2.75 USDT loss is fee drag from non-thesis fills. The ADX Wilder fix (EXP-20260311-05) and threshold relaxation (EXP-20260311-04, ADX < 28) were just applied. Probes must be re-enabled to collect mean-reversion evidence.

**What exists now**:
- `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml` — `bot7_probe_enabled: false`, `bot7_warmup_quote_levels: 0`
- Lifetime thesis fills: 1 out of 159

**Design decision (pre-answered)**: re-enable probes; observe 48h; require >= 10 thesis fills (probe_* or mean_reversion_*) as minimum evidence before further tuning.

**Implementation steps**:
1. Set `bot7_probe_enabled: true` in `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`
2. After 48h, count fills where `alpha_policy_state` matches `probe_long`, `probe_short`, or `mean_reversion_*`
3. Compute thesis-only expectancy/fill on the sample
4. If < 10 thesis fills: escalate to P2-QUANT-20260311-2 (conjunction gate simplification)

**Acceptance criteria**:
- >= 10 thesis fills in 48h observation window
- Non-thesis fills < 5/day
- No hard_stop triggered

**Do not**:
- Re-enable warmup quotes at the same time (isolate the probe variable)
- Tune RSI/BB thresholds before probe evidence is collected

---

### [P1-QUANT-20260311-3] Wire bot5 alpha_policy attribution into fills dossier `done (2026-03-11)`

**Why it matters**: the bot5 dossier shows all 1542 fills attributed to `unknown` alpha_policy, preventing per-flow-state optimization. Cannot identify which flow states generate +3.6 bps/fill vs which destroy edge.

**What exists now**:
- `hbot/controllers/bots/bot5/ift_jota_v1.py` — `_bot5_flow_state["reason"]` is computed but not written into fills
- `hbot/reports/analysis/bot5_performance_dossier_latest.json` — all fills show `alpha_policy: unknown`

**Design decision (pre-answered)**: write `flow_state_reason` from `_bot5_flow_state["reason"]` into the fills.csv `alpha_policy_state` column at fill-time in the bot5 controller.

**Implementation steps**:
1. In `ift_jota_v1.py`, ensure `alpha_policy_state` is set to `self._bot5_flow_state.get("reason", "unknown")` when building fill metadata
2. Verify the attribution appears in `fills.csv` after next fill cycle
3. Re-run dossier: `python hbot/controllers/analytics/performance_metrics.py --bot bot5`
4. Confirm per-reason expectancy table appears in dossier output

**Acceptance criteria**:
- Next bot5 dossier shows per-flow-state expectancy breakdown (at minimum: neutral, directional_long, directional_short, derisk)
- `unknown` attribution drops to < 5% of fills

**Do not**:
- Change the attribution logic for other bots (bot5 lane only)
- Recompute historical fills retroactively — only new fills from the fix forward

---

### [P1-QUANT-20260311-4] Investigate bot5 161 bps P95 slippage `done (2026-03-12)`

**Why it matters**: P95 slippage of 161 bps (actually 278 bps on re-analysis with full dataset) indicated massive non-thesis fill contamination that overstated strategy costs.

**Root cause found**: Bot5's `_resolve_quote_side_mode` override skipped the shared runtime's `alpha_state == "no_trade"` cleanup entirely. When the gate transitioned to `fail_closed` (e.g., `fill_edge_below_cost_floor` or `selective_blocked`), stale resting maker orders from the Paper Exchange Service were never canceled.

**Analysis results** (4282 fills):
- 2900 fills (67.7%) tagged `fill_edge_below_cost_floor` — all non-thesis
- 94.6% of bad fills were MAKER (stale resting orders)
- 94.7% were SELLS — one-sided orphaning
- Price-to-mid gap: P50=1.9%, P95=2.88%, max=4.7%
- Two massive bursts: 1282 fills in 2hr on Mar 9, 1579 fills in 1hr on Mar 10
- Fee waste: 33.6 USDT on bad fills vs 14.1 USDT on thesis fills
- Thesis fills had tight slippage: directional_buy/sell P50 < 1 bps

**Fix applied**: Added gate `fail_closed` check to bot5's `_resolve_quote_side_mode`. When the gate reports `fail_closed`, the method now:
1. Cancels all active quote executors (`_cancel_active_quote_executors()`)
2. Cancels lingering paper exchange orders (`_cancel_alpha_no_trade_orders()`)
3. Sets mode to `"off"`

**Files changed**: `controllers/bots/bot5/ift_jota_v1.py`

**Acceptance criteria** (met):
- Root cause identified: orphaned maker sells from missing gate-off cleanup
- Strategy-side fix applied (not a parity discount)
- Expected P95 slippage after fix: < 10 bps (thesis fills only)

---

### [P1-QUANT-20260311-5] Fix bot6 dead-code fail_closed gate `done (2026-03-11)`

**Why it matters**: `_bot6_gate_metrics()` in `cvd_divergence_v1.py` hardcodes `fail_closed = False`, making the risk-append path in `_evaluate_all_risk()` unreachable. The gate can never block via risk, creating a silent safety gap.

**What exists now**:
- `hbot/controllers/bots/bot6/cvd_divergence_v1.py` line ~100: `fail_closed = False` (hardcoded)
- `_evaluate_all_risk()` appends `fail_closed` risk only if `fail_closed` is True — dead code

**Design decision (pre-answered)**: wire real fail conditions (stale features, funding risk, extreme inventory) into `fail_closed` logic; add unit test verifying the gate can trigger.

**Implementation steps**:
1. Identify the intended conditions for `fail_closed = True` in bot6 context (e.g., feature age > 5m, CVD signal NaN)
2. Replace hardcoded `False` with computed condition
3. Add unit test in `tests/controllers/test_epp_v2_4_bot6.py` that verifies risk gate triggers when conditions are met

**Acceptance criteria**:
- `fail_closed` evaluates to `True` under at least one realistic condition
- Unit test demonstrates gate triggers and blocks order placement
- No regression in existing bot6 tests

**Do not**:
- Apply this pattern to bot7 in the same PR — fix bot6 and bot7 in separate, reviewable changes
- Make `fail_closed` always True (over-blocking)

---

### [P1-QUANT-20260311-6] Bot6 signal timeframe alignment `done (2026-03-12)`

**Why it matters**: the CVD divergence signal uses a 30-trade window (~1-5 minutes of BTC flow) alongside a 15m candle trend filter (SMA 20/60). The timeframe mismatch means the trade-level CVD signal fires in conditions where the 15m trend is stale or uncorrelated, producing noisy conjunctions that rarely reach the score threshold.

**Root cause analysis (2026-03-12)**:
Gate instrumentation revealed the signal was 100% blocked by `trade_features_warmup` — not by score, ADX, or trend. The real binding constraint was:
1. **Zero spot trades in Redis**: `MARKET_DATA_SERVICE_DISCOVERY_CONNECTORS` only included `bitget_perpetual`. The `bitget` (spot) connector was never subscribed, so `spot_features.stale` was permanently True.
2. **Combined staleness check**: `DirectionalTradeFeatures.stale = futures.stale OR spot.stale` meant the missing spot data blocked the entire signal, even though futures data was flowing correctly (scores computed up to 10).
3. **Timeframe mismatch**: SMA 20/60 on 15m candles = 5h/15h horizon vs 30-trade window ≈ 1-5 minute horizon.

**Changes applied**:
1. **Staleness decoupling** (`cvd_divergence_v1.py`): Use `futures.stale` as the primary gate. Signal fires in "futures_only" mode when spot is stale but futures is fresh.
2. **Fail-closed gate cleanup** (`cvd_divergence_v1.py`): Added aggressive order cancellation when gate is `fail_closed`, matching bot5/bot7 pattern to prevent orphaned order contamination.
3. **Spot data infrastructure** (`docker-compose.yml`): Added `bitget|BTC-USDT` to `MARKET_DATA_SERVICE_SUBSCRIPTIONS` and `bitget` to `MARKET_DATA_SERVICE_DISCOVERY_CONNECTORS`.
4. **Timeframe alignment** (config): Switched `bot6_candle_interval: 15m` → `1m` (Option B). SMA 20/60 on 1m = 20min/60min horizon, aligning with the 30-trade (~1-5 min) flow window.

**Tests**: 6 new unit tests covering futures-stale blocking, spot-stale pass-through, full divergence reason, bearish futures-only, and fail-closed gate cleanup.

**Acceptance criteria**:
- Signal-fire rate >= 3/day in paper after change → observe 48h window
- No increase in stuck-inventory events → observe 48h window
- Unit test covers the new staleness decoupling + gate cleanup ✅

---

### [P2-QUANT-20260311-1] Bot1 wider-spread config experiment `in-progress (2026-03-12)`

**Why it matters**: the current 6-13.5 bps neutral spreads cannot cover VIP0 maker fees (~2 bps) plus adverse selection (~1.5 bps) plus slippage. A 15-30 bps spread regime with reduced fill factor provides positive theoretical edge.

**What exists now**:
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml` — frozen, `no_trade: true`
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot1_wider_spread_exp.yml` — experiment config, `no_trade: false`

**Edge calculation (2026-03-12)**:
- Cost model (conservative): maker(2) + adverse(2) + slippage(1.5) = 5.5 bps
- At spread_min 15 bps, fill_factor 0.20: effective half-spread = 13.5 bps
- Conservative edge per fill: +8.0 bps (passes > 3 bps gate ✓)
- Even at tightest spread (15 bps): half = 7.5, edge = +2.0 bps (positive ✓)

**Config changes from frozen baseline**:
- `no_trade: false` (re-enables quoting)
- All regime `spread_min`: 15-25 bps (was 2.5-6 bps)
- All regime `spread_max`: 30-50 bps (was 7.5-15 bps)
- All regime `fill_factor`: 0.20 (was 0.35-0.45)
- All regime `levels_max`: 1 (unchanged)
- `buy/sell_spreads` top-level: "0.00150,0.00300" (was "0.00025,0.00060")
- Neutral_high_vol: 18-35 bps (slightly wider for vol protection)
- High_vol_shock: 25-50 bps (widest for extreme conditions)

**Observation window**: 5 days minimum, 200 fills target, starting 2026-03-12.

**Acceptance criteria**:
- Positive expectancy/fill (CI95 lower bound > 0) on >= 200 maker fills
- Maker ratio >= 80%
- No hard_stop or drawdown > 3% in 5-day window

**Do not**:
- Overwrite the frozen bot1 config before evidence is collected
- Increase position size during the experiment

---

### [P2-QUANT-20260311-2] Bot7 conjunction gate simplification `blocked (requires P1-QUANT-20260311-2 probe evidence)`

**Why it matters**: if probe-enabled observation (P1-QUANT-20260311-2) produces < 10 thesis fills in 48h, the current conjunction gate (BB-touch + RSI + absorption/delta_trap + ADX) is too selective to generate sufficient evidence for any statistical conclusion.

**What exists now**:
- `hbot/controllers/bots/bot7/adaptive_grid_v1.py` — entry requires: BB(10,2) touch + RSI < 34 or > 66 + (absorption or delta_trap signal) + ADX < 28
- Thesis fill rate: 1 in 159 (0.6%)

**Design decision (pre-answered)**: if probes fail the 10-fill threshold, drop the absorption/delta_trap requirement for probes; use BB-touch + RSI only. This produces a testable, simpler thesis. If validated, re-add absorption/delta_trap as an exit-quality filter rather than entry gate.

**Implementation steps**:
1. Wait for P1-QUANT-20260311-2 evidence (48h)
2. If thesis fills >= 10: do not proceed with this item; tune existing conjunction
3. If thesis fills < 10: simplify probe entry to `bb_touch + (rsi_oversold or rsi_overbought)` only
4. Run 48h with simplified gate; measure thesis fill rate and expectancy

**Acceptance criteria**:
- >= 20 thesis fills/day in ranging BTC conditions with simplified gate
- Thesis-only expectancy/fill > 0 on >= 50 fill sample

**Do not**:
- Remove ADX gate from the full mean-reversion path (only relax probe entry)
- Proceed before P1-QUANT-20260311-2 evidence is collected

---

## Bot7 Strategy Audit (2026-03-12)

> **Mode**: INITIAL_AUDIT · **Scope**: bot7 · **Review date**: 2026-03-12
>
> **Baseline**: PnL/fill = -0.0136 USDT · maker% = 98.6% · thesis fill% = 12.2% · gate active = 1.8%
>
> **Verdict**: `improve` — non-thesis fill contamination and stale equity tracking are immediate blockers

### [P0-STRAT-20260312-1] Eliminate bot7 non-thesis fill contamination `done (2026-03-12)`

**Why it matters**: 87.8% (759/864) of bot7 fills are non-thesis (`regime_inactive`, `no_entry`, `unknown`), generating ~$6.91 in pure fee drag. The strategy's thesis cannot be evaluated while contaminated fills dominate the P&L.

**What exists now**:
- `hbot/controllers/bots/bot7/adaptive_grid_v1.py:_resolve_quote_side_mode` — conditional cleanup guard only fired for specific idle reasons
- `hbot/data/bot7/logs/epp_v24/bot7_a/fills.csv` — 400 `regime_inactive` + 272 `no_entry` + 40 `unknown` non-thesis fills

**Design decision (pre-answered)**: make idle-transition cleanup unconditional when `desired_mode == "off"`, and add `_cancel_alpha_no_trade_orders()` for comprehensive paper engine order cleanup.

**Implementation steps**:
1. Removed `cancel_active_when_off` guard in `_resolve_quote_side_mode` — cleanup now runs unconditionally for all `off` transitions
2. Added `_cancel_alpha_no_trade_orders()` call alongside existing `_cancel_active_quote_executors()` and `_force_cancel_orphaned_orders()` calls
3. All tests pass (130 core + full suite)

**Acceptance criteria**:
- Non-thesis fills < 5/day over 48h paper run
- No regression in thesis fill rate (>= 10/day maintained)

**Do not**:
- Disable the `_force_cancel_orphaned_orders` path — it handles edge cases the executor cancel misses

---

### [P0-STRAT-20260312-2] Fix drawdown/daily_loss risk metrics for paper perps `done (2026-03-12)`

**Why it matters**: `daily_loss_pct` and `drawdown_pct` both read 0.000 in bot7's minute.csv despite the bot losing money (-2.75 USDT/day). The hard-stop safety nets (`max_daily_loss_pct_hard: 0.020`, `max_drawdown_pct_hard: 0.035`) cannot fire if the metrics are always zero.

**What exists now**:
- `hbot/controllers/shared_mm_v24.py:_risk_loss_metrics` — computed from `equity_quote` vs `_daily_equity_open` / `_daily_equity_peak`
- Paper engine's `portfolio.equity_quote()` returns stale cash balance (5000) because perp PnL settlements don't flow to the ledger (see P1-STRAT-20260312-2)

**Design decision (pre-answered)**: add a fallback floor in `_risk_loss_metrics` using the controller's own PnL tracking (`_realized_pnl_today - _fees_paid_today_quote - _funding_cost_today_quote`). The `max()` of equity-based and PnL-based metrics is always correct regardless of whether the paper engine settles correctly.

**Implementation steps**:
1. Extended `_risk_loss_metrics` to compute `net_pnl` from controller-tracked daily PnL, fees, and funding
2. When `net_pnl < 0`, uses `abs(net_pnl) / open_equity` as a floor for `daily_loss_pct` and `abs(net_pnl) / peak_equity` as a floor for `drawdown_pct`
3. Used `getattr` with defaults so mock objects in tests don't break

**Acceptance criteria**:
- `drawdown_pct` > 0 in minute.csv after a losing fill
- `daily_loss_pct` > 0 in minute.csv when net daily PnL is negative
- Hard stop triggers correctly when loss exceeds `max_daily_loss_pct_hard`

**Do not**:
- Remove the equity-based computation — it correctly captures unrealized PnL when the paper engine works properly

---

### [P1-STRAT-20260312-1] Clean bot7 YAML dead config values `done (2026-03-12)`

**Why it matters**: the bot7 YAML contained 6 MM-only parameters (`min_net_edge_bps`, `edge_resume_bps`, `adaptive_params_enabled`, `adaptive_edge_relax_max_bps`, `adaptive_edge_tighten_max_bps`, `adaptive_min_edge_bps_floor`) silently overridden to 0/false by `DirectionalRuntimeConfig`, creating a false impression of active edge gating.

**What exists now**:
- `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml` — dead MM params removed
- Added comment: `# MM-only params (edge gate, adaptive spreads, governor) are disabled by DirectionalRuntimeConfig`

**Acceptance criteria**:
- Bot7 starts without errors
- No behavioral change

---

### [P1-STRAT-20260312-2] Paper engine perp PnL ledger settlement bug `done (2026-03-12)`

**Why it matters**: the paper engine's `PaperPortfolio._settle_ledger()` should debit fees and credit/debit realized PnL for perp fills, but the saved `paper_desk_v2.json` shows `balances: {"USDT": "5000"}` unchanged after 864 fills. This causes `equity_quote` to be stale, breaking all equity-derived metrics until the P0-STRAT-20260312-2 fallback was added.

**Root cause found**: when `PAPER_EXCHANGE_MODE=active`, orders are submitted to the external Paper Exchange Service via Redis (order IDs prefixed `pe-`), bypassing PaperDesk v2's matching engine entirely. Fill events return via `_consume_paper_exchange_events` and fire HB events, but `portfolio.settle_fill()` is never called. The PaperDesk v2 portfolio stays at its initial balance forever.

**Fix applied**: added `_sync_fill_to_portfolio()` helper in `hb_bridge.py` that settles external Paper Exchange fills into PaperDesk v2's portfolio. Called from both fill paths in `_consume_paper_exchange_events`:
- `submit_order` with status `partially_filled`/`filled`
- `order_fill`/`fill`/`fill_order` lifecycle events

**Files changed**:
- `controllers/paper_engine_v2/hb_bridge.py` — added `_sync_fill_to_portfolio()` + 2 call sites
- `tests/controllers/test_paper_engine_v2/test_portfolio.py` — 5 new perp settlement tests
- `tests/controllers/test_hb_bridge_signal_routing.py` — 4 new sync fill integration tests

**Acceptance criteria** (all met):
- After perp round-trip, `paper_desk_v2.json` `balances.USDT` < starting equity
- `equity_quote` reflects settled fees and PnL
- Full test suite passes (all non-integration tests green)
- P0-STRAT-20260312-2 defense-in-depth fallback remains in place

---

### [P0-TECH-20260312-1] Force-save state stores after fills (data loss prevention) `done (2026-03-12)`

**Why it matters**: both `DeskStateStore` and controller `DailyStateStore` used throttled saves (30s default) even after fill events, meaning a crash within 30s of a fill would lose accounting data (positions, realized PnL, balances).

**Changes**:
- `controllers/paper_engine_v2/desk.py`: detect fills in `tick()` events and pass `force=True` to `_state_store.save()`
- `controllers/fill_handler_mixin.py`: change `_save_daily_state()` to `_save_daily_state(force=True)` on fill processing

**Acceptance criteria** (all met):
- After any fill, both state stores persist immediately, bypassing throttle
- Full test suite passes

---

### [P1-TECH-20260312-1] Paper engine audit — sub-minute telemetry + state reconciliation `done (2026-03-12)`

**Why it matters**: dashboard equity/position/PnL data was up to 60s stale (published only at minute boundaries). Additionally, the two independent state stores (desk portfolio vs controller daily state) had no cross-validation on restore, allowing silent desynchronization.

**Changes**:
- `controllers/telemetry_mixin.py`: added sub-minute telemetry re-publish (10s default, configurable via `TELEMETRY_SUB_MINUTE_INTERVAL_S`) with live equity/PnL overlay from controller state
- `controllers/shared_mm_v24.py`: added `_maybe_reconcile_desk_state()` one-time check on first tick comparing desk portfolio position/avg_entry/realized_pnl with controller tracking, logging `STATE RECONCILIATION:` warnings on mismatch
- `controllers/daily_state_store.py`: `load()` now compares `ts_utc` between Redis and disk and picks the freshest; added debug log when background saves are dropped due to still-running thread

**Acceptance criteria** (all met):
- Dashboard data refreshes every 10s instead of 60s
- State desync between desk and controller is logged on startup
- Full test suite passes

---

### [P2-TECH-20260312-1] Paper portfolio equity_quote and mark_to_market accuracy fixes `done (2026-03-12)`

**Why it matters**: three accounting bugs in `PaperPortfolio` caused incorrect equity tracking: (1) `mark_to_market()` zeroed unrealized PnL when price was temporarily missing, losing position value; (2) `equity_quote()` without `mark_prices` returned cash-only, ignoring open positions; (3) peak equity tracking in `settle_fill()` and `apply_funding()` used cash-only equity.

**Changes**:
- `controllers/paper_engine_v2/portfolio.py` `mark_to_market()`: split condition — only zero unrealized PnL when position is flat, preserve existing values when price is missing
- `controllers/paper_engine_v2/portfolio.py` `equity_quote()`: always include unrealized PnL for perp positions (from mark_prices when provided, from stored `pos.unrealized_pnl` otherwise)
- Peak equity in `settle_fill()` and `apply_funding()` now reflects full equity (cash + unrealized PnL)

**Acceptance criteria** (all met):
- `equity_quote()` returns correct equity with or without `mark_prices`
- Peak equity tracks full equity, not just cash
- Full test suite passes (47 portfolio/desk tests)

---

### [P2-TECH-20260312-2] DailyStateStore freshest-source loading + dropped save logging `done (2026-03-12)`

**Why it matters**: `DailyStateStore.load()` always preferred Redis over disk regardless of timestamps, potentially restoring stale data when a crash interrupted a Redis write but the disk file had the latest forced save. Background save drops were silent.

**Changes**:
- `controllers/daily_state_store.py` `load()`: loads from both backends, compares `ts_utc`, returns freshest
- `controllers/daily_state_store.py` `save()`: logs at DEBUG level when a throttled save is dropped due to still-running background thread

**Acceptance criteria** (all met):
- On restore, the newer state source is always chosen
- Dropped saves appear in debug logs
- Full test suite passes

---

## Recently Completed (Moved to Archive)

The following completed tracks were removed from this active backlog and summarized in `hbot/docs/archive/BACKLOG_ARCHIVE_2026Q1.md`:
- BUILD_SPEC — Multi-Bot Desk Audit Follow-Up
- BUILD_SPEC — Canonical Data Plane Migration (Timescale)
- BUILD_SPEC — Pro Quality Upgrade Program (ARCH/TECH/PERF/FUNC)
- BUILD_SPEC — Semi-Pro Paper Exchange Service (exchange mirror)
- Legacy P0/P1/P2 + infra/tech-debt/code-quality execution tracks
- STRATEGY_LOOP — Iteration (2026-03-02)

---

## SERVICE REVIEW — Full-Stack Audit (2026-03-16)

> Goal: systematic code review of every service for bugs, logic errors, missing error
> handling, and robustness gaps. Findings prioritized by operational impact.

### Service Review Scorecard

| Service | Health | Critical | High | Medium | Low |
|---|---|---|---|---|---|
| kill_switch | 7/10 | 0 | 2 | 3 | 1 |
| event_store | 7/10 | 0 | 2 | 2 | 1 |
| coordination_service | 8/10 | 0 | 0 | 3 | 2 |
| reconciliation_service | 7/10 | 0 | 1 | 3 | 1 |
| paper_exchange_service | 6/10 | 0 | 3 | 2 | 0 |
| signal_service | 6/10 | 0 | 2 | 3 | 1 |
| risk_service | 8/10 | 0 | 0 | 2 | 0 |
| portfolio_risk_service | 7/10 | 0 | 1 | 2 | 1 |
| market_data_service | 7/10 | 0 | 1 | 3 | 1 |
| realtime_ui_api | 7/10 | 0 | 2 | 3 | 1 |
| telegram_bot | 8/10 | 0 | 0 | 2 | 2 |
| shadow_execution | 8/10 | 0 | 0 | 2 | 2 |
| portfolio_allocator | 8/10 | 0 | 1 | 1 | 0 |
| ops_db_writer | 7/10 | 0 | 1 | 2 | 0 |
| bot_watchdog | 6/10 | 2 | 1 | 1 | 0 |
| hb_bridge/redis_client | 7/10 | 1 | 0 | 1 | 1 |
| common/shared modules | 7/10 | 1 | 1 | 3 | 2 |
| controllers (core) | 7/10 | 0 | 2 | 4 | 3 |

### Top 30 Findings (Prioritized)

| # | Service | Severity | Finding | Effort |
|---|---|---|---|---|
| 1 | bot_watchdog | CRITICAL | `strftime("%H:%M timezone.utc")` produces literal text, not UTC — Telegram alerts have broken timestamps | S |
| 2 | bot_watchdog | CRITICAL | `_save_state()` crashes on first run — parent directory may not exist | S |
| 3 | hb_bridge/redis_client | CRITICAL | Reconnect backoff calculation result discarded (line 133) — reconnect loop never sleeps between retries | S |
| 4 | paper_exchange_service | HIGH | Fill deduplication check runs AFTER state mutation — replayed snapshots can double-count fills | M |
| 5 | paper_exchange_service | HIGH | Silent publish failure leaves partial state — fills applied to positions but events not published | M |
| 6 | paper_exchange_service | HIGH | Funding settlement committed before persistence — lost on crash, duplicate charges on restart | M |
| 7 | event_store | HIGH | DB connection never reconnects — once Postgres fails, all future DB writes silently skipped | M |
| 8 | event_store | HIGH | Stale DB connection after long idle — no ping before use, can hang on first query | S |
| 9 | signal_service | HIGH | Fake confidence scores when model lacks predict_proba — `abs(return) * 100` clamped to 1.0 | S |
| 10 | signal_service | HIGH | Model load failure silently downgrades to baseline — no alert or metric | S |
| 11 | kill_switch | HIGH | Race condition on `_kill_switch_state` dict — concurrent HTTP handler and main loop access | M |
| 12 | kill_switch | HIGH | Missing Redis reconnection — if Redis goes down after init, service loops silently forever | M |
| 13 | portfolio_risk_service | HIGH | Event store read unprotected — service crashes if event store is temporarily unavailable | S |
| 14 | controllers/daily_state_store | HIGH | Threading race on `_last_save_ts` — concurrent saves can corrupt persisted state | S |
| 15 | controllers/protective_stop | HIGH | Placement failure silently sets order_id=None — position becomes unprotected with no alert | S |
| 16 | market_data_service | HIGH | WS reconnect has no exponential backoff — fixed delay regardless of failure count | S |
| 17 | realtime_ui_api/state | HIGH | Dead code at line 513 — timeframe_ms calculation result discarded, never assigned | S |
| 18 | realtime_ui_api/stream_consumer | HIGH | ack() failure after process() — message processed but never acknowledged, data loss | S |
| 19 | bot_watchdog | HIGH | Backoff calculation computed but never applied — reconnect loop never actually sleeps | S |
| 20 | ops_db_writer | HIGH | `conn` may be undefined in finally block — `NameError` if `_connect()` throws | S |
| 21 | reconciliation_service | MEDIUM | Redis xadd has no error handling — service crashes if Redis unavailable during intent publish | S |
| 22 | portfolio_risk_service | MEDIUM | `gross_exposure_cap=0` silently skipped instead of treated as hard cap | S |
| 23 | portfolio_risk_service | MEDIUM | Synthetic breach not injected into scoped_bots — gate testing gives false confidence | M |
| 24 | signal_service | MEDIUM | Temp files from model downloads never cleaned — disk exhaustion over time | S |
| 25 | signal_service | MEDIUM | S3 URI "s3://bucket" (no key) crashes with ValueError — not caught | S |
| 26 | common/retry.py | MEDIUM | `assert last_exc is not None` used for flow control — disabled by `-O` flag | S |
| 27 | common/market_history_provider_impl | MEDIUM | DB connection leak — `conn` undefined if connect() throws, `NameError` in finally | S |
| 28 | controllers/order_sizer | MEDIUM | Division by zero edge case when `mid=0` — unguarded second division | S |
| 29 | controllers/fee_manager | MEDIUM | Cascading fallback hides error source — no structured error codes per stage | M |
| 30 | coordination_service | MEDIUM | Bare except on risk decision parsing — malformed events silently dropped without metrics | S |

---

### [P1-SVC-20260316-1] Fix bot_watchdog critical bugs `done (2026-03-17)`

**Why it matters**: Telegram alerts have broken timestamps (literal "timezone.utc" text) and state file save crashes on first run. Both are trivially fixable but affect every deployment.

**Implementation steps**:
1. Fix `strftime` format string to produce actual UTC indicator.
2. Ensure parent directory exists before `STATE_FILE.write_text()`.
3. Apply and store backoff calculation result in reconnect loop.

**Acceptance criteria**: Watchdog starts clean, timestamps show UTC, reconnect backs off exponentially.

---

### [P1-SVC-20260316-2] Fix redis_client reconnect backoff `done (2026-03-17)`

**Why it matters**: The exponential backoff calculation at line 133 is computed but never stored — reconnect loop retries immediately on every failure, creating a tight spin loop that floods Redis and wastes CPU.

**Implementation steps**:
1. Assign backoff result to a variable and `time.sleep(backoff)` before next reconnect attempt.

**Acceptance criteria**: Reconnect delay grows exponentially (1s, 2s, 4s, ..., 30s max).

---

### [P1-SVC-20260316-3] Fix paper_exchange_service fill deduplication ordering `done (2026-03-17)`

**Why it matters**: Fill candidates are deduplicated AFTER order state is already mutated. If a market snapshot is replayed, fills are double-counted in positions.

**Implementation steps**:
1. Move deduplication check before `_apply_fill_candidate()`.
2. Skip state mutations when `event_already_published` is true.
3. Add unit test for replay deduplication.

**Acceptance criteria**: Replayed market snapshots produce no duplicate fills.

---

### [P1-SVC-20260316-4] Add DB reconnection to event_store `done (2026-03-17)`

**Why it matters**: Once Postgres fails, all future DB writes silently skipped forever. No recovery without restart.

**Implementation steps**:
1. Add reconnection logic with exponential backoff in `_append_events_db()`.
2. Add `db_mirror_alive` field to stats report.
3. Validate connection with `SELECT 1` before batch write.

**Acceptance criteria**: DB mirror recovers within 60s of Postgres restart; stats show mirror health.

---

### [P1-SVC-20260316-5] Fix signal_service confidence scoring `done (2026-03-17)`

**Why it matters**: When ML model lacks `predict_proba`, confidence is set to `abs(return) * 100` clamped to 1.0. This creates fake high-confidence signals from arbitrary predictions.

**Implementation steps**:
1. Return 0.0 confidence when neither `predict_proba` nor `decision_function` is available.
2. Log explicitly when falling back to baseline signal logic.
3. Clean up temp files after model load.

**Acceptance criteria**: No false-confidence signals published; model fallback is visible in logs.

---

### [P1-SVC-20260316-6] Fix kill_switch thread safety `done (2026-03-17)`

**Why it matters**: `_kill_switch_state` dict accessed concurrently from HTTP handler thread and main loop without locking. Can cause corrupt state reads.

**Implementation steps**:
1. Add `threading.Lock` protecting `_kill_switch_state` reads and writes.
2. Add Redis health check to `/health` endpoint.

**Acceptance criteria**: No concurrent dict mutation; health endpoint reflects Redis connectivity.

---

### [P1-SVC-20260316-7] Fix controllers threading and stop placement `done (2026-03-17)`

**Why it matters**: DailyStateStore has race on `_last_save_ts`. ProtectiveStopManager silently loses stop orders on placement failure.

**Implementation steps**:
1. Add `threading.Lock` to DailyStateStore around `_last_save_ts` and `_bg_thread`.
2. Check `_join_pending_save()` return via `t.is_alive()` after join timeout.
3. In ProtectiveStopManager, retry `place_stop()` once on failure; log ERROR if both fail.

**Acceptance criteria**: No concurrent state corruption; failed stop placements retry once and log.

---

### [P2-SVC-20260316-8] Fix realtime_ui_api dead code and ack safety `done (2026-03-17)`

**Why it matters**: Timeframe calculation at state.py:513 is computed but never assigned. Stream consumer ack() failure causes data loss.

**Implementation steps**:
1. Assign `timeframe_ms = max(1, int(timeframe_s)) * 1000` and use it.
2. Wrap `ack()` in try-except in stream_consumer.py; track failed acks.

**Acceptance criteria**: Candle timeframes resolve correctly; ack failures logged and tracked.

---

### [P2-SVC-20260316-9] Fix ops_db_writer connection safety and portfolio_risk gaps `done (2026-03-17)`

**Why it matters**: NameError in finally block if connect() throws. Portfolio risk gross_exposure_cap=0 is silently skipped.

**Implementation steps**:
1. Initialize `conn = None` before try block; check `if conn` in finally.
2. Distinguish `gross_exposure_cap=0` (hard cap) from `None` (disabled).
3. Wrap event store reads in try-except with fallback to previous cycle.

**Acceptance criteria**: No NameError on connection failure; zero-cap triggers breach.

---

### [P2-SVC-20260316-10] Harden common modules `done (2026-03-17)`

**Why it matters**: retry.py uses `assert` for flow control (disabled by `-O`). market_history_provider_impl has DB connection leak. Fee provider silently swallows all errors.

**Implementation steps**:
1. Replace `assert last_exc is not None` with `raise RuntimeError(...)`.
2. Initialize `conn = None` in market_history_provider_impl; check before close.
3. Add WARNING log to fee_provider when API/connector fallback occurs.
4. Add `time.sleep(backoff)` to redis_client reconnect (if not already fixed by P1-SVC-20260316-2).

**Acceptance criteria**: No assert-based flow control; no connection leaks; fee fallbacks logged.

---

## STRATEGY REVIEW — Functional Logic Audit (2026-03-16)

> Full review of all bot strategies (bot1/5/6/7), shared MM layer, EPP core, and all mixins for logic bugs and functional correctness.

### Scorecard

| Component | Score | CRITICAL | HIGH | MEDIUM | LOW |
|---|---|---|---|---|---|
| fill_handler_mixin | 5/10 | 1 | 1 | 1 | 0 |
| auto_calibration_mixin | 6/10 | 1 | 0 | 0 | 0 |
| bot6/cvd_divergence_v1 | 6/10 | 0 | 2 | 3 | 0 |
| position_mixin | 7/10 | 0 | 1 | 0 | 0 |
| shared_mm_v24 / epp_v2_4 | 7/10 | 0 | 1 | 2 | 1 |
| bot7/adaptive_grid + pullback | 7/10 | 0 | 0 | 2 | 2 |
| bot5/ift_jota_v1 | 8/10 | 0 | 0 | 1 | 0 |
| bot1/baseline_v1 | 8/10 | 0 | 0 | 1 | 0 |
| telemetry_mixin | 8/10 | 0 | 0 | 0 | 1 |
| risk_mixin | 8/10 | 0 | 0 | 1 | 0 |
| position_recovery | 8/10 | 0 | 0 | 1 | 0 |

### Top Findings (Prioritized)

| # | Component | Severity | Finding |
|---|---|---|---|
| 1 | fill_handler_mixin | CRITICAL | HEDGE mode position tracking: long/short values overwritten by ONEWAY derivation logic (lines 368-442) — hedge positions silently corrupted |
| 2 | auto_calibration_mixin | CRITICAL | Missing `datetime` imports — `NameError` at runtime when auto-calibration triggers time-based logic |
| 3 | bot6/cvd_divergence_v1 | HIGH | CVD divergence denominator produces inverted signals when both perp and spot CVD have same sign — `abs(perp) + abs(spot)` denominator conflates magnitude with divergence |
| 4 | bot6/cvd_divergence_v1 | HIGH | Delta spike baseline uses only 5 trades — easily gamed or noisy, especially on low-volume pairs |
| 5 | shared_mm_v24 | HIGH | Negative effective minimum edge threshold possible (lines 3488-3568) — `edge_floor - fee_drag` can go negative, allowing negative-edge orders |
| 6 | position_mixin | HIGH | Position drift cascading to HARD_STOP after just 3 corrections in 1 hour (lines 247-255) — aggressive escalation on transient drift |
| 7 | fill_handler_mixin | HIGH | Fill dedup key collision risk for same-order partial fills (lines 78-92) — two partials with same order_id + price could collide |
| 8 | bot6/cvd_divergence_v1 | MEDIUM | z-score normalization missing entirely — raw CVD divergence used without statistical standardization |
| 9 | bot6/cvd_divergence_v1 | MEDIUM | Trend direction inference unreachable — `sma_fast <= _ZERO` condition never true for positive SMA |
| 10 | bot6/cvd_divergence_v1 | MEDIUM | Spot staleness doesn't block signal — stale spot data feeds into CVD calculation unchecked |
| 11 | shared_mm_v24 / epp_v2_4 | MEDIUM | Position reconciliation one-shot logic risk — reconciliation runs once and assumes success |
| 12 | shared_mm_v24 / epp_v2_4 | MEDIUM | Daily state reset race condition — force flush is background-threaded, not awaited |
| 13 | bot7/adaptive_grid + pullback | MEDIUM | Signal score denominator inconsistency: adaptive grid divides by 3, pullback by 4 — pullback systematically more conservative |
| 14 | bot7/adaptive_grid + pullback | MEDIUM | Zone floor validation missing — no check that grid zone boundaries stay positive |
| 15 | bot1/baseline_v1 | MEDIUM | Missing `min_base_pct < max_base_pct` validation — config inversion silently accepted |
| 16 | bot5/ift_jota_v1 | MEDIUM | Low_conviction flag minor inconsistency — threshold checks don't align with conviction weighting boundaries |
| 17 | risk_mixin | MEDIUM | Fee extraction silent fallback corrupts PnL — unrecognized fee structure defaults to zero fees |
| 18 | position_recovery | MEDIUM | Recovery assumes single exchange snapshot — multi-exchange deployments would overwrite positions |
| 19 | telemetry_mixin | LOW | NaN/inf propagation to telemetry — no sanitization before Prometheus export |
| 20 | bot7 | LOW | Absorption z-score uses float bridge for sqrt — precision loss on extreme values |
| 21 | shared_mm_v24 | LOW | Orphan order cleanup skipped if any active executor exists — stale orders accumulate |

---

### [P0-STRAT-20260316-1] Fix HEDGE mode position tracking in fill_handler_mixin `done (2026-03-17)`

**Why it matters**: In HEDGE mode, `_update_position_from_fill()` (lines 368-442) overwrites long/short position values using ONEWAY derivation logic. This silently corrupts hedge positions, making position tracking unreliable for any bot using hedge mode. The position data feeds into risk evaluation, PnL computation, and stop placement — all of which become wrong.

**Implementation steps**:
1. In `fill_handler_mixin.py:368-442`, add a branch for `PositionMode.HEDGE` that updates `long_qty`/`short_qty` independently based on fill side.
2. Preserve existing ONEWAY logic behind an `else` branch.
3. Add unit tests: HEDGE fill on long side only affects long_qty, short side only affects short_qty.

**Acceptance criteria**: Hedge-mode fills update the correct side without overwriting the other. All existing ONEWAY tests remain green.

---

### [P0-STRAT-20260316-2] Fix auto_calibration_mixin missing imports `done (2026-03-17)`

**Why it matters**: `auto_calibration_mixin.py` references `datetime` objects in time-based calibration logic but the import is missing. This causes a `NameError` at runtime when calibration triggers, crashing the strategy tick.

**Implementation steps**:
1. Add `from datetime import datetime, timezone` at the top of `auto_calibration_mixin.py`.
2. Verify all datetime references in the file resolve correctly.
3. Run existing auto_calibration tests.

**Acceptance criteria**: No `NameError` on calibration tick. Existing tests pass.

---

### [P1-STRAT-20260316-3] Fix CVD divergence denominator logic `done (2026-03-17)`

**Why it matters**: In `cvd_divergence_v1.py`, the divergence calculation uses `abs(perp_cvd) + abs(spot_cvd)` as the denominator. When both CVDs have the same sign (both positive or both negative), this denominator conflates magnitude with divergence direction, producing inverted signals. The strategy reads convergence as divergence.

**Implementation steps**:
1. Replace the denominator with `max(abs(perp_cvd), abs(spot_cvd))` or use a signed difference normalized by a rolling window baseline.
2. Add guard for denominator == 0.
3. Add unit test: same-sign CVDs produce near-zero divergence, not inflated values.

**Acceptance criteria**: Same-sign CVDs produce convergence signal (near 0), not false divergence. Opposite-sign CVDs produce meaningful divergence.

---

### [P1-STRAT-20260316-4] Fix delta spike baseline sample size `done (2026-03-17)`

**Why it matters**: Delta spike detection uses a baseline of only 5 trades. This is statistically unreliable — a single large trade can dominate the baseline and cause false spikes or missed real spikes. On low-volume pairs, 5 trades may represent minutes of activity.

**Implementation steps**:
1. Increase minimum baseline window to 20 trades (configurable).
2. Add staleness check: if baseline window covers < 30 seconds, extend or skip spike detection.
3. Add unit test for baseline stability under varying trade frequencies.

**Acceptance criteria**: Baseline requires >= 20 trades. Spike detection disabled when baseline is insufficient.

---

### [P1-STRAT-20260316-5] Fix negative effective edge floor in shared_mm `done (2026-03-17)`

**Why it matters**: In `shared_mm_v24.py:3488-3568`, the effective minimum edge is `edge_floor - fee_drag`. When fee drag exceeds the configured edge floor, the effective floor goes negative, allowing orders to be placed at a guaranteed loss. This directly erodes PnL.

**Implementation steps**:
1. Add `effective_edge = max(0, edge_floor - fee_drag)` — never allow negative floor.
2. Log WARNING when fee drag exceeds edge floor.
3. Add unit test: high fee scenario clamps effective edge to 0, not negative.

**Acceptance criteria**: Effective edge floor is always >= 0. Warning logged when fee drag dominates.

---

### [P1-STRAT-20260316-6] Reduce position drift escalation aggressiveness `done (2026-03-17)`

**Why it matters**: In `position_mixin.py:247-255`, position drift correction escalates to HARD_STOP after just 3 corrections within 1 hour. Transient drift from normal market-making activity can trigger this, causing unnecessary full flattening and fee drag.

**Implementation steps**:
1. Increase correction count threshold from 3 to 5 before HARD_STOP escalation.
2. Add a cooldown period (15 min) after each correction before counting the next one.
3. Add config parameters: `drift_escalation_count` and `drift_escalation_cooldown_s`.
4. Add unit tests for escalation with and without cooldown.

**Acceptance criteria**: Transient drift (< 5 corrections in 1 hour) does not trigger HARD_STOP. Persistent drift still escalates correctly.

---

### [P1-STRAT-20260316-7] Fix fill dedup key collision for partial fills `done (2026-03-17)`

**Why it matters**: In `fill_handler_mixin.py:78-92`, the deduplication key is `(order_id, price)`. Two partial fills on the same order at the same price produce identical keys, causing the second partial to be silently dropped. This understates realized position and PnL.

**Implementation steps**:
1. Add `fill_qty` or a monotonic sequence number to the dedup key: `(order_id, price, qty)` or `(order_id, fill_seq)`.
2. Add unit test: two partial fills at same price on same order are both processed.

**Acceptance criteria**: Partial fills at same price are not deduplicated. Exact duplicate replays are still caught.

---

### [P2-STRAT-20260316-8] Add z-score normalization to CVD divergence `done (2026-03-17)`

**Why it matters**: Raw CVD divergence values are used without statistical standardization. This means the signal magnitude is pair-dependent and volume-dependent, making threshold tuning fragile across different instruments.

**Implementation steps**:
1. Add rolling z-score normalization over a configurable window (e.g., 100 ticks).
2. Replace raw divergence thresholds with z-score thresholds (e.g., |z| > 2.0).
3. Add unit tests for z-score calculation and threshold crossing.

**Acceptance criteria**: Divergence signal is z-score normalized. Existing config thresholds updated to z-score equivalents.

---

### [P2-STRAT-20260316-9] Fix bot6 spot staleness and trend inference `done (2026-03-17)`

**Why it matters**: Stale spot data feeds into CVD calculation unchecked — if spot WS disconnects, the strategy trades on frozen data. Separately, the trend direction inference branch (`sma_fast <= _ZERO`) is unreachable for positive SMA values, meaning trend filtering is partially dead code.

**Implementation steps**:
1. Add spot price staleness check (same as perp): skip signal if spot age > `max_staleness_s`.
2. Fix trend condition: use `sma_fast < sma_slow` for bearish, `sma_fast > sma_slow` for bullish.
3. Add unit tests for stale spot rejection and corrected trend classification.

**Acceptance criteria**: Stale spot data blocks signal generation. Trend inference covers both bullish and bearish cases.

---

### [P2-STRAT-20260316-10] Fix daily state reset race and reconciliation one-shot `done (2026-03-17)`

**Why it matters**: Daily state reset's force flush runs in a background thread without being awaited — subsequent ticks can read stale pre-reset state. Position reconciliation runs once at startup and assumes success — if it fails (e.g., exchange timeout), the bot runs with stale positions for the entire session.

**Implementation steps**:
1. In `daily_state_store.py`, await the background flush thread (join with timeout) before returning from reset.
2. In position reconciliation, add retry with exponential backoff (max 3 attempts) on startup.
3. Log ERROR and enter SOFT_PAUSE if reconciliation fails after retries.

**Acceptance criteria**: State reset is durable before next tick reads. Reconciliation retries on failure; bot pauses if unresolvable.

---

### [P2-STRAT-20260316-11] Miscellaneous strategy quality fixes `done (2026-03-17)`

**Why it matters**: Collection of lower-severity issues across multiple components.

**Implementation steps**:
1. **bot7 signal denominator**: Align pullback denominator from /4 to /3 to match adaptive grid, or document the intentional asymmetry.
2. **bot7 zone floor**: Add `max(0, zone_boundary)` guard for grid zone calculations.
3. **bot1 config validation**: Add `assert min_base_pct < max_base_pct` in config load.
4. **telemetry NaN guard**: Add `math.isfinite()` check before Prometheus gauge set.
5. **risk_mixin fee fallback**: Log WARNING when fee extraction falls back to zero.
6. **orphan order cleanup**: Run cleanup pass even when active executors exist, filtering by executor age.

**Acceptance criteria**: Each sub-item has a targeted unit test. No behavioral regressions.

---

## INITIAL AUDIT — Semi-Pro Hardening (2026-03-17)

> 6-loop initial audit (frontend, ops, performance, quant, strategy, tech) establishing baseline and identifying all gaps required to reach semi-professional trading desk level.
> Audit date: 2026-03-17. All entries below are new gaps not already covered by existing backlog items above.

---

### Audit Health Summary

| Loop | Score | Headline |
|---|---|---|
| Frontend | 6.2 / 10 | Solid foundation; accessibility gap; store needs selectors; transport hook monolith |
| Ops | 7.0 / 10 | Good playbooks + alerting; no dashboards in VCS; JSONL growth unverified; memory limits missing |
| Performance | 6.0 / 10 | Sync I/O on hot path; JSONL disk growth; large monolith files; no profiling baseline |
| Quant | Low confidence | All bots frozen or lacking data; ROAD-1 and ROAD-5 both FAIL; bot1 in no_trade mode |
| Strategy | Cannot score | No trade data (no_trade=true); code architecture sound but untested by real fills |
| Tech | 6.5 / 10 | 132 test files but no coverage measured; 13 files > 600 lines; god class on hot path |

---

## P0 — Blocks Strategy Assessment

### [P0-QUANT-20260317-1] Enable bot1 paper trading to unblock strategy assessment `done (2026-03-17)`

**Why it matters**: Bot1 config has `no_trade: true`. Zero fills are generated. ROAD-1 (20-day paper edge) and ROAD-5 (4-week testnet) cannot progress. The quant loop, strategy loop, and promotion gates are all blocked on this single flag. Without trade data, no strategy viability assessment is possible.

**What exists now**:
- `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml` — `no_trade: true`, `total_amount_quote: 140`
- `reports/strategy/multi_day_summary_latest.json` — 15 days coverage, Sharpe FAIL
- Bot1 is paper-only (`BOT_MODE=paper` in compose)

**Design decision (pre-answered)**: Set `no_trade: false` for a bounded 48h experiment. Keep all other parameters unchanged. Collect baseline metrics before making any tuning changes.

**Implementation steps**:
1. In `hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml`, set `no_trade: false`.
2. Restart bot1 container: `docker compose --env-file ../env/.env -f docker-compose.yml up -d --no-deps --force-recreate bot1`.
3. Monitor for 48h: fills.csv, minute.csv, desk_snapshot.
4. After 48h, collect: fill count, PnL/fill, maker ratio, soft-pause ratio, max drawdown, governor mult avg.

**Acceptance criteria**:
- Bot generates fills for 48h without freeze or crash.
- Baseline metrics collected in fills.csv and minute.csv.
- Data sufficient for next quant/strategy loop iteration.

**Do not**:
- Change strategy parameters (spreads, sizing, regime) in the same experiment.
- Enable live (non-paper) trading.
- Skip the 48h window — partial data is insufficient for assessment.

---

## P1 — PnL / Reliability / Ops Hardening

### [P1-OPS-20260317-1] Version-control Grafana dashboards `done (2026-03-17)`

**Why it matters**: No Grafana dashboard JSON files are committed to the repo (`hbot/infra/monitoring/grafana/dashboards/` is empty). A Grafana wipe, container rebuild, or migration loses all dashboard definitions. The ops loop cannot audit panel correctness without version-controlled definitions. This is the single largest observability gap.

**What exists now**:
- `hbot/infra/monitoring/grafana/dashboards/` — no JSON files committed
- Dashboards exist only in the live Grafana instance (if any)
- `hbot/infra/monitoring/grafana/provisioning/datasources/datasource.yml` — datasource provisioning exists

**Design decision (pre-answered)**: Export all current Grafana dashboards as provisioned JSON files. Configure Grafana to auto-load from a provisioned dashboards directory mounted as a volume.

**Implementation steps**:
1. Export dashboards from Grafana API: `curl -s http://localhost:3000/api/search | jq -r '.[].uid'` then `curl -s http://localhost:3000/api/dashboards/uid/<uid> | jq '.dashboard' > hbot/infra/monitoring/grafana/dashboards/<name>.json`.
2. If no Grafana instance is running, create a minimum viable dashboard JSON with panels for: bot state, PnL, fills, governor mult, soft-pause ratio, container health, Redis memory.
3. Create `hbot/infra/monitoring/grafana/provisioning/dashboards/default.yml` pointing to `/etc/grafana/dashboards/`.
4. Mount `hbot/infra/monitoring/grafana/dashboards/` in docker-compose volume for Grafana.
5. Restart Grafana, verify dashboards load on fresh start.

**Acceptance criteria**:
- At least 1 dashboard JSON committed to `hbot/infra/monitoring/grafana/dashboards/`.
- Grafana loads provisioned dashboards on fresh container start.
- `git diff` shows new dashboard files.

**Do not**:
- Delete live dashboards before confirming export is complete.
- Create dashboards that reference metrics not yet scraped by Prometheus.

---

### [P1-OPS-20260317-2] Verify and enforce JSONL desk_events retention `done (2026-03-17)`

**Why it matters**: `desk_events_*.jsonl` files are growing 100-127 MB/day at peak. The artifact retention policy specifies 14-day retention for event_store, but enforcement has not been verified. At current rates, 2 weeks of data is ~1-2 GB. Without active pruning, disk fills in weeks.

**What exists now**:
- `hbot/config/artifact_retention_policy.json` — 14-day retention for event_store
- `artifact-retention` service exists in docker-compose
- `hbot/data/bot1/logs/epp_v24/bot1_a/desk_events_20260308.jsonl` — 111.6 MB (9 days old)
- `hbot/data/bot1/logs/epp_v24/bot1_a/desk_events_20260311.jsonl` — 126.7 MB (6 days old)

**Design decision (pre-answered)**: Verify the artifact-retention service is running and correctly deleting files older than 14 days. If not, debug the retention logic.

**Implementation steps**:
1. Check artifact-retention container is running: `docker ps --filter name=artifact-retention`.
2. Check container logs for recent retention runs: `docker logs kzay-capital-artifact-retention --tail 50`.
3. List desk_events files sorted by date; verify no files older than 14 days exist.
4. If retention is not running, check `hbot/scripts/ops/artifact_retention.py` for the sweep logic.
5. Add a daily disk usage metric to the ops report.

**Acceptance criteria**:
- No `desk_events_*.jsonl` files older than 14 days in `hbot/data/bot1/logs/`.
- Artifact-retention service logs show successful sweep runs.
- Disk growth rate stabilizes.

**Do not**:
- Delete files manually without verifying the retention service works.
- Reduce retention below 14 days without updating the policy JSON.

---

### [P1-OPS-20260317-3] Set memory limits on all control-plane services `done (2026-03-17)`

**Why it matters**: Without memory limits, a single leaking service can OOM the host and cascade-kill all 35+ containers. Only 6 services currently have limits. A semi-pro desk must have resource isolation.

**What exists now**:
- Memory limits set: bot1 (1G), redis (2G), postgres (512M), prometheus (512M), realtime-ui-api (512M), realtime-ui-web (64M)
- Missing on: paper-exchange-service, signal-service, risk-service, coordination-service, event-store-service, market-data-service, reconciliation-service, kill-switch, telegram-bot, ops-db-writer, bot-watchdog, desk-snapshot-service, shadow-parity-service, portfolio-risk-service, portfolio-allocator-service, bot-metrics-exporter, control-plane-metrics-exporter, alertmanager, alert-webhook-sink

**Design decision (pre-answered)**: Add `mem_limit` and `mem_reservation` to every service. Start conservative: 128M for lightweight (webhook-sink, desk-snapshot), 256M for medium (signal, risk, coordination, watchdog, telegram, metrics exporters), 512M for heavy (paper-exchange, ops-db-writer, reconciliation, event-store, market-data, shadow-parity, portfolio services), 128M for alertmanager.

**Implementation steps**:
1. Add `mem_limit` and `mem_reservation` to every service in `hbot/infra/compose/docker-compose.yml`.
2. Validate: `docker compose --env-file ../env/.env -f docker-compose.yml config > /dev/null`.
3. Restart stack, monitor with `docker stats` for 1h to confirm no OOM kills.
4. Tune limits based on observed RSS.

**Acceptance criteria**:
- All services have explicit `mem_limit` in docker-compose.yml.
- No service OOM-killed under normal 1h load.
- `docker compose config` validates without errors.

**Do not**:
- Set limits too tight initially — start at 2x observed RSS and tune down.
- Remove existing limits on services that already have them.

---

### [P1-OPS-20260317-4] Add Redis stream MAXLEN to prevent unbounded growth `done (2026-03-17)`

**Why it matters**: Redis is configured with `noeviction` policy. Streams without MAXLEN grow unbounded, eventually consuming all 2G of Redis memory. When Redis hits `maxmemory`, all writes fail and the entire event bus stops. A semi-pro desk needs bounded streams.

**What exists now**:
- Redis: `maxmemory` set, `noeviction` policy, AOF persistence
- No MAXLEN visible in stream XADD calls or compose configuration
- Key streams: `hb.signal.v1`, `hb.execution_intent.v1`, `hb.market_data.v1`, `hb.market_depth.v1`, `hb.audit.v1`

**Design decision (pre-answered)**: Add approximate MAXLEN trimming (`MAXLEN ~ N`) to all XADD calls. Use 100,000 entries for high-volume streams (market data, depth), 50,000 for medium (signals, intents, audit). Expose via `REDIS_STREAM_MAXLEN` environment variable.

**Implementation steps**:
1. Audit all `XADD` calls across `hbot/services/` — search for `xadd` in all Python files.
2. Add `maxlen` parameter with approximate trimming to each XADD call.
3. Add `REDIS_STREAM_MAXLEN` and `REDIS_STREAM_MAXLEN_DEPTH` env vars to `.env.template` with defaults.
4. Add stream depth to periodic health check output.

**Acceptance criteria**:
- `XLEN` on all streams stays below configured limit.
- No data loss for active consumers (consumer lag < maxlen).
- New env vars documented in `.env.template`.

**Do not**:
- Set MAXLEN too low — must exceed consumer lag + safety buffer.
- Use exact trimming (without `~`) as it is O(N) per write.

---

### [P1-OPS-20260317-5] Validate Telegram alerting end-to-end `done (2026-03-17)`

**Why it matters**: Telegram is the primary alerting channel for the desk operator. `OPS-PREREQ-1` has been blocked since 2026-03-08. If Telegram is broken, critical alerts (kill switch, container down, drawdown breach) are silently lost. A semi-pro desk must have confirmed alert delivery.

**What exists now**:
- `hbot/services/telegram_bot/main.py` — 676-line Telegram service
- `hbot/infra/monitoring/alertmanager/webhook_sink.py` — forwards alerts to Telegram
- `OPS-PREREQ-1` — blocked, `reports/ops/telegram_validation_latest.json` not fresh
- Alertmanager routes critical/warning to webhook_sink

**Design decision (pre-answered)**: Run the Telegram validation script, confirm delivery, and unblock OPS-PREREQ-1.

**Implementation steps**:
1. Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`.
2. Send test message: `python hbot/scripts/ops/validate_telegram.py` (or equivalent).
3. Confirm message received on Telegram.
4. Generate fresh `reports/ops/telegram_validation_latest.json`.
5. Update OPS-PREREQ-1 status to `done`.

**Acceptance criteria**:
- Test message received on Telegram with correct formatting.
- `telegram_validation_latest.json` has fresh timestamp and `pass: true`.
- OPS-PREREQ-1 unblocked.

**Do not**:
- Mark as done without actually receiving the test message.
- Store bot token in code — keep in `.env` only.

---

### [P1-TECH-20260317-1] Measure and establish test coverage baseline `done (2026-03-17)`

**Why it matters**: 132 test files exist, but no coverage percentage has been measured. Without a baseline, under-tested modules (risk rules, fill handling, kill switch logic) cannot be identified. A semi-pro desk needs evidence that critical code paths are tested.

**What exists now**:
- `pytest-cov` in requirements
- `hbot/tests/` — 132 files, ~1,000+ tests
- No coverage report artifact exists
- Coverage command documented in rules: `PYTHONPATH=hbot python -m pytest hbot/tests/ --cov=hbot --cov-report=term-missing --ignore=hbot/tests/integration`

**Design decision (pre-answered)**: Run coverage, save report, identify modules below 50%, prioritize critical paths.

**Implementation steps**:
1. Run: `PYTHONPATH=hbot python -m pytest hbot/tests/ --cov=hbot --cov-report=term-missing --cov-report=json:hbot/reports/verification/coverage_baseline.json --ignore=hbot/tests/integration -q`.
2. Record overall % and per-module %.
3. Identify top 5 under-tested modules by criticality (risk > fill handling > paper engine > services).
4. Add coverage run to weekly ops checklist.

**Acceptance criteria**:
- `reports/verification/coverage_baseline.json` exists with per-file coverage data.
- Overall coverage % documented.
- Top 5 under-tested critical modules identified with specific test gaps.

**Do not**:
- Require 100% coverage — focus on critical financial/risk paths.
- Add low-value tests just to inflate coverage number.

---

### [P1-TECH-20260317-2] Automated dependency CVE scanning `done (2026-03-17)`

**Why it matters**: Python runtime deps include `ccxt` (fast-moving exchange library), `redis`, `psycopg`, `requests`, `boto3`, and `scikit-learn`. No automated vulnerability scanning exists. A single CVE in a dependency used in the hot path (e.g., `orjson` deserialization, `redis` client) could be exploited via crafted exchange payloads. Semi-pro desks must know their exposure.

**What exists now**:
- `hbot/infra/compose/images/control_plane/requirements-control-plane.txt` — 15 pinned dependencies
- No `pip-audit`, `safety`, or CI CVE scan configured
- Frontend: `npm audit` not run regularly

**Design decision (pre-answered)**: Add `pip-audit` to the release script pipeline. Run `npm audit` as part of frontend build verification. Store reports.

**Implementation steps**:
1. Add `pip-audit` to requirements: `pip install pip-audit`.
2. Add to `run_strict_promotion_cycle.py`: `pip-audit -r infra/compose/images/control_plane/requirements-control-plane.txt --output json > reports/verification/pip_audit_latest.json`.
3. Fail promotion if any HIGH/CRITICAL CVE is found.
4. Add `npm audit --json > reports/verification/npm_audit_latest.json` to frontend build step.
5. Add both audit reports to weekly ops checklist.

**Acceptance criteria**:
- `reports/verification/pip_audit_latest.json` generated on every promotion cycle.
- `reports/verification/npm_audit_latest.json` generated on every frontend build.
- HIGH/CRITICAL CVEs block promotion.

**Do not**:
- Block on LOW/MODERATE CVEs unless they are in hot-path code.
- Skip `ccxt` — it processes exchange payloads directly.

---

### [P1-TECH-20260317-3] Plan shared_mm_v24.py decomposition `done (2026-03-17)`

**Why it matters**: `shared_mm_v24.py` is 4,058 lines — the largest file in the system and the entire tick hot path. It combines tick orchestration, level sizing, regime resolution, risk evaluation, order management, and lifecycle hooks in a single class with 5 mixins (~2,700 additional lines). Any exception in this file stops the bot. This is the highest structural risk in the codebase and must be addressed to reach semi-pro code health.

**What exists now**:
- `hbot/controllers/shared_mm_v24.py` — 4,058 lines, `SharedRuntimeKernel` class
- 5 mixins: `FillHandlerMixin` (525), `RiskMixin` (563), `TelemetryMixin` (758), `AutoCalibrationMixin` (353), `PositionMixin` (507)
- MRO: 6+ classes in the resolution chain

**Design decision (pre-answered)**: Create a decomposition plan (not the decomposition itself). Identify natural seams: tick orchestration, level computation, risk evaluation, order management, lifecycle. Map each method to a target module. Validate with strategy isolation contract tests.

**Implementation steps**:
1. Generate method inventory: list all public/private methods with line ranges and call relationships.
2. Identify natural seams based on method clusters and data flow.
3. Propose target modules with dependency diagram.
4. Estimate migration risk per seam (which methods have the most cross-cutting state access).
5. Write the plan as `hbot/docs/architecture/shared_mm_decomposition_plan.md`.

**Acceptance criteria**:
- Decomposition plan document exists with method→module mapping.
- Dependency diagram shows no circular imports in proposed structure.
- Risk assessment per migration phase included.

**Do not**:
- Start decomposing without the plan.
- Change behavior — this is a structural refactoring plan, not a logic change.
- Rush the decomposition — plan first, execute in multiple bounded PRs.

---

### [P1-PERF-20260317-1] Move tick_emitter CSV write to background thread `done (2026-03-17)`

**Why it matters**: `tick_emitter.py` (361 lines) writes to CSV synchronously on every tick (~1/second). This is a blocking file I/O call on the async event loop hot path. At 86,400 writes/day, this adds cumulative latency to every tick. Semi-pro performance requires non-blocking I/O on the critical path.

**What exists now**:
- `hbot/controllers/tick_emitter.py` — `_emit_tick_output()` method writes CSV synchronously
- Tick loop runs ~1/second
- minute.csv is 18.4 MB and growing

**Design decision (pre-answered)**: Use `asyncio.to_thread()` to offload CSV write to a thread pool. Add a bounded queue (maxsize=100) as backpressure. Flush queue on stop/shutdown.

**Implementation steps**:
1. In `tick_emitter.py`, wrap CSV write call with `asyncio.to_thread()` or use a dedicated `ThreadPoolExecutor`.
2. Add bounded queue (maxsize=100) between tick loop and writer thread.
3. On queue full, log WARNING and drop oldest entry (minute data, not fills).
4. Add flush-on-shutdown to ensure no data loss on clean stop.
5. Add test for queue overflow behavior.

**Acceptance criteria**:
- Tick loop no longer blocks on file I/O.
- CSV files remain correct and complete under normal load.
- Shutdown flushes all pending writes.

**Do not**:
- Remove the CSV write — it's needed for analysis and strategy loops.
- Use unbounded queue — set max size to prevent memory growth.

---

### [P1-PERF-20260317-2] Profile tick loop hot path with py-spy `done (2026-03-17)`

**Why it matters**: No profiling data exists for the tick loop. Without evidence, optimization is guesswork. The tick path traverses 4,058 lines of `shared_mm_v24.py` plus 5 mixins, spread engine, regime detector, risk evaluator, paper engine matching, and CSV write. Identifying the actual bottleneck is prerequisite for any performance improvement.

**What exists now**:
- Tick loop runs ~1/second in bot1
- No profiling data, no flame graphs, no latency breakdown
- `hbot/reports/verification/paper_exchange_perf_regression_latest.json` — perf regression gate exists but focuses on paper exchange, not tick loop

**Design decision (pre-answered)**: Use py-spy to sample the bot1 process for 10 minutes under normal load. Generate flame graph and top-functions report. Identify top 5 functions by wall time.

**Implementation steps**:
1. Install `py-spy` in the bot1 container or on host.
2. Attach to running bot1 process: `py-spy record -o hbot/reports/verification/tick_loop_profile.svg --pid <PID> --duration 600`.
3. Generate top-functions report: `py-spy top --pid <PID> --duration 600 > hbot/reports/verification/tick_loop_top.txt`.
4. Analyze: which functions dominate? Is it computation, I/O, or waiting?
5. Document baseline in `hbot/reports/verification/tick_loop_profile_baseline.md`.

**Acceptance criteria**:
- Flame graph and top-functions report generated.
- Top 5 functions by wall time identified.
- Baseline documented for future comparison.

**Do not**:
- Profile with debug logging enabled — use production log level.
- Optimize before measuring — this is measurement only.

---

### [P1-PERF-20260317-3] Bound paper portfolio fill history `done (2026-03-17)`

**Why it matters**: `paper_engine_v2/portfolio.py` (949 lines) maintains fill history for PnL computation. If fill history grows unbounded, memory usage increases monotonically over multi-day runs. A bot running continuously for weeks would accumulate hundreds of thousands of fill records.

**What exists now**:
- `hbot/controllers/paper_engine_v2/portfolio.py` — `PaperPortfolio`, `MultiAssetLedger`
- Fill history used for realized PnL computation
- No evidence of max-size cap on fill history lists

**Design decision (pre-answered)**: Add a rolling window cap on in-memory fill history (e.g., last 10,000 fills). Archive older fills to the JSONL event log. Ensure realized PnL computation remains correct by maintaining running totals.

**Implementation steps**:
1. Audit `portfolio.py` for all lists/dicts that grow with fill count.
2. Add `MAX_FILL_HISTORY` constant (default 10,000).
3. Trim oldest entries when cap is exceeded, preserving running PnL totals.
4. Add test: portfolio with 15,000 fills maintains correct PnL and bounded memory.

**Acceptance criteria**:
- Fill history capped at configured maximum.
- Realized PnL remains correct after trimming.
- Memory RSS of paper-exchange service stabilizes over 24h.

**Do not**:
- Discard fills without preserving their contribution to running PnL totals.
- Set cap too low — 10,000 fills covers ~1 week of active trading.

---

### [P1-FRONT-20260317-1] Add persistent disconnected/stale data visual indicators `done (2026-03-17)`

**Why it matters**: The operator must see within 2 seconds if data is stale or the WebSocket connection is lost. The store tracks `ConnectionState` and `DataFreshnessState`, but these are not consistently surfaced on data panels. A stale dashboard that looks healthy is the most dangerous failure mode for a trading desk operator.

**What exists now**:
- `ConnectionState` in store: `idle`, `connecting`, `connected`, `reconnecting`, `error`, `closed`
- `DataFreshnessState`: `marketTsMs`, `depthTsMs`, `positionTsMs`, `ordersTsMs`, `fillsTsMs`
- `STATE_REFRESH_STALE_AFTER_MS` constant defined
- `AlertsStrip` shows alerts but connection status not always prominent

**Design decision (pre-answered)**: Add a `ConnectionBadge` component to TopBar showing connection status with color (green/yellow/red). Add a translucent "STALE" overlay on data panels when their freshness timestamp exceeds `STATE_REFRESH_STALE_AFTER_MS`.

**Implementation steps**:
1. Create `ConnectionBadge.tsx`: green dot + "Connected" / yellow + "Reconnecting..." / red + "Disconnected".
2. Add to `TopBar.tsx` next to instance selector.
3. In `Panel.tsx`, accept optional `freshnessTsMs` prop; render "STALE" overlay when `Date.now() - freshnessTsMs > STATE_REFRESH_STALE_AFTER_MS`.
4. Wire `freshnessTsMs` to each data panel: MarketChartPanel → `marketTsMs`, FillsPanel → `fillsTsMs`, OrdersPanel → `ordersTsMs`, PositionExposurePanel → `positionTsMs`.
5. Add tests: badge renders correct state for each ConnectionStatus value.

**Acceptance criteria**:
- Disconnecting WS shows "Reconnecting..." badge immediately.
- Stale data shows visible overlay within `STATE_REFRESH_STALE_AFTER_MS`.
- Badge and overlay persist until data is fresh again.

**Do not**:
- Hide the indicator after a timeout — it must persist until recovery.
- Use color alone — include text label for accessibility.

---

### [P1-FRONT-20260317-2] Run npm audit and remediate vulnerabilities `done (2026-03-17)`

**Why it matters**: The frontend ships to operator browsers. A dependency vulnerability (XSS in a UI library, prototype pollution in a utility) could be exploited if the dashboard is exposed on a network. No evidence of a recent `npm audit` run exists.

**What exists now**:
- `hbot/apps/realtime_ui_v2/package.json` — 6 runtime deps, 17 dev deps
- `package-lock.json` exists
- No audit report in repo

**Design decision (pre-answered)**: Run `npm audit`, save report, remediate HIGH/CRITICAL findings.

**Implementation steps**:
1. Run: `cd hbot/apps/realtime_ui_v2 && npm audit --json > ../../reports/verification/npm_audit_latest.json`.
2. Review findings: remediate HIGH/CRITICAL with `npm audit fix` or manual updates.
3. For non-fixable: document risk and mitigation in report.
4. Add `npm audit` to frontend build script.

**Acceptance criteria**:
- `reports/verification/npm_audit_latest.json` exists with current date.
- No HIGH/CRITICAL vulnerabilities in shipped runtime dependencies.

**Do not**:
- Run `npm audit fix --force` without reviewing breaking changes.
- Ignore vulnerabilities in dev deps that run during build (Vite plugins, ESLint).

---

### [P1-QUANT-20260317-1] Review and simplify bot7 parameter count `done (2026-03-17)`

**Why it matters**: Bot7 (`pullback_v1.py`) is 1,968 lines with 10+ tunable signal parameters (BB period, RSI thresholds, ADX range, pullback zone %, absorption z-score, delta trap). Each parameter multiplies the optimization search space and overfitting risk. A strategy with more parameters than it can validate is structurally fragile.

**What exists now**:
- `hbot/controllers/bots/bot7/pullback_v1.py` — 1,968 lines
- Parameters: `pb_bb_period`, `pb_rsi_long_min`, `pb_rsi_long_max`, `pb_rsi_short_min`, `pb_rsi_short_max`, `pb_adx_min`, `pb_adx_max`, `pb_pullback_zone_pct`, `pb_absorption_z_threshold`, `pb_delta_trap_threshold`, plus TP/SL/time_limit
- Recent experiments: EXP-20260311-02 through EXP-20260312-01

**Design decision (pre-answered)**: Audit each parameter for marginal contribution. Identify parameters that can be derived from others or fixed without loss. Target: reduce to 6-7 independent parameters. Document the analysis.

**Implementation steps**:
1. List all tunable parameters with current values and sensitivity (how much does PnL change when the param moves 20%?).
2. Identify correlated parameters (e.g., RSI min/max can be reduced to a single "RSI zone width").
3. Identify parameters with negligible marginal contribution — fix at default.
4. Propose simplified parameter set in experiment ledger.
5. Run bounded A/B: simplified (fewer params) vs current, 48h each.

**Acceptance criteria**:
- Parameter audit document in experiment ledger.
- Simplified variant identified with <= 7 independent parameters.
- A/B experiment plan defined with success/failure criteria.

**Do not**:
- Remove parameters that are core to the thesis (BB, RSI, pullback zone).
- Deploy simplified version without A/B evidence.

---

### [P1-QUANT-20260317-2] Calibrate paper fill model against exchange evidence `done (2026-03-17)`

**Why it matters**: Paper engine has 3 fill models (`QueuePositionFillModel`, `TopOfBookFillModel`, `LatencyAwareFillModel`) but calibration against real exchange fills is unknown. If the paper model flatters fills (faster queue advancement, less adverse selection, no partial-fill degradation), all strategy assessment is biased upward. ROAD-5 requires slippage < 2 bps vs paper — this needs a baseline measurement.

**What exists now**:
- `hbot/controllers/paper_engine_v2/fill_models.py` — 618 lines, 3 models
- `hbot/controllers/paper_engine_v2/adverse_inference.py` — 144 lines
- `hbot/controllers/paper_engine_v2/latency_model.py` — 80 lines
- No calibration report exists

**Design decision (pre-answered)**: Compare paper fills against testnet fills (when ROAD-5 provides data). In the meantime, document the theoretical parity gaps and assign conservative discount factors.

**Implementation steps**:
1. Document current fill model assumptions: queue position formula, adverse selection parameters, latency distribution.
2. Estimate parity discount: what % of paper PnL would survive under pessimistic assumptions (50% worse queue position, 2x adverse selection, 50ms additional latency)?
3. Record analysis in `hbot/docs/strategy/paper_parity_calibration.md`.
4. When ROAD-5 testnet data is available: compute actual paper-vs-live fill comparison.

**Acceptance criteria**:
- Paper parity calibration document exists with quantified discount factors.
- ROAD-5 acceptance criteria reference this calibration.

**Do not**:
- Claim paper PnL equals live PnL without calibration evidence.
- Adjust fill model parameters without documented justification.

---

## P2 — Quality / Maintainability / Semi-Pro Polish

### [P2-OPS-20260317-1] Audit and fix restart policies in docker-compose `done (2026-03-17)`

**Why it matters**: All 35+ services use `unless-stopped` restart policy. This means a crashing service restarts indefinitely, potentially looping on a persistent bug and consuming resources. Non-critical services (daily-ops-reporter, artifact-retention, soak-monitor) should use `on-failure` with `max_retries` to prevent restart storms.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — `restart: unless-stopped` on all services

**Design decision (pre-answered)**: Keep `unless-stopped` for critical services (bot1, redis, prometheus, postgres, kill-switch, realtime-ui-api). Switch to `on-failure` with `max_retries: 5` for all others.

**Implementation steps**:
1. Classify services: critical (must always restart) vs non-critical (can tolerate downtime).
2. Change non-critical services to `restart: on-failure` with `deploy.restart_policy.max_attempts: 5`.
3. Validate: `docker compose config`.
4. Monitor for 48h: no unexpected service downtime.

**Acceptance criteria**:
- Critical services keep `unless-stopped`.
- Non-critical services use `on-failure` with max retries.
- No restart storm on persistent failure.

**Do not**:
- Change restart policy on redis, postgres, bot1, or kill-switch.
- Remove restart policy entirely — all services need a policy.

---

### [P2-OPS-20260317-2] Add health check to alertmanager `done (2026-03-17)`

**Why it matters**: Alertmanager is the only service without a health check. If it crashes silently, all alerts are lost but Prometheus continues scraping without error. The operator has no visibility into alertmanager health.

**What exists now**:
- `hbot/infra/compose/docker-compose.yml` — alertmanager has no `healthcheck` block
- All other services have health checks

**Design decision (pre-answered)**: Add HTTP health check to alertmanager using its `/-/healthy` endpoint.

**Implementation steps**:
1. Add to alertmanager service in docker-compose:
   ```yaml
   healthcheck:
     test: ["CMD-SHELL", "wget -q --spider http://localhost:9093/-/healthy || exit 1"]
     interval: 30s
     timeout: 5s
     retries: 3
   ```
2. Validate: `docker compose config`.
3. Restart alertmanager, verify health check passes.

**Acceptance criteria**:
- `docker ps` shows alertmanager as `healthy`.
- Alertmanager crash is detected within 90s.

**Do not**:
- Use `curl` in health check — use `wget` (available in alertmanager image).

---

### [P2-OPS-20260317-3] Schedule integration tests in CI / weekly ops `done (2026-03-17)`

**Why it matters**: 3 integration tests exist (`test_ml_signal_to_intent_flow.py`, `test_redis_chaos_smoke.py`, `test_signal_risk_flow.py`) but are excluded from normal test runs (`--ignore=hbot/tests/integration`). These test critical failure paths (Redis disconnect, ML signal flow) that unit tests cannot cover. A semi-pro desk needs regular integration test evidence.

**What exists now**:
- `hbot/tests/integration/` — 3 test files, excluded from normal suite
- Tests require running Redis instance

**Design decision (pre-answered)**: Add a weekly integration test run to the ops checklist. Use docker-compose to spin up a test Redis, run integration tests, tear down.

**Implementation steps**:
1. Create `hbot/scripts/ops/run_integration_tests.sh`: starts test Redis, runs integration tests, stops Redis.
2. Add to weekly ops checklist.
3. Store results in `hbot/reports/verification/integration_tests_latest.json`.

**Acceptance criteria**:
- Integration tests run weekly with fresh results.
- Report artifact exists with pass/fail for each test.

**Do not**:
- Run integration tests against production Redis.
- Block promotion on integration test failures until tests are proven stable.

---

### [P2-FRONT-20260317-1] Extract memoized selectors from dashboard store `done (2026-03-17)`

**Why it matters**: `useDashboardStore.ts` (1,726 lines) has 28 actions and no derived selectors. Components subscribe to raw store slices (`useDashboardStore((state) => state.X)`). Any action that modifies any state slice triggers re-evaluation of all subscriptions. On high-frequency events like `market_quote` (throttled but still frequent), this causes unnecessary re-renders across panels that don't display market data.

**What exists now**:
- `apps/realtime_ui_v2/src/store/useDashboardStore.ts` — 1,726 lines, monolith
- Components select raw slices directly
- No `useShallow` or memoized selector patterns

**Design decision (pre-answered)**: Create `src/store/selectors.ts` with grouped memoized selectors using Zustand's `useShallow` comparator. Group by domain: market, position, fills, orders, connection, health, settings.

**Implementation steps**:
1. Create `src/store/selectors.ts` with typed selector hooks:
   - `useMarketData()` — mid, bid, ask, trading pair
   - `usePositionData()` — position fields
   - `useFillsData()` — fills, fillsTotal, fillFilter, fillSide, fillMaker
   - `useConnectionHealth()` — connection status, health, freshness
   - `useSettings()` — settings object
2. Replace raw `useDashboardStore` calls in components with grouped selectors.
3. Verify with React DevTools: render count should not increase.
4. Add test: market_quote event does not trigger render on FillsPanel.

**Acceptance criteria**:
- Selector file exists with domain-grouped hooks.
- At least 5 components migrated to use selectors.
- No functional regression.

**Do not**:
- Change store state shape — only add a selector layer.
- Over-memoize — only group selectors where re-render reduction is measurable.

---

### [P2-FRONT-20260317-2] Split useRealtimeTransport into composable modules `done (2026-03-17)`

**Why it matters**: `useRealtimeTransport.ts` is 554 lines in a single function. It combines WebSocket lifecycle management, REST fallback polling, health polling, event throttling, session management, and reconnect backoff. This makes it hard to test individual concerns, hard to reason about failure modes, and hard to extend.

**What exists now**:
- `apps/realtime_ui_v2/src/hooks/useRealtimeTransport.ts` — 554 lines, single exported function
- `useRealtimeTransport.test.ts` — 99 lines (limited coverage)

**Design decision (pre-answered)**: Extract into 3-4 focused modules: `useWebSocketManager` (connection lifecycle, reconnect), `useRestFallback` (REST polling, health), `useEventThrottle` (high-frequency event batching), and `useRealtimeTransport` (orchestrator).

**Implementation steps**:
1. Extract `useWebSocketManager.ts`: WS open/close, reconnect backoff, session ID management.
2. Extract `useRestFallback.ts`: `/api/v1/state` polling, `/api/v1/health` polling, stale rejection.
3. Extract `useEventThrottle.ts`: high-frequency event batching, pending message cap.
4. Simplify `useRealtimeTransport.ts` to orchestrate the 3 modules.
5. Add tests for each extracted module independently.

**Acceptance criteria**:
- Each module is < 150 lines.
- `useRealtimeTransport` orchestrator is < 100 lines.
- Existing test coverage maintained or improved.
- No behavioral regression.

**Do not**:
- Change the external API of `useRealtimeTransport` — components should not need changes.
- Break WebSocket reconnect behavior — this is the most critical path.

---

### [P2-FRONT-20260317-3] Add ARIA accessibility labels to interactive controls `done (2026-03-17)`

**Why it matters**: Frontend accessibility score is 3/10. No ARIA labels on TopBar controls, table headers, tabs, or interactive panels. While the primary user is a desktop operator, accessibility is a quality baseline for professional software. Screen reader support also helps with automated testing tools.

**What exists now**:
- `prefers-reduced-motion` media query present (good)
- No `aria-label`, `role`, or `aria-live` attributes on interactive elements
- No a11y audit has been run

**Design decision (pre-answered)**: Add ARIA labels to all interactive controls incrementally. Start with TopBar (view buttons, instance selector, settings), then tables (column headers, row roles), then panels (live region for alerts).

**Implementation steps**:
1. TopBar.tsx: Add `aria-label` to view buttons, instance selector `<select>`, settings menu.
2. Tables: Add `role="grid"` to table containers, `aria-sort` to sortable columns.
3. AlertsStrip: Add `aria-live="polite"` for alert updates.
4. ConnectionBadge (from P1-FRONT-20260317-1): Add `aria-live="assertive"` for connection state changes.
5. Run Lighthouse accessibility audit and record baseline score.

**Acceptance criteria**:
- Lighthouse accessibility score >= 70 (from estimated ~40 baseline).
- All interactive controls have `aria-label`.
- Alert strip uses `aria-live`.

**Do not**:
- Add ARIA labels that duplicate visible text — use only where screen reader needs additional context.
- Skip TopBar — it's the primary navigation element.

---

### [P2-FRONT-20260317-4] Add panel rendering tests for edge cases `done (2026-03-17)`

**Why it matters**: No tests exist for panel rendering with partial, malformed, or empty data. If the API changes payload shape, panels may crash without error boundaries catching it (since Zod validates at the transport layer, not at each panel). Edge case coverage prevents operator-visible crashes.

**What exists now**:
- `TopBar.test.tsx` (78 lines) and `InstancesPreviewStrip.test.tsx` (133 lines) — 2 component tests
- No tests for data panels (FillsPanel, OrdersPanel, MarketChartPanel, etc.)
- `ViewErrorBoundary` catches crashes but user sees error UI

**Design decision (pre-answered)**: Add render tests for data panels with: empty data, partial data (some fields null), and error state. Use React Testing Library.

**Implementation steps**:
1. Add `FillsPanel.test.tsx`: render with 0 fills, 1 fill, fill with null fields.
2. Add `OrdersPanel.test.tsx`: render with 0 orders, partial order data.
3. Add `MarketChartPanel.test.tsx`: render with no candles, 1 candle, gap in candle series.
4. Add `PositionExposurePanel.test.tsx`: render with no position, position with zero values.
5. Each test: verify no crash, verify meaningful empty state shown.

**Acceptance criteria**:
- 4 new test files with >= 3 test cases each.
- All panels render without crash on empty/partial data.
- `npx vitest run` passes.

**Do not**:
- Test implementation details (store internals) — test rendered output only.
- Skip MarketChartPanel — it's the most complex panel and most likely to crash on edge data.

---

### [P2-PERF-20260317-1] Establish frontend render profiling baseline `done (2026-03-17)`

**Why it matters**: No render performance data exists. The store has 28 actions, no selectors, and high-frequency events. Without measurement, frontend optimization is guesswork. A semi-pro dashboard must be responsive under live data flow.

**What exists now**:
- No Lighthouse scores, no React DevTools profiling data, no Web Vitals measurement
- `lightweight-charts` and `@tanstack/react-table` as heaviest components
- Bounded buffers prevent unbounded growth

**Design decision (pre-answered)**: Run Lighthouse on the dashboard and record baseline. Use React DevTools Profiler to identify worst-case panel render times under simulated data flow.

**Implementation steps**:
1. Run Lighthouse: `npx lighthouse http://localhost:8088 --output json --output-path hbot/reports/verification/lighthouse_baseline.json`.
2. Record: Performance score, FCP, LCP, TBT, CLS.
3. Use React DevTools Profiler: open dashboard, let it run for 5 minutes with live data, export profile.
4. Identify: which panel has the longest render time? Which renders most frequently?
5. Document baseline in `hbot/reports/verification/frontend_perf_baseline.md`.

**Acceptance criteria**:
- Lighthouse report exists with scores.
- Worst-case panel render time identified.
- Baseline documented for future comparison.

**Do not**:
- Profile with browser extensions that add overhead.
- Optimize before measuring.

---

### [P2-TECH-20260317-1] Plan hb_bridge.py decomposition `done (2026-03-17)`

**Why it matters**: `paper_engine_v2/hb_bridge.py` at 2,648 lines is the second largest file in the system. It bridges the paper engine to Hummingbot's event system. A single failure here stops all paper trading. The file combines connection management, event routing, order lifecycle, position tracking, and state serialization.

**What exists now**:
- `hbot/controllers/paper_engine_v2/hb_bridge.py` — 2,648 lines
- Tests: `test_hb_bridge_signal_routing.py` (61 tests)

**Design decision (pre-answered)**: Create a decomposition plan identifying natural seams (similar to P1-TECH-20260317-3 for shared_mm_v24.py). Proposed modules: event routing, order lifecycle adapter, position sync, state serialization.

**Implementation steps**:
1. Generate method inventory with call relationships.
2. Identify 4-5 natural modules.
3. Write plan as `hbot/docs/architecture/hb_bridge_decomposition_plan.md`.
4. Estimate test migration effort per module.

**Acceptance criteria**:
- Decomposition plan exists.
- No proposed module > 600 lines.

**Do not**:
- Start decomposing without the plan document.

---

### [P2-TECH-20260317-2] Plan paper_exchange_service decomposition `done (2026-03-17)`

**Why it matters**: `services/paper_exchange_service/main.py` at 3,480 lines is the third largest file. It simulates the entire exchange: order FSM, matching, position management, and Redis stream I/O in a single file.

**What exists now**:
- `hbot/services/paper_exchange_service/main.py` — 3,480 lines
- `order_fsm.py` — 68 lines (already extracted)
- Tests: `test_paper_exchange_service.py` (71 tests)

**Design decision (pre-answered)**: Create decomposition plan. Proposed modules: order management, matching loop, position/balance tracking, Redis stream adapter, health/metrics.

**Implementation steps**:
1. Generate method inventory.
2. Identify 4-5 natural modules.
3. Write plan as `hbot/docs/architecture/paper_exchange_decomposition_plan.md`.

**Acceptance criteria**:
- Decomposition plan exists.
- No proposed module > 800 lines.

**Do not**:
- Start decomposing without the plan.
- Change matching logic behavior.

---

### [P2-QUANT-20260317-1] Design bounded experiment for Bot5 (IFT Jota) `done (2026-03-17)`

**Why it matters**: Bot5 uses imbalance + trend flow signals but has no performance data. The directional strategy cannot be assessed without a bounded experiment. Leaving it in perpetual freeze wastes the development investment.

**What exists now**:
- `hbot/controllers/bots/bot5/ift_jota_v1.py` — 423 lines
- Config path: `hbot/data/bot5/conf/controllers/`
- Experiment ledger: `hbot/docs/strategy/bot5_experiment_ledger.md`
- Verdict from initial audit: `freeze` (no data)

**Design decision (pre-answered)**: Design a falsifiable 48h paper experiment with defined success/failure criteria. Do not deploy until bot1 is generating baseline data (P0-QUANT-20260317-1 must be done first).

**Implementation steps**:
1. Define experiment in bot5 experiment ledger:
   - Hypothesis: IFT flow signal generates positive PnL/fill net of fees
   - Config: current bot5 config with directional parameters
   - Duration: 48h minimum
   - Primary KPIs: fill count, PnL/fill, hit rate, max drawdown
   - Guardrail: max DD < 3%, stop if > 10 consecutive losing fills
   - Success: PnL/fill > 0 net of fees with >= 20 fills
   - Failure: PnL/fill < -2 bps or < 10 fills in 48h
2. Verify bot5 compose profile and config are correct.
3. Do not start experiment until P0-QUANT-20260317-1 is done.

**Acceptance criteria**:
- Experiment design documented in ledger with falsification criteria.
- Config verified against DirectionalRuntimeController requirements.

**Do not**:
- Run bot5 experiment concurrently with bot1 parameter changes.
- Skip defining failure/rollback criteria.

---

### [P2-QUANT-20260317-2] Design bounded experiment for Bot6 (CVD Divergence) `done (2026-03-17)`

**Why it matters**: Bot6 uses CVD spot-vs-perp divergence signals but has multiple logic bugs (P1-STRAT-20260316-3, P1-STRAT-20260316-4) and no performance data. The experiment should only run after the logic fixes are applied.

**What exists now**:
- `hbot/controllers/bots/bot6/cvd_divergence_v1.py` — 549 lines
- Open bugs: CVD denominator inversion (P1-STRAT-20260316-3), delta spike baseline too small (P1-STRAT-20260316-4), missing z-score (P2-STRAT-20260316-8), stale spot data (P2-STRAT-20260316-9)
- Verdict from initial audit: `freeze` (no data + logic bugs)

**Design decision (pre-answered)**: Fix logic bugs first (P1-STRAT-20260316-3 and -4 minimum), then design 48h bounded experiment.

**Implementation steps**:
1. Prerequisite: complete P1-STRAT-20260316-3 (denominator fix) and P1-STRAT-20260316-4 (baseline sample size).
2. Define experiment in experiment ledger:
   - Hypothesis: CVD divergence generates positive PnL/fill on BTC-USDT perps
   - Duration: 48h
   - Primary KPIs: fill count, PnL/fill, hit rate, max drawdown
   - Guardrail: max DD < 3%
   - Success: PnL/fill > 0 net of fees with >= 15 fills
   - Failure: PnL/fill < -2 bps or < 5 fills in 48h
3. Verify config and compose profile.

**Acceptance criteria**:
- Logic bugs fixed before experiment start.
- Experiment design documented with falsification criteria.

**Do not**:
- Run experiment with known denominator inversion bug.
- Skip defining failure criteria.

---

## ARCH — Project Structure Reorganization

### Project Structure Analysis (2026-03-22)

The `hbot/` root currently mixes seven distinct concerns in a flat layout:

| Concern | Current location | Problem |
|---|---|---|
| **Source code** | `controllers/`, `services/`, `scripts/` | Clean — no issue |
| **Tests** | `tests/` | Clean — mirrors source |
| **Runtime data** | `data/bot1`–`bot7/`, `data/shared/`, SQLite DBs | Bot runtime state (desk_events, paper_desk_svc.json, logs/*.csv) lives next to checked-in configs (`conf/`). `.gitignore` filters most of it but the dir tree is confusing. |
| **Historical / ML data** | `data/historical/`, `data/ml/`, `data/backtest_configs/` | Backtest configs (60+ YAMLs) are checked in alongside runtime data dirs |
| **Generated reports** | `reports/` (30+ subdirs, 9900+ JSON files) | Ephemeral outputs sitting at the same level as source code. `.gitignore` handles timestamped ones but `reports/` still dominates the tree. |
| **Web app** | `apps/realtime_ui_v2/` | Fine as a top-level dir, but `node_modules/` and `package.json` leak into `hbot/` root instead of living inside `apps/realtime_ui_v2/`. |
| **Screenshots / Playwright** | Root-level `screenshot*.png`, `screenshot_*.js`, `node_modules/` | `.gitignore` excludes them but they pollute `ls` output and Playwright's `node_modules/` (300+ dirs) sits at `hbot/` root. |
| **Infra configs** | `infra/compose/`, `infra/monitoring/`, `infra/firewall-rules.sh`, `infra/env/`, top-level `config/` | Operational tooling grouped under `infra/`; policy JSON stays in `config/`. |
| **Nested `hbot/hbot/`** | `hbot/hbot/` | Confusing — appears to be a symlink or mount artifact for data/reports paths in Docker. |

#### Key smells:
1. **`node_modules/` at `hbot/` root** — Playwright is used for UI testing/screenshots. Its `package.json` and `node_modules/` should live inside `apps/realtime_ui_v2/`, not at the Python project root.
2. **`data/` is overloaded** — it holds checked-in configs, runtime state, historical market data, and backtest job configs in a single tree. Newcomers can't tell what's source-controlled vs generated.
3. **`reports/` is massive** — 30+ subdirs with thousands of generated files. Even with `.gitignore`, the dir structure is noisy.
4. **Infra grouping** — Compose, monitoring, env, and firewall script live under `infra/`; `config/` remains top-level for JSON policies.
5. **`hbot/hbot/`** nested directory is confusing.

### [P2-ARCH-20260322-1] Relocate `node_modules` and `package.json` into `apps/realtime_ui_v2/` `open`

**Why it matters**: Python project root has 300+ dirs from Playwright's `node_modules/`. This bloats `ls`, confuses IDE indexing, and mixes JS dependency management with the Python workspace.

**What exists now**:
- `hbot/package.json` and `hbot/package-lock.json` at root
- `hbot/node_modules/` (Playwright) at root
- `apps/realtime_ui_v2/` has its own `package.json` already

**Design decision (pre-answered)**: Move Playwright `package.json` into `apps/realtime_ui_v2/` (or a dedicated `apps/e2e/` dir). Update any screenshot scripts to reference the new path. Add `node_modules/` to root `.gitignore` as a safety net.

**Implementation steps**:
1. Move `hbot/package.json` and `hbot/package-lock.json` into `apps/realtime_ui_v2/` (merge with existing if present).
2. Delete `hbot/node_modules/` and reinstall from the new location.
3. Update any scripts that reference Playwright from root.
4. Add `node_modules/` to `.gitignore` if not already present.

**Acceptance criteria**:
- No `package.json` or `node_modules/` at `hbot/` root.
- Playwright scripts still work from new location.

**Do not**:
- Break existing screenshot or E2E test workflows.

---

### [P2-ARCH-20260322-2] Split `data/` into `data/` (checked-in) and runtime output `open`

**Why it matters**: `data/` currently holds checked-in configs (`data/bot*/conf/`, `data/backtest_configs/`), runtime state (`data/bot*/logs/`, SQLite DBs), and historical market data (`data/historical/`). Contributors can't tell what's source-controlled.

**What exists now**:
- `data/bot{1..7}/conf/` — checked in (strategy YAML configs)
- `data/bot{1..7}/logs/`, `data/bot{1..7}/data/` — gitignored runtime output
- `data/backtest_configs/` — 60+ checked-in YAML files
- `data/historical/` — catalog.json checked in, Parquet files gitignored
- `data/shared/` — SQLite DBs (gitignored)
- `data/backtest_jobs.sqlite3` — gitignored

**Design decision (pre-answered)**: Rename is not worth the Docker mount breakage. Instead, add a `data/README.md` that documents what's checked in vs generated, and consider moving `data/backtest_configs/` to `config/backtest/` to co-locate with other config.

**Implementation steps**:
1. Create `data/README.md` explaining the directory layout and what's tracked vs generated.
2. Optionally move `data/backtest_configs/` → `config/backtest/` and update all references in YAML loaders, CLI scripts, and docs.
3. Update `config_loader.py` and `harness_cli.py` default paths if moved.

**Acceptance criteria**:
- `data/README.md` exists and is accurate.
- All backtest config references still resolve.

**Do not**:
- Break Docker volume mounts (`data/bot*/` paths are baked into compose).
- Move `data/historical/` — it's the data catalog root and is referenced everywhere.

---

### [P2-ARCH-20260322-3] Consolidate infra config dirs under `infra/` `open`

**Why it matters**: Operational configs are easier to navigate with compose, monitoring, env, and firewall automation under `infra/` while `config/` stays top-level for JSON policies.

**What exists now**:
- `infra/compose/` — `docker-compose.yml`, `images/`, `logrotate.d/`
- `infra/monitoring/` — Prometheus, Grafana, Alertmanager, Promtail configs
- `infra/firewall-rules.sh` — Firewall rules
- `infra/env/` — `.env.template`
- `config/` — JSON risk/policy configs, Mosquitto, strategy catalog

**Design decision (pre-answered)**: Consolidate into `infra/` with subdirs. This is a cosmetic improvement — only do it if Docker Compose paths can be updated without breaking the deployment pipeline.

**Current layout**:
```
infra/
  compose/           ← docker-compose.yml, images/, logrotate.d/
  monitoring/        ← prometheus/, grafana/, alertmanager/
  firewall-rules.sh  ← firewall rules
  env/               ← .env.template
config/              ← JSON policies, mosquitto, strategy catalog (top-level)
```

**Implementation steps**:
1. Create `infra/` and move subdirs.
2. Update all `docker-compose.yml` paths, `compose_up.sh`, monitoring configs.
3. Update `.cursor/rules/project-context.mdc` workspace layout.
4. Verify `docker compose up` still works.

**Acceptance criteria**:
- Single `infra/` dir at root for all ops config.
- `docker compose up` passes.

**Do not**:
- Do this mid-deployment or during an active experiment window.
- Change any config file contents — only move files.

---

### [P2-ARCH-20260322-4] Clean up `hbot/hbot/` nested directory `open`

**Why it matters**: A nested `hbot/hbot/` directory exists, likely as a symlink or Docker mount artifact. It creates confusion about the project root.

**Implementation steps**:
1. Determine if `hbot/hbot/` is a symlink, mount point, or accidental copy.
2. If symlink: document its purpose in `README.md` and ensure Docker Compose references it correctly.
3. If accidental: remove it and verify nothing breaks.

**Acceptance criteria**:
- Purpose of `hbot/hbot/` is documented or the artifact is removed.

---

### [P2-ARCH-20260322-5] Backtesting package internal reorganization `open`

**Why it matters**: The backtesting package has 30 files in a flat directory. The previous architecture review identified: (a) harness.py `_build_adapter()` is a 380-line if/elif chain — a registry pattern would be cleaner and more extensible; (b) adapter configs duplicate shared fields without a common base; (c) flat layout will become hard to navigate as more adapters are added.

**What exists now**:
- 30 `.py` files flat in `controllers/backtesting/`
- 7 adapter files, each with their own config dataclass
- `_build_adapter()` in `harness.py` is ~380 LOC of string-matching

**Design decision (pre-answered)**: Phase 1: extract adapter registry. Phase 2 (optional): sub-package layout.

**Phase 1 — Adapter registry**:
1. Create `controllers/backtesting/adapter_registry.py` with a `ADAPTER_REGISTRY` dict mapping `adapter_mode` → `(AdapterClass, ConfigClass)`.
2. Refactor `_build_adapter()` to use the registry: lookup, hydrate config, instantiate.
3. Each adapter registers itself or is registered in the registry module.

**Phase 2 — Sub-package layout** (optional, only if >40 files):
```
backtesting/
  domain/        types.py, metrics.py
  adapters/      pullback_adapter.py, atr_mm_adapter.py, ...
  infra/         data_store.py, data_catalog.py, config_loader.py
  replay/        replay_harness.py, replay_clock.py, ...
  cli/           harness_cli.py, sweep_cli.py
```

**Acceptance criteria**:
- `_build_adapter()` < 50 LOC.
- All existing tests pass.
- Adding a new adapter requires only: (a) new adapter file, (b) one line in registry.

**Do not**:
- Change adapter behavior — this is purely structural.
- Do Phase 2 unless the package grows past ~40 files.

