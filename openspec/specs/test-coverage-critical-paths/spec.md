## ADDED Requirements

### Requirement: Every trading-critical module has a dedicated test file
The following modules SHALL each have a corresponding test file with meaningful coverage (not just import smoke tests):

| Module | Required test file |
|---|---|
| `simulation/bridge/` (hb_bridge split) | `tests/simulation/test_bridge_*.py` |
| `controllers/sim_broker.py` | `tests/controllers/test_sim_broker.py` |
| Telemetry kernel module | `tests/controllers/test_kernel_telemetry.py` |
| Auto-calibration kernel module | `tests/controllers/test_kernel_calibration.py` |
| Risk guards kernel module | `tests/controllers/test_kernel_risk_guards.py` |
| Quoting kernel module | `tests/controllers/test_kernel_quoting.py` |

#### Scenario: sim_broker tested
- **WHEN** `pytest tests/controllers/test_sim_broker.py` is run
- **THEN** at least 5 test cases SHALL pass covering: order placement, fill generation, position tracking, fee calculation, error on invalid order

#### Scenario: risk_guards tested
- **WHEN** `pytest tests/controllers/test_kernel_risk_guards.py` is run
- **THEN** at least 8 test cases SHALL pass covering: gate activation, gate release, soft-pause trigger, drawdown limit, risk budget check, edge floor, cost floor, compound gate logic

### Requirement: Test files mirror source structure
Test directory structure SHALL mirror the source module structure:
- `hbot/simulation/` → `hbot/tests/simulation/`
- `hbot/platform/` → `hbot/tests/platform/`
- `hbot/controllers/runtime/kernel/` → `hbot/tests/controllers/test_kernel/`

#### Scenario: Simulation tests exist
- **WHEN** `ls hbot/tests/simulation/` is run
- **THEN** test files SHALL exist for `desk`, `matching_engine`, `portfolio`, and `bridge`

### Requirement: Error path testing
Every `except` block in hot-path code that was hardened (from `except Exception: pass` to typed handling) SHALL have at least one test that exercises the error path.

#### Scenario: Bridge Redis error tested
- **WHEN** Redis is unavailable during bridge initialization
- **THEN** a test SHALL verify that `BridgeError` is raised (not silently swallowed) and the bridge enters degraded mode

#### Scenario: Matching engine invalid order tested
- **WHEN** an order with zero quantity is submitted to the matching engine
- **THEN** a test SHALL verify that `MatchingEngineError` is raised with order context

### Requirement: Regression test count tracking
A `tests/architecture/test_coverage_minimums.py` SHALL enforce minimum test counts per critical module to prevent coverage erosion.

#### Scenario: Coverage minimum enforced
- **WHEN** someone deletes tests from `test_kernel_risk_guards.py` reducing count below 8
- **THEN** `test_coverage_minimums.py` SHALL fail
