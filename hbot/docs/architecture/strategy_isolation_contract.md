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
- Legacy `controllers/epp_v2_4_bot*` files are compatibility wrappers only.
- `controllers/market_making/*` is reserved for market-making loader shims only.

## Runtime Family Hierarchy

```
SharedRuntimeKernel(MarketMakingControllerBase)    <- shared infrastructure
  ├── EppV24Controller(SharedRuntimeKernel)         <- MM-specific machinery
  │     └── SharedMmV24Controller                   <- alias for bot1
  │           └── Bot1BaselineV1Controller
  └── DirectionalRuntimeController(SharedRuntimeKernel)  <- directional stubs
        ├── Bot5IftJotaV1Controller
        ├── Bot6CvdDivergenceV1Controller
        └── Bot7AdaptiveGridV1Controller
```

- **SharedRuntimeKernel** is the shared base class in `shared_mm_v24.py`.
  It provides price buffer, risk limits, fill handling, logging, paper bridge,
  fee resolution, and OpsGuard. MM-specific methods use polymorphic `self._`
  dispatch, allowing subclasses to override them.
- **EppV24Controller** extends the kernel and provides full MM machinery
  (edge gate, PnL governor, selective quoting, alpha policy, adaptive spread
  knobs, auto-calibration, Kelly sizing).
- **DirectionalRuntimeController** extends the kernel directly (NOT through
  EppV24Controller), stubbing all MM-only methods to safe no-ops.
- Directional configs extend `DirectionalStrategyRuntimeV24Config`, which
  sets all MM-only enable flags to `False` by default.
- Canonical imports for new directional lanes:
  ```python
  from controllers.runtime.base import DirectionalStrategyRuntimeV24Config, DirectionalStrategyRuntimeV24Controller
  ```

## Allowed Dependency Direction
1. `controllers/bots/*` -> `controllers/runtime/*` + generic services.
2. Legacy wrappers -> corresponding strategy lane module only.
3. Shared/runtime modules -> generic/shared modules only.
4. Shared runtime kernel -> execution-family adapters under `controllers/runtime/*` only.

## Forbidden Dependencies
- Shared/runtime modules importing `controllers.bots.*`.
- One strategy lane importing another strategy lane.
- Strategy logic implemented in legacy wrapper files.
- Non-market-making strategy logic added under `controllers/market_making/`.
- Directional bots extending `StrategyRuntimeV24Controller` directly (must use `DirectionalStrategyRuntimeV24Controller`).
- Directional bot configs manually setting MM disable flags (handled by `DirectionalRuntimeConfig`).

## Runtime Event Identity Contract
- Bot-scoped telemetry/events must include stable routing identity:
  - `instance_name`
  - `connector_name`
  - `trading_pair`
- Fill telemetry must also include `order_id`.
- Control and governance streams must include stable producer identity:
  - `execution_intent`: `instance_name`, `controller_id`
  - `strategy_signal`: `instance_name`
  - `audit`: `instance_name`
- Event consumers must fail closed on ambiguous routes:
  - do not guess a controller when multiple controllers match
  - drop foreign-instance events rather than mapping them to local controllers
- Command paths must reject empty routing identity fields before mutating state.
- Producers must preflight identity using `services/contracts/event_identity.py`
  before publishing bot-scoped events.
- Additive metadata is allowed on v1 payloads for migration support:
  - `controller_contract_version`
  - `runtime_impl`
- Do not rename or repurpose `controller_id`, stream names, artifact namespaces,
  or daily-state prefixes during internal runtime extraction.

## Change Workflow
- Strategy-only change:
  - modify one lane file under `controllers/bots/`
  - keep other lanes untouched
  - keep shared runtime untouched unless interface change is intentional
- Shared runtime change:
  - modify only shared/runtime modules
  - keep family-specific execution semantics behind `controllers/runtime/market_making_core.py`, `controllers/runtime/directional_core.py`, or future family adapters
  - run wrapper/strategy regression tests before merge

## Verification
- Boundary guard:
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_strategy_isolation_contract.py -q`
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_market_making_shim_contract.py -q`
- Regression subset:
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_epp_v2_4_bot5.py hbot/tests/controllers/test_epp_v2_4_bot6.py hbot/tests/controllers/test_epp_v2_4_bot7.py -q`
  - `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_hb_bridge_event_isolation.py hbot/tests/controllers/test_hb_event_fire.py -q`
  - `PYTHONPATH=hbot python -m pytest hbot/tests/services/test_event_store.py hbot/tests/services/test_paper_exchange_service.py hbot/tests/services/test_event_identity.py hbot/tests/services/test_hb_event_publisher.py -q`
