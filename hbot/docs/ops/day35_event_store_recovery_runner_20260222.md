# Day 35 - Event-Store Recovery Runner + Strict Recheck (2026-02-22)

## Objective
- Remove manual friction in event-store blocker recovery.
- Ensure strict-cycle retries are reproducible from a single command.
- Stabilize test gate behavior when docker runtime image lacks `pytest`.

## Implemented
- New runner:
  - `scripts/release/recover_event_store_stack_and_strict_cycle.py`
  - Responsibilities:
    - check Docker daemon availability
    - `docker compose up -d` minimal external stack:
      - `redis`
      - `event-store-service`
      - `event-store-monitor`
      - `day2-gate-monitor`
    - wait for health status
    - run `run_strict_promotion_cycle.py`
    - persist report to `reports/recovery/latest.json`

- Test runner reliability fix:
  - `scripts/release/run_tests.py`
  - In `--runtime auto`, if docker execution fails due missing `pytest`, fallback to host runtime automatically.
  - Adds payload field: `fallback_reason` (e.g. `docker_runtime_missing_pytest`).

## Validation
- Recovery runner evidence:
  - `reports/recovery/recover_event_store_strict_20260222T132151Z.json`
  - compose startup succeeded; service state snapshot captured; strict-cycle output captured.
- Test runner fallback evidence:
  - `reports/tests/test_run_20260222T132229Z.json`
  - `status=pass`, `runtime_used=host`, `fallback_reason=docker_runtime_missing_pytest`
- Strict cycle re-run:
  - `reports/promotion_gates/strict_cycle_latest.json`
  - Current failure reduced to:
    - `day2_event_store_gate` only

## Outcome
- Runtime blocker diagnosis and retry path are now automated and repeatable.
- Gate failure surface improved from multiple blockers to one expected maturity blocker.
- Remaining blocker is policy/validation maturity:
  - `day2_event_store_gate` requires elapsed window and baseline-delta tolerance to pass.
