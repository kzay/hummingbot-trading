## MODIFIED Requirements

### Requirement: Function length guardrails
No single function in `hbot/controllers/`, `hbot/services/`, `hbot/simulation/`, or `hbot/platform_lib/` SHALL exceed 100 lines of executable code (excluding blank lines and comments). Functions currently exceeding this limit SHALL be decomposed into focused helper methods.

#### Scenario: Kernel __init__ decomposition
- **WHEN** `SharedRuntimeKernel.__init__` (currently ~354 lines) is reviewed
- **THEN** it SHALL be decomposed into `_setup_config()`, `_setup_streams()`, `_setup_telemetry()`, and `_setup_mixins()` helpers, each under 100 lines

#### Scenario: _compute_adaptive_spread_knobs decomposition
- **WHEN** `SharedRuntimeKernel._compute_adaptive_spread_knobs` (currently ~216 lines) is reviewed
- **THEN** it SHALL be decomposed into at least 2 helper methods (e.g., `_compute_volatility_adjustment()`, `_compute_inventory_skew()`)

#### Scenario: _compute_alpha_policy decomposition
- **WHEN** `QuotingMixin._compute_alpha_policy` (currently ~136 lines) is reviewed
- **THEN** it SHALL be decomposed into at least 2 helper methods

### Requirement: Bare except blocks have justification
Every `except Exception: pass` block in production code (`hbot/controllers/`, `hbot/services/`, `hbot/simulation/`, `hbot/platform_lib/`) SHALL either:
1. Be narrowed to a specific exception type, OR
2. Include a `# Justification: <reason>` comment explaining why the broad catch is necessary.

#### Scenario: Audit compliance
- **WHEN** the codebase is searched for `except Exception` followed by `pass` without a justification comment
- **THEN** zero matches SHALL be found in production code directories

## ADDED Requirements

### Requirement: File length guardrails
No single file in `hbot/controllers/runtime/kernel/` SHALL exceed 600 lines. Files currently exceeding this limit SHALL be refactored by extracting helper modules or splitting responsibilities.

#### Scenario: controller.py size reduction
- **WHEN** `controller.py` (currently 1032 lines) is reviewed
- **THEN** it SHALL be reduced to under 600 lines by extracting initialization and computation helpers into dedicated modules (e.g., `_init_helpers.py`, `_spread_helpers.py`)
