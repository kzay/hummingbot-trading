# Option 4 Operator Checklist (One Page)

## Purpose
Quick daily execution checklist for Option 4:
- Keep Hummingbot for live execution
- Add external reliability layers
- Enforce safety-first promotion gates

## How To Use
- Run this checklist once per day.
- Mark each item `DONE` or `BLOCKED`.
- If any critical item is blocked, stop promotion and run rollback/safety actions.

---

## Day 1 - Baseline Freeze
- [x] Baseline manifest created (image tag + active configs + risk params) (DONE: `docs/ops/release_manifest_20260221.md`)
- [x] Reproducible startup verified from manifest (DONE: compose `config/up/ps` on 2026-02-21)
- [x] Hard-stop path tested and logged (DONE: evidence in `data/bot1/logs/epp_v24/...`)
- [x] Monitoring stack health verified (DONE: Prometheus/Grafana/Loki/exporter healthy)
- [x] Alert delivery path tested (DONE: Alertmanager -> `alert-webhook-sink` deliveries observed)

Go/No-Go:
- [x] GO only if all five items are complete

## Day 2 - Event Store
- [x] Event schema finalized (orders, fills, risk decisions, states) (DONE: `docs/architecture/event_schema_v1.md`)
- [x] Append-only event store running (DONE: `services/event_store/main.py` + compose `event-store-service`)
- [x] Correlation IDs present end-to-end (DONE: normalization verified in `reports/event_store/events_20260221.jsonl`)
- [ ] 24h ingestion run completed (PAUSED_BY_OPERATOR: baseline reanchor applied at `2026-02-22T13:25Z`; resume after full 24h window from new baseline)
- [x] Event counts match source logs within tolerance (DONE: snapshots `reports/event_store/source_compare_20260221T170633Z.json`, `reports/event_store/source_compare_20260221T170659Z.json`)

Go/No-Go:
- [ ] GO only if ingestion is stable and no critical loss (PAUSED_BY_OPERATOR: `day2_event_store_gate` deferred until elapsed window; latest gate `reports/event_store/day2_gate_eval_latest.json`)

## Day 3 - Reconciliation
- [x] Balance reconciliation job active (DONE: `reconciliation-service` running)
- [x] Position/inventory reconciliation job active (DONE: inventory drift checks in report output)
- [x] Fill/order parity checks active (DONE: parity check implemented in reconciliation report)
- [x] Drift severity rules implemented (warning/critical) (DONE: severity-based findings in `reports/reconciliation/latest.json`)
- [x] Drift alert test passed (DONE: synthetic drift critical finding recorded)

Go/No-Go:
- [x] GO only if critical drift alerts trigger correctly (MVP GO)

## Day 4 - Shadow Execution
- [x] Shadow evaluator deployed (DONE: `services/shadow_execution/main.py` + compose `shadow-parity-service`)
- [x] Fill ratio delta tracked (DONE: `reports/parity/latest.json` metric `fill_ratio_delta`)
- [x] Slippage delta (bps) tracked (DONE: `reports/parity/latest.json` metric `slippage_delta_bps`)
- [x] Reject rate delta tracked (DONE: `reports/parity/latest.json` metric `reject_rate_delta`)
- [x] Realized PnL delta tracked (DONE: `reports/parity/latest.json` metric `realized_pnl_delta_quote`)
- [x] Daily parity report generated automatically (DONE: `reports/parity/YYYYMMDD/parity_<timestamp>.json` + `reports/parity/latest.json`)

Go/No-Go:
- [x] GO only if parity report is complete and thresholded (DAY 4 MVP GO: thresholds in `config/parity_thresholds.json`, report `status=pass`)

## Day 5 - Portfolio Risk
- [x] Global daily loss cap active (DONE: `portfolio-risk-service` evaluates `global_daily_loss_cap_pct`)
- [x] Cross-bot net exposure cap active (DONE: `cross_bot_net_exposure_cap_quote` check in report)
- [x] Concentration caps active (DONE: `concentration_cap_pct` check in report)
- [x] Risk actions wired to pause/kill paths (DONE: emits `soft_pause` / `kill_switch` execution intents for scoped live bots)
- [x] Audit trail verified for each risk action (DONE: append-only `reports/portfolio_risk/audit_20260221.jsonl`)

Go/No-Go:
- [x] GO only if breach simulation triggers expected controls (DONE: synthetic breach produced `portfolio_action=kill_switch` with scoped actions for `bot1` and `bot4`)

## Day 6 - Promotion Gates
- [x] Automated gate runner executes in one command (DONE: `python scripts/release/run_promotion_gates.py`)
- [x] Preflight checks included (DONE: required config/spec/script checks in gate report)
- [x] Smoke checks included (DONE: bot4 smoke artifact checks)
- [x] Reconciliation checks included (DONE: `reports/reconciliation/latest.json` freshness + critical check)
- [x] Parity checks included (DONE: `reports/parity/latest.json` freshness + status check)
- [x] Alerting health checks included (DONE: `reports/reconciliation/last_webhook_sent.json` recency check)
- [x] Promotion blocking works on critical failure (DONE: strict run failed on `day2_event_store_gate` with non-zero exit)

Go/No-Go:
- [x] GO only if gate runner provides clear PASS/FAIL reasons (DONE: PASS and FAIL runs both produced explicit `critical_failures` + evidence paths)

## Day 7 - Soak and Decision
- [ ] 24h-48h micro-capital soak completed
- [ ] Stability reviewed (run/pause/hard-stop behavior)
- [ ] Reconciliation drift reviewed
- [ ] Parity deltas reviewed
- [ ] Risk action frequency reviewed
- [x] Readiness decision documented (PROVISIONAL HOLD documented in `docs/ops/option4_readiness_decision.md`)

Go/No-Go:
- [ ] GO for next phase only with evidence-backed readiness decision

---

## Post-Day40 Operational Closure
- [x] Day 1-40 implementation delivered in repo (code/docs/services/gates completed)
- [x] Strict cycle no longer blocked by secrets hygiene (latest strict failures contain only Day2 gate)
- [ ] Day 2 elapsed window complete and `day2_event_store_gate` flipped to GO
- [ ] Day 7 soak status upgraded from `hold` to `ready`
- [ ] Day 15 funded live window evidence captured (or formally waived by operator)

Current blocking set (latest):
- `day2_event_store_gate`
- `soak_not_ready`

Immediate operator commands:
- `python scripts/utils/day2_gate_evaluator.py`
- `python scripts/release/run_strict_promotion_cycle.py --max-report-age-min 20`
- `python scripts/release/finalize_readiness_decision.py --apply-to-primary`

---

## Daily Stop Conditions (Critical)
- [ ] Reconciliation critical drift unresolved
- [ ] Parity metrics outside hard thresholds
- [ ] Unexplained hard-stop events
- [ ] Alerting pipeline unavailable

If any box above is checked:
- [ ] Pause promotion activity
- [ ] Execute rollback/safety runbook
- [ ] Log incident and owner/action

---

## Daily Report (Required)
1. What changed
2. Files/services touched
3. Validation run
4. Metrics before/after
5. Incidents/risks
6. Rollback status
7. Next day top 3 tasks
