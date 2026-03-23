## ADDED Requirements

### Requirement: Adapter registry maps mode strings to adapter/config classes
A declarative `ADAPTER_REGISTRY` dict in `controllers/backtesting/adapter_registry.py` SHALL map each `adapter_mode` string to its module path, adapter class name, and config class name.

#### Scenario: All existing modes are registered
- **WHEN** the registry is loaded
- **THEN** it contains entries for: `atr_mm`, `atr_mm_v2`, `smc_mm`, `combo_mm`, `pullback`, `pullback_v2`, `momentum_scalper`, `directional_mm`, `simple` (9 standard modes plus a standalone `_RUNTIME_ENTRY` for `runtime`)

#### Scenario: Adding a new adapter
- **WHEN** a developer creates a new adapter file (e.g., `new_adapter.py`)
- **THEN** they only need to add one entry to `ADAPTER_REGISTRY` and the harness supports the new adapter mode

### Requirement: Behavior-preserving config hydration
A `hydrate_config()` function SHALL convert YAML values to the correct Python type. The hydration MUST produce identical results to the existing per-adapter hydration loops in the original `_build_adapter()`.

Two hydration paths are supported:
- **Explicit**: Uses `decimal_attrs`, `int_attrs`, `bool_attrs` tuples from the entry — preferred for non-frozen configs where the original code used explicit type lists.
- **Introspect**: Falls back to inspecting the config dataclass default value types — used for configs that used `isinstance(getattr(...))` style checks.

#### Scenario: Decimal field hydration
- **WHEN** a YAML config specifies `spread_atr_mult: 1.5` and the config dataclass field defaults to `Decimal("1.0")`
- **THEN** the hydrated config has `spread_atr_mult == Decimal("1.5")`

#### Scenario: Bool field hydration — string safety
- **WHEN** a YAML config specifies `vol_sizing_enabled: true` and the config dataclass field defaults to `False`
- **THEN** the hydrated config has `vol_sizing_enabled == True`

#### Scenario: Bool field hydration — string "false" safety
- **WHEN** a YAML config specifies `some_flag: "false"` (as a YAML string, not bool)
- **THEN** the hydrated config has `some_flag == False` (not `bool("false")` which would be `True`)

#### Scenario: Frozen and non-frozen dataclass compatibility
- **WHEN** a config dataclass is frozen, `is_frozen=True` is set in its registry entry
- **THEN** the hydration function uses `object.__setattr__()` to set values
- **WHEN** a config dataclass is non-frozen (e.g., `PullbackAdapterConfig`, `MomentumScalperConfig`)
- **THEN** `is_frozen` defaults to `False` and hydration uses standard `setattr()`

### Requirement: _build_adapter() delegates to the registry
The `_build_adapter()` method in `harness.py` SHALL be reduced to fewer than 50 lines by delegating to the adapter registry.

#### Scenario: harness.py method size
- **WHEN** `_build_adapter()` is measured
- **THEN** it contains fewer than 50 lines of code (actual: 20 lines)

### Requirement: Runtime adapter mode handled as special case
The `runtime` adapter mode SHALL be handled with a dedicated `_build_runtime_adapter` function because it requires loading a strategy class and has a different constructor signature (`strategy=` argument). Its config hydration delegates to `hydrate_config()` via a standalone `_RUNTIME_ENTRY` with explicit attribute lists.

#### Scenario: Runtime adapter still works
- **WHEN** `adapter_mode` is `"runtime"`
- **THEN** the strategy is loaded via `_load_strategy()` and passed to `BacktestRuntimeAdapter`

#### Scenario: Runtime config hydration uses registry
- **WHEN** runtime adapter config is hydrated
- **THEN** `hydrate_config()` is called with `_RUNTIME_ENTRY` for consistent type conversion and `_safe_bool()` protection

### Requirement: All existing backtesting tests pass without changes
The adapter registry refactoring SHALL NOT change any adapter behavior. All existing tests in `tests/controllers/test_backtesting/` SHALL pass without modification.

#### Scenario: Test suite passes
- **WHEN** `pytest hbot/tests/controllers/test_backtesting/ -x -q` is run
- **THEN** all tests pass with exit code 0
