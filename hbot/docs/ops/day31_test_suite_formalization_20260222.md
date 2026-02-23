# Day 31 - Test Suite Formalization + Gate Integration

## Scope
- Add a single deterministic test runner.
- Produce machine + operator artifacts for each run.
- Make test PASS/FAIL a critical promotion blocker.

## Implemented
- New runner:
  - `scripts/release/run_tests.py`
  - runs test groups:
    - `unit`
    - `service`
    - `integration`
  - coverage scope:
    - `controllers`
    - `services`
  - default coverage floor:
    - `--cov-fail-under=5.0` (gate integration default; raise via `--cov-fail-under` for tighter enforcement)
  - artifacts:
    - `reports/tests/latest.json`
    - `reports/tests/latest.md`
    - `reports/tests/coverage.xml`
    - `reports/tests/coverage.json`
- Promotion gate integration:
  - `scripts/release/run_promotion_gates.py`
  - new critical gate: `unit_service_integration_tests`
- Contract update:
  - `docs/validation/promotion_gate_contract.md`
- Reproducible image deps updated for test tooling:
  - `compose/images/control_plane/requirements-control-plane.txt`
  - added `pytest==8.4.2`, `pytest-cov==7.0.0`

## Outcome
- Test execution is now deterministic and artifacted.
- Any test or coverage failure blocks promotion automatically.

## Validation Evidence
- Test runner PASS:
  - `reports/tests/test_run_20260222T130243Z.json` (`status=pass`, `rc=0`)
- Promotion gate after integration:
  - `reports/promotion_gates/promotion_gates_20260222T130248Z.json`
  - `unit_service_integration_tests=PASS`
  - overall gate still `FAIL` due to `event_store_integrity_freshness` (separate freshness blocker)

## Code Fix During Validation
- `services/hb_bridge/intent_consumer.py`
  - fixed duplicate intent handling within the same poll batch (`seen_in_batch`) to satisfy deterministic idempotency behavior expected by `tests/services/test_intent_idempotency.py`.
