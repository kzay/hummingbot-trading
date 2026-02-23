# Day 37 - Formal CI Pipeline (2026-02-22)

## Objective
- Deliver a formal, repeatable CI entrypoint for per-push validation on a self-hosted runner.
- Ensure CI executes tests, regression replay, and promotion gates with evidence artifacts.

## Implemented
- CI orchestration script:
  - `scripts/release/run_ci_pipeline.py`
- Workflow:
  - `.github/workflows/day37_formal_ci_pipeline.yml`

## Pipeline Contract
1. Tests:
   - `run_tests.py` (`unit,service,integration`)
2. Regression:
   - `run_replay_regression_cycle.py --repeat 2 --min-events 1000`
3. Gates:
   - `run_promotion_gates.py --ci --skip-replay-cycle`

## Evidence
- `reports/ci_pipeline/latest.json`
- `reports/ci_pipeline/latest.md`
- Plus upstream evidence:
  - `reports/tests/latest.json`
  - `reports/replay_regression/latest.json`
  - `reports/promotion_gates/latest.json`

## Validation
- Dry-run command (local structure check):
  - `python scripts/release/run_ci_pipeline.py --dry-run --tests-runtime host`

## Outcome
- Day 37 baseline is delivered with a self-hosted workflow and a single deterministic CI command path.
