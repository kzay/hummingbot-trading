## ADDED Requirements

### Requirement: No Python file in the runtime kernel exceeds 800 lines
After the split, every file under `controllers/runtime/kernel/` SHALL be under 800 lines (including blank lines and comments).

#### Scenario: Line count check
- **WHEN** `wc -l controllers/runtime/kernel/*.py` is run
- **THEN** every file SHALL report fewer than 800 lines

### Requirement: `shared_runtime_v24.py` is replaced by kernel submodules
The 4,376-line `shared_runtime_v24.py` SHALL be decomposed into focused modules under `controllers/runtime/kernel/`:

- `startup.py` — initialization, config validation, daily state restore
- `quoting.py` — spread computation, order sizing, quote placement
- `risk_guards.py` — risk evaluation, gate checks, soft-pause logic
- `regime_bridge.py` — regime detection integration, spec overrides
- `paper_hooks.py` — PaperDesk bridge installation, paper-mode wiring
- `telemetry.py` — minute logging, heartbeat, metrics emission
- `state.py` — daily state, fill cache, position tracking
- `calibration.py` — auto-calibration, percentile calculations
- `controller.py` — `EppV24Controller` class composing all above

#### Scenario: EppV24Controller still importable from original path
- **WHEN** code uses `from controllers.shared_runtime_v24 import EppV24Controller`
- **THEN** the import SHALL succeed via a re-export shim

#### Scenario: All kernel modules import cleanly
- **WHEN** `python -c "from controllers.runtime.kernel import controller"` is run
- **THEN** no import errors SHALL occur

### Requirement: No circular imports between kernel modules
Kernel submodules SHALL have a strict DAG dependency: `controller.py` depends on all others; no other module depends on `controller.py`.

#### Scenario: Circular import detection
- **WHEN** each kernel module is imported individually in isolation
- **THEN** no `ImportError` or `AttributeError` from circular references SHALL occur

### Requirement: Existing mixins absorbed or delegated
Root-level mixins (`risk_mixin.py`, `position_mixin.py`, `fill_handler_mixin.py`, `telemetry_mixin.py`) SHALL be absorbed into the corresponding kernel module or converted to composition-based delegation.

#### Scenario: Mixin files removed from root
- **WHEN** the refactoring is complete
- **THEN** `controllers/risk_mixin.py`, `controllers/position_mixin.py`, `controllers/fill_handler_mixin.py`, and `controllers/telemetry_mixin.py` SHALL NOT exist as standalone files (their logic lives in kernel modules)

### Requirement: Behavioral equivalence
The split SHALL produce zero behavior changes. The `test_epp_v2_4_core.py` test suite SHALL show the exact same pass/fail results as the pre-refactoring baseline (129 passing, 1 pre-existing failure on `test_publish_bot_minute_snapshot_telemetry_falls_back_to_event_store_file`).

#### Scenario: Core test suite — no regressions
- **WHEN** `pytest tests/controllers/test_epp_v2_4_core.py -q` is run after the split
- **THEN** exactly the same 129 tests SHALL pass and exactly the same 1 test SHALL fail as before the split (the pre-existing `test_publish_bot_minute_snapshot_telemetry_falls_back_to_event_store_file` failure)

#### Scenario: No new failures in dependent suites
- **WHEN** `test_epp_v2_4_bot7_pullback.py`, `test_epp_v2_4_bot6.py`, `test_price_buffer.py`, and `test_hb_bridge_signal_routing.py` are run
- **THEN** the same tests that passed before the split SHALL still pass
