## ADDED Requirements

### Requirement: Simulation package lives at `hbot/simulation/`
The paper engine v2 library SHALL reside at `hbot/simulation/` as a standalone package independent of `controllers/`.

#### Scenario: Package structure
- **WHEN** the refactoring is complete
- **THEN** `hbot/simulation/__init__.py` EXISTS and exports `PaperDesk`, `MatchingEngine`, `Portfolio`, `RiskEngine`, and all public types

#### Scenario: No controller imports inside simulation
- **WHEN** any Python file under `hbot/simulation/` is analyzed
- **THEN** it SHALL NOT contain `from controllers` or `import controllers` statements

#### Scenario: HB bridge isolation
- **WHEN** `simulation/bridge/` modules are analyzed
- **THEN** only `simulation/bridge/hb_bridge.py` (or its successors) SHALL import from `hummingbot.*` — all other simulation modules remain HB-free

### Requirement: Backward-compatible re-export shim
During migration, `controllers/paper_engine_v2/__init__.py` SHALL re-export all public symbols from `simulation` so existing imports continue to work.

#### Scenario: Legacy import still resolves
- **WHEN** code uses `from controllers.paper_engine_v2.desk import PaperDesk`
- **THEN** the import SHALL succeed and return the same class as `from simulation.desk import PaperDesk`

#### Scenario: Deprecation warning emitted
- **WHEN** code imports via the legacy `controllers.paper_engine_v2` path
- **THEN** a `DeprecationWarning` SHALL be emitted indicating the new import path

### Requirement: All consumers updated
All production code (services, backtesting, runtime) SHALL import from `simulation` directly, not via the legacy shim.

#### Scenario: Services use new path
- **WHEN** `grep -r "controllers.paper_engine_v2" hbot/services/` is run
- **THEN** zero matches SHALL be returned

#### Scenario: Backtesting uses new path
- **WHEN** `grep -r "controllers.paper_engine_v2" hbot/controllers/backtesting/` is run
- **THEN** zero matches SHALL be returned

### Requirement: Files moved with git history
All 21 Python files from `controllers/paper_engine_v2/` SHALL be moved using `git mv` to preserve version history.

#### Scenario: Git log shows rename
- **WHEN** `git log --follow simulation/desk.py` is run
- **THEN** history SHALL trace back to the original `controllers/paper_engine_v2/desk.py` commits
