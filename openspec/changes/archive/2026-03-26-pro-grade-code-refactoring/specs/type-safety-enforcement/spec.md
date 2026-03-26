## ADDED Requirements

### Requirement: Return type annotations on all public methods in core modules
Every public method (not starting with `_`) in the following modules SHALL have explicit return type annotations:
- `controllers/runtime/kernel/*.py` (all kernel modules)
- `simulation/*.py` (all simulation modules)
- `platform/*.py` (all platform modules)

#### Scenario: Kernel controller methods annotated
- **WHEN** `controllers/runtime/kernel/controller.py` is analyzed with `mypy --strict`
- **THEN** no "missing return type" errors SHALL be reported for public methods

#### Scenario: Simulation public API annotated
- **WHEN** `simulation/__init__.py` exports are inspected
- **THEN** every exported function/class SHALL have full type signatures

### Requirement: Eliminate `Any` from core trading decision paths
`Any` type annotations SHALL NOT appear in modules that make trading decisions (quoting, risk, position sizing, fill handling). Acceptable exceptions: third-party library return types that genuinely return `Any`.

#### Scenario: No Any in quoting
- **WHEN** `grep "Any" controllers/runtime/kernel/quoting.py` is run
- **THEN** zero matches SHALL be returned (excluding comments)

#### Scenario: No Any in risk guards
- **WHEN** `grep "Any" controllers/runtime/kernel/risk_guards.py` is run
- **THEN** zero matches SHALL be returned (excluding comments)

### Requirement: Strict mypy configuration for critical modules
A `mypy.ini` or `pyproject.toml [tool.mypy]` section SHALL define strict checking for:
- `controllers/runtime/kernel/`
- `simulation/`
- `platform/`

With settings: `disallow_untyped_defs = True`, `disallow_any_explicit = True`, `warn_return_any = True`

#### Scenario: mypy strict passes on kernel
- **WHEN** `mypy --strict controllers/runtime/kernel/` is run
- **THEN** zero errors SHALL be reported

### Requirement: Decimal enforcement in monetary calculations
All price, quantity, PnL, fee, and notional calculations SHALL use `Decimal`. `float()` casts are permitted ONLY for:
- JSON serialization (telemetry, logging, API responses)
- Prometheus metric values
- Display formatting

Each permitted `float()` on a monetary value SHALL have an inline comment: `# float: serialization-only`

#### Scenario: No unmarked float casts on money
- **WHEN** `float(` appears on a line containing price/pnl/fee/quantity variable names in kernel modules
- **THEN** the line SHALL contain `# float: serialization-only` comment

### Requirement: `# type: ignore` budget
The total count of `# type: ignore` directives across `controllers/`, `simulation/`, and `platform/` SHALL NOT exceed 10 (down from ~25 pre-refactoring). Each remaining one SHALL include a reason: `# type: ignore[specific-error] -- reason`

#### Scenario: type-ignore count check
- **WHEN** `grep -r "type: ignore" hbot/controllers/ hbot/simulation/ hbot/platform/` is run
- **THEN** fewer than 10 matches SHALL be returned, and each SHALL have a reason comment
