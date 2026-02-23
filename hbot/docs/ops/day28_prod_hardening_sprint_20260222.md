# Day 28 - Prod Hardening Sprint v1

## Scope Executed
- Reliability hardening via service healthchecks across control-plane and ops writer services.
- Promotion gate fail-closed tightening for freshness/safety signals.
- Recovery drill playbook for stale report and restart scenarios.

## Changes Implemented
- Compose healthchecks added for:
  - `signal-service`, `risk-service`, `coordination-service`
  - `event-store-service`, `event-store-monitor`, `day2-gate-monitor`
  - `reconciliation-service`, `exchange-snapshot-service`, `shadow-parity-service`, `portfolio-risk-service`
  - `soak-monitor`, `daily-ops-reporter`, `ops-db-writer`
- Freshness threshold envs (`*_HEALTH_MAX_SEC`) added for all output-producing services with conservative defaults.
  - `signal-service`, `risk-service`, `coordination-service` use Redis-ping healthchecks (no freshness env needed).
- Promotion gate strictness tightened:
  - `scripts/release/run_promotion_gates.py`
    - default freshness window reduced (`20m`; CI `15m`)
    - new critical check: `portfolio_risk_status`
    - new critical check: `strategy_catalog_consistency` (runs `check_strategy_catalog_consistency.py`)
    - `check_strategy_catalog_consistency.py` added to preflight file list
  - `scripts/release/run_strict_promotion_cycle.py`
    - now invokes gate runner with `--ci`
    - strict cycle freshness default reduced to `20m`
  - `scripts/release/watch_strict_cycle.py`
    - strict watch freshness default reduced to `20m`
- Contract/docs updated:
  - `docs/validation/promotion_gate_contract.md`
  - `docs/ops/day8_reproducible_builds_20260222.md`
  - `docs/ops/recovery_drills_v1.md`

## Validation
- `docker compose ... config` passes with new healthcheck definitions.
- Python compile check passed for modified gate scripts (AST clean: all 4 scripts).
- Gate validation run (`--ci`) confirms fail-closed behavior on stale integrity:
  - `reports/promotion_gates/promotion_gates_20260222T124736Z.json`
  - status: `FAIL`
  - critical failures: `event_store_integrity_freshness`
  - note: this run predates addition of `strategy_catalog_consistency` check
- `strategy_catalog_consistency` confirmed pass post-addition:
  - `reports/strategy_catalog/latest.json` (`status=pass`, 4 bundles checked: `epp_v2_4_bitget_live_microcap_bot1`, `epp_v2_4_bitget_live_notrade_bot1`, `epp_v2_4_bitget_paper_smoke_bot3`, `epp_v2_4_binance_testnet_smoke_bot4`)

## Bug Fixed During Validation
- `scripts/release/run_promotion_gates.py` — `event_store_integrity_freshness` check used `ts_utc` key but `event_store/main.py` writes `last_update_utc`.
  - Gate always fell back to OS file mtime silently instead of the embedded report timestamp.
  - Fixed: check now resolves `ts_utc` first, then `last_update_utc`, then file mtime as final fallback.
- Additional undocumented gate additions confirmed in live run (added post-Day 28 validation snapshot):
  - `coordination_policy_scope` check (`check_coordination_policy.py`, `config/coordination_policy_v1.json`)
  - `unit_service_integration_tests` check (`run_tests.py`)
  - Both checks now included in preflight file list.

## Live Validation Run (post-fix)
- Command: `python scripts/release/run_promotion_gates.py --skip-replay-cycle --max-report-age-min 15`
- Evidence: `reports/promotion_gates/promotion_gates_20260222T131109Z.json`
- Exit code: `2` (FAIL — correct fail-closed behavior)
- Status: `FAIL`, `critical_failures=["event_store_integrity_freshness"]`
- All 15 other checks: PASS
- Integrity staleness confirmed via `last_update_utc` (08:15 UTC vs gate run 13:11 UTC = 296 min > 15-min window)
- Total checks in current gate: 16

## Outcome
- Control-plane services now have executable health semantics (not just process liveness).
- Promotion path is stricter on freshness and explicitly includes portfolio risk health.
- Recovery drills are documented for repeatable operator execution.
- Integrity freshness check now uses the correct embedded `last_update_utc` timestamp from the event store report.
