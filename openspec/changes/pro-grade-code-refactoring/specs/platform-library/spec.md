## ADDED Requirements

### Requirement: Shared library at `hbot/platform/`
Shared utilities consumed by both controllers and services SHALL reside in `hbot/platform/`, not in `services/common/`.

#### Scenario: Package exists with public API
- **WHEN** `from platform import MarketDataPlane` is run
- **THEN** the import SHALL succeed

#### Scenario: Platform has no upward dependencies
- **WHEN** any file under `hbot/platform/` is analyzed
- **THEN** it SHALL NOT import from `controllers`, `services`, `simulation`, `scripts`, or `tests`

### Requirement: `services/common/` becomes re-export shim
After migration, `services/common/__init__.py` SHALL re-export from `platform/` for backward compatibility.

#### Scenario: Legacy service imports still work
- **WHEN** code uses `from services.common.market_data_plane import MarketDataPlane`
- **THEN** the import SHALL succeed via the re-export shim

#### Scenario: Deprecation warning on legacy path
- **WHEN** importing via `services.common.*`
- **THEN** a `DeprecationWarning` SHALL be emitted

### Requirement: Controllers import from platform, not services
All controller modules that currently import `services.common.*` SHALL be updated to import from `platform.*`.

#### Scenario: No controller→services.common imports
- **WHEN** `grep -r "from services.common\|import services.common" hbot/controllers/` is run
- **THEN** zero matches SHALL be returned after the refactoring

### Requirement: Platform modules categorized by concern
`hbot/platform/` SHALL contain sub-packages organized by concern:
- `platform/market_data/` — market data plane, data helpers
- `platform/execution/` — execution gateway protocols, order types
- `platform/redis/` — Redis client, stream helpers
- `platform/time/` — timestamps, scheduling, interval helpers
- `platform/logging/` — structured logging, formatters
- `platform/contracts/` — shared data contracts (types, enums, protocols)

#### Scenario: Sub-package structure exists
- **WHEN** the refactoring is complete
- **THEN** each listed sub-package SHALL have an `__init__.py` with `__all__` exports
