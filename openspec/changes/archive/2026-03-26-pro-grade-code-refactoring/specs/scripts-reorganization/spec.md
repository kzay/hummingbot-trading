## ADDED Requirements

### Requirement: Scripts organized into purpose-based sub-packages
The 116-file `scripts/` directory SHALL be organized into sub-packages:
- `scripts/ops/` — operational scripts (startup checks, health, deployment)
- `scripts/release/` — promotion gates, strict cycle, dev workflow
- `scripts/analysis/` — performance analysis, TCA reports, dashboards
- `scripts/backtest/` — backtest runners, sweep CLIs, preset sweeps
- `scripts/ml/` — ML dataset builders, training scripts
- `scripts/shared/` — shared harnesses and utilities (e.g. `v2_with_controllers.py`)

#### Scenario: No loose scripts at root
- **WHEN** `ls scripts/*.py` is run (excluding `__init__.py`)
- **THEN** zero Python files SHALL exist at the `scripts/` root — all SHALL be in sub-packages

#### Scenario: Each sub-package has `__init__.py`
- **WHEN** each listed sub-package is inspected
- **THEN** it SHALL contain an `__init__.py` (can be empty)

### Requirement: Shell scripts organized alongside Python
Shell scripts (`.sh`) currently at `scripts/` root SHALL be moved to the appropriate sub-package (e.g., deployment `.sh` files to `scripts/ops/`).

#### Scenario: No loose shell scripts
- **WHEN** `ls scripts/*.sh` is run
- **THEN** zero `.sh` files SHALL exist at the `scripts/` root

### Requirement: Import paths updated in all references
All Docker Compose commands, CI workflows, documentation, and other scripts that reference moved files SHALL be updated.

#### Scenario: Docker compose references valid
- **WHEN** `grep -r "scripts/" hbot/infra/compose/docker-compose.yml` is run
- **THEN** all script paths SHALL point to valid, existing files

### Requirement: Duplicate/redundant scripts consolidated
Scripts that duplicate logic (e.g., multiple variants of promotion gate runners) SHALL be consolidated or one SHALL be designated canonical with others removed.

#### Scenario: No functionally duplicate scripts
- **WHEN** the refactoring is complete
- **THEN** each script SHALL serve a unique purpose documented in its module docstring
