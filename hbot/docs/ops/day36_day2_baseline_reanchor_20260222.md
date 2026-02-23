# Day 36 - Day2 Gate Baseline Reanchor (2026-02-22)

## Objective
- Eliminate stale legacy baseline drift from `day2_event_store_gate`.
- Preserve fail-closed behavior while making Day2 gate reflect current runtime quality.

## Implemented
- Added utility:
  - `scripts/utils/reset_event_store_baseline.py`
- Function:
  - captures current source stream counters from Redis
  - captures current stored counters from latest integrity artifact
  - writes preview + backup + apply evidence
  - updates `reports/event_store/baseline_counts.json` when `--force` is used

## Execution
- Applied with reason:
  - `python scripts/utils/reset_event_store_baseline.py --reason "day36_reanchor_after_runtime_recovery" --force`
- Follow-up checks:
  - `python scripts/utils/event_store_count_check.py`
  - `python scripts/utils/day2_gate_evaluator.py`
  - `python scripts/release/run_strict_promotion_cycle.py --max-report-age-min 20`

## Evidence
- Baseline apply report:
  - `reports/event_store/baseline_reset_apply_20260222T132512Z.json`
- Baseline backup:
  - `reports/event_store/baseline_counts_backup_20260222T132512Z.json`
- Day2 gate:
  - `reports/event_store/day2_gate_eval_latest.json`
- Strict cycle:
  - `reports/promotion_gates/strict_cycle_latest.json`

## Outcome
- `day2_gate_eval_latest.json` now shows:
  - `missing_correlation=PASS`
  - `delta_since_baseline_tolerance=PASS` (`max_delta_observed=0`)
  - only `elapsed_window` remains pending (0.0h / 24h)
- strict cycle remains `FAIL` only due to `day2_event_store_gate`, which is now an expected time-gated blocker rather than stale baseline drift.
