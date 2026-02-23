# Day 38 - Deterministic Replay Regression First-Class Gate (2026-02-22)

## Objective
- Promote replay regression from a single-cycle check to a first-class critical gate with multi-window coverage.
- Keep deterministic repeatability enforced per window.

## Implemented
- New multi-window runner:
  - `scripts/release/run_replay_regression_multi_window.py`
- Gate integration:
  - `scripts/release/run_promotion_gates.py`
  - gate renamed to `replay_regression_first_class` (critical)
  - now uses `run_replay_regression_multi_window.py`
- CI pipeline alignment:
  - `scripts/release/run_ci_pipeline.py` now runs multi-window replay coverage before promotion gates.

## Coverage Contract
- Default windows:
  - `500,1000,2000` events
- For each window:
  - run replay regression cycle with `--repeat 2`
  - require cycle `status=pass`
  - require `deterministic_repeat_pass=true`

## Evidence
- `reports/replay_regression_multi_window/latest.json`
- `reports/replay_regression_multi_window/latest.md`
- Promotion evidence:
  - `reports/promotion_gates/latest.json` with `replay_regression_first_class`

## Validation
- `python scripts/release/run_replay_regression_multi_window.py --windows 500,1000,2000 --repeat 2`
- `python scripts/release/run_promotion_gates.py --ci`

## Outcome
- Replay regression is now a first-class promotion blocker with deterministic multi-window coverage.
