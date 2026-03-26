## ADDED Requirements

### Requirement: Empty packages removed
The empty `controllers/strategies/` directory SHALL be deleted.

#### Scenario: Directory does not exist
- **WHEN** `ls controllers/strategies/` is run
- **THEN** the command SHALL fail (directory does not exist)

### Requirement: Pure alias modules removed
`controllers/shared_mm_v24.py` (which only re-exports from `shared_runtime_v24`) SHALL be removed after its references are updated.

#### Scenario: File does not exist
- **WHEN** the refactoring is complete
- **THEN** `controllers/shared_mm_v24.py` SHALL NOT exist

### Requirement: Every Python package has a meaningful `__init__.py`
All `__init__.py` files SHALL either:
- Contain `__all__` exports defining the package's public API, OR
- Be empty with a module docstring explaining the package's purpose

#### Scenario: No content-free `__init__.py`
- **WHEN** `__init__.py` files are inspected
- **THEN** each SHALL contain either a docstring or `__all__` (or both)

### Requirement: Module docstrings on all public modules
Every non-test Python file SHALL have a module-level docstring (first string literal in the file) describing what the module does.

#### Scenario: Docstring check
- **WHEN** a non-test Python file is opened
- **THEN** it SHALL begin with a docstring (triple-quoted string)

### Requirement: `sys.path` hacks eliminated
The `services/monitoring/bot_metrics_exporter.py` shim that mutates `sys.path` SHALL be removed; the service SHALL use proper package imports instead.

#### Scenario: No sys.path manipulation
- **WHEN** `grep -r "sys.path" hbot/services/` is run
- **THEN** zero matches SHALL be returned (excluding test fixtures)

### Requirement: Stale `epp_v2_4.py` legacy wrapper clarified
`controllers/epp_v2_4.py` is documented in project rules as the "main controller (2300+ lines)" but is actually a small re-export shim. Project documentation SHALL be updated to reference `controllers/runtime/kernel/controller.py` as the real implementation.

#### Scenario: Project rules updated
- **WHEN** `.cursor/rules/project-context.mdc` is read
- **THEN** it SHALL reference `controllers/runtime/kernel/controller.py` (not `epp_v2_4.py`) as the main controller
