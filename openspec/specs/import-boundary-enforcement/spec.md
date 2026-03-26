## ADDED Requirements

### Requirement: Import boundary contract test exists
A pytest test at `tests/architecture/test_import_boundaries.py` SHALL enforce the following dependency rules:

| Source Layer | May Import From | SHALL NOT Import From |
|---|---|---|
| `platform/` | stdlib, third-party | `controllers`, `services`, `simulation`, `scripts` |
| `simulation/` | `platform/`, stdlib, third-party | `controllers`, `services`, `scripts` |
| `controllers/` | `platform/`, `simulation/`, stdlib, third-party | `services` (except via `hb_loader_shims/`) |
| `services/` | `platform/`, `simulation/`, `controllers/` (readonly), stdlib, third-party | other `services/*` packages (no cross-service imports) |
| `scripts/` | anything under `hbot/` | — |

#### Scenario: Contract test catches violations
- **WHEN** a developer adds `from services.common import X` inside `controllers/runtime/kernel/quoting.py`
- **THEN** `pytest tests/architecture/test_import_boundaries.py` SHALL fail with a clear error message naming the violation

#### Scenario: Clean codebase passes
- **WHEN** the contract test is run against the fully refactored codebase
- **THEN** zero violations SHALL be reported

### Requirement: Contract test uses AST parsing, not runtime imports
The boundary test SHALL use `ast.parse()` and `ast.walk()` to inspect import statements statically, without executing any module.

#### Scenario: Test runs without external dependencies
- **WHEN** `pytest tests/architecture/test_import_boundaries.py` is run in a minimal environment (no Redis, no HB)
- **THEN** the test SHALL pass or fail based solely on source code analysis

### Requirement: Baseline-aware enforcement
The contract test SHALL be aware of the pre-refactoring baseline (45 `controllers → services` violations). During phased execution, the allowed violation count SHALL be progressively tightened:
- After Phase 2 (platform extraction): ≤ 10 violations allowed
- After Phase 3 (simulation extraction): ≤ 5 violations allowed
- After all phases complete: 0 violations allowed

#### Scenario: Progressive tightening
- **WHEN** Phase 2 is complete and the contract test runs
- **THEN** it SHALL fail if more than 10 `controllers → services` violations exist (was 45 pre-refactoring)

#### Scenario: Final zero-tolerance
- **WHEN** all phases are complete
- **THEN** the contract test SHALL fail on any boundary violation with zero exceptions

### Requirement: Cross-service import prevention
No service package (`services/X/`) SHALL import from another service package (`services/Y/`). Shared code MUST go through `platform/` or `services/contracts/`.

#### Scenario: Service isolation verified
- **WHEN** the contract test scans all `services/*/` packages
- **THEN** no cross-service imports SHALL be found (excluding `services/common/`, `services/contracts/`, `services/hb_bridge/`)

### Requirement: CI integration
The import boundary test SHALL be included in the default `pytest` run and in the CI pipeline.

#### Scenario: CI catches regression
- **WHEN** a PR introduces a layer violation
- **THEN** CI SHALL fail before merge
