# Strategy Isolation Contract

## Objective
Prevent coupling between shared runtime and bot-specific strategies so a change
for one bot lane cannot alter strategy behavior for other lanes.

## Design Rules
- Shared/runtime code is strategy-agnostic:
  - `controllers/runtime/*`
  - `controllers/epp_v2_4.py`
  - `controllers/regime_detector.py`
  - `controllers/spread_engine.py`
  - `controllers/tick_emitter.py`
- Strategy logic lives only in `controllers/bots/*`.
- `controllers/strategies/*` is compatibility-only and should re-export bot lanes.
- Legacy `controllers/epp_v2_4_bot*` files are compatibility wrappers only.
- `controllers/market_making/*` is reserved for market-making loader shims only.

## Allowed Dependency Direction
1. `controllers/bots/*` -> `controllers/runtime/*` + generic services.
2. Legacy wrappers -> corresponding strategy lane module only.
3. Shared/runtime modules -> generic/shared modules only.

## Forbidden Dependencies
- Shared/runtime modules importing `controllers.bots.*`.
- One strategy lane importing another strategy lane.
- Strategy logic implemented in legacy wrapper files.
- Non-market-making strategy logic added under `controllers/market_making/`.

## Change Workflow
- Strategy-only change:
  - modify one lane file under `controllers/bots/`
  - keep other lanes untouched
  - keep shared runtime untouched unless interface change is intentional
- Shared runtime change:
  - modify only shared/runtime modules
  - run wrapper/strategy regression tests before merge

## Verification
- Boundary guard:
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_strategy_isolation_contract.py -q`
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_market_making_shim_contract.py -q`
- Regression subset:
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_epp_v2_4_bot5.py hbot/tests/controllers/test_epp_v2_4_bot6.py hbot/tests/controllers/test_epp_v2_4_bot7.py -q`
