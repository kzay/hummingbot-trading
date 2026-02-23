# Promotion Gate Contract (Day 6)

## Command
- `python scripts/release/run_promotion_gates.py`
- CI-like mode (Day 17):
  - `python scripts/release/run_promotion_gates.py --ci`
- Replay regression cycle (Day 10):
  - `python scripts/release/run_replay_regression_cycle.py --repeat 2 --min-events 1000`
- Multi-window replay regression (Day 38):
  - `python scripts/release/run_replay_regression_multi_window.py --windows 500,1000,2000 --repeat 2`
- Optional freshness helper:
  - `python scripts/release/run_promotion_gates.py --refresh-parity-once`
- Optional upgrade preflight:
  - `python scripts/release/check_hb_upgrade_readiness.py --target-image <candidate-image-tag>`
- Strict convenience cycle:
  - `python scripts/release/run_strict_promotion_cycle.py`
- Strict watcher (post-Day7):
  - `python scripts/release/watch_strict_cycle.py --interval-sec 300 --append-incident-on-transition`
- Readiness finalizer (post-Day7):
  - `python scripts/release/finalize_readiness_decision.py`

## Purpose
Single-command promotion decision that outputs PASS/FAIL with explicit reasons and evidence paths.

## Critical Gates
1. `preflight_checks`
- Required config/spec/scripts exist.

2. `multi_bot_policy_scope`
- Multi-bot policy consistency across:
  - `config/multi_bot_policy_v1.json`
  - `config/portfolio_limits_v1.json`
  - `config/exchange_account_map.json`
  - `config/reconciliation_thresholds.json`

3. `strategy_catalog_consistency`
- Strategy catalog bundles resolve to existing config pairs and shared controller code.

4. `coordination_policy_scope`
- Coordination service policy and compose guardrails must enforce allowed scope/mode.

5. `unit_service_integration_tests`
- Deterministic tests (`unit`, `service`, `integration`) and coverage threshold must pass via `scripts/release/run_tests.py`.

6. `secrets_hygiene`
- Automated secret leakage scan must pass for docs/reports/log artifacts.

7. `smoke_checks`
- Smoke activity evidence exists for live test path (`bot4` minute logs).

8. `paper_smoke_matrix`
- Paper validation intent is enforced (`bot3` stays `paper_only` in exchange snapshot evidence).

9. `replay_regression_first_class`
- Deterministic replay regression must pass as a first-class critical gate across multiple event windows (`500,1000,2000`) with repeatability checks.

10. `ml_signal_governance`
- ML governance policy contract must pass:
  - baseline comparison thresholds,
  - drift limits,
  - retirement criteria.
- When `ML_ENABLED=false`, checker must still pass policy shape + safe baseline-only mode.
- Implemented by `scripts/release/check_ml_signal_governance.py`.

11. `regression_backtest_harness`
- Deterministic regression harness returns PASS and writes report.

12. `reconciliation_status`
- Latest reconciliation report is fresh and has zero critical findings.

13. `parity_thresholds`
- Latest parity report is fresh and status is `pass`.

14. `portfolio_risk_status`
- Latest portfolio risk report is fresh and has zero critical findings.

15. `accounting_integrity_v2`
- Accounting snapshots are fresh, structurally complete, and free of critical accounting findings.
- Implemented by `scripts/release/check_accounting_integrity_v2.py`.

16. `alerting_health`
- Alert webhook evidence exists and is recent.

17. `event_store_integrity_freshness`
- Latest integrity artifact is fresh and has `missing_correlation_count == 0`.

18. `market_data_freshness` (warning)
- Latest event-store JSONL artifact is fresh and includes `hb.market_data.v1` rows.
- Implemented by `scripts/release/check_market_data_freshness.py`.

19. `day2_event_store_gate` (optional strict dependency)
- Enabled via `--require-day2-go`.

## Post-Day7 Convenience
- `run_strict_promotion_cycle.py` runs:
  - strict gate mode (`--require-day2-go`)
  - one-shot parity refresh (`--refresh-parity-once`)
  - CI defaults (`--ci`) for stricter freshness window
  - writes summary artifact: `reports/promotion_gates/strict_cycle_latest.json`
- Optional incident note append:
  - `--append-incident-on-fail`
- `watch_strict_cycle.py` runs strict cycles periodically and records status transitions:
  - state: `reports/promotion_gates/strict_watch_state.json`
  - transitions: `reports/promotion_gates/strict_watch_transitions.jsonl`
  - optional incident note append only when status transitions to FAIL.
- `finalize_readiness_decision.py` generates:
  - `reports/readiness/final_decision_latest.json`
  - `docs/ops/option4_readiness_decision_latest.md`
  - Optional primary doc update with `--apply-to-primary`.

## Output Artifacts
- `reports/promotion_gates/latest.json`
- `reports/promotion_gates/promotion_gates_<timestamp>.json`
- `reports/promotion_gates/latest.md`
- `reports/promotion_gates/promotion_gates_<timestamp>.md`
- Replay cycle artifacts:
  - `reports/replay_regression/latest.json`
  - `reports/replay_regression/latest.md`
  - `reports/replay_regression/replay_regression_<timestamp>.json`
  - `reports/replay_regression/replay_regression_<timestamp>.md`
- Multi-window replay artifacts:
  - `reports/replay_regression_multi_window/latest.json`
  - `reports/replay_regression_multi_window/latest.md`
  - `reports/replay_regression_multi_window/replay_regression_multi_window_<timestamp>.json`
  - `reports/replay_regression_multi_window/replay_regression_multi_window_<timestamp>.md`

## Stable Evidence References (Day 13)
- Gate output includes:
  - `release_manifest_ref` (`path`, `sha256`, `size_bytes`)
  - `evidence_bundle.evidence_bundle_id`
  - `evidence_bundle.artifacts[]` with stable file references
- These references provide a queryable audit trail from release manifest to gate decision evidence.

## Blocking Rule
- Any failed **critical** gate => overall `FAIL` and non-zero process exit code.
- Deployment/promotion must be blocked on `FAIL`.
- Failed **warning** gates do not flip global status to `FAIL`, but must be reviewed before promotion approval.

## Operator Workflow
1. Run the command.
2. Read `status` and `critical_failures`.
3. Use `checks[].evidence_paths` to investigate and remediate.
4. Re-run until status is `PASS`.
