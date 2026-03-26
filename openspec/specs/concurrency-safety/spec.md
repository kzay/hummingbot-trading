## ADDED Requirements

### Requirement: Mutable singletons documented with access contract
Every module-level mutable object in `simulation/` and `controllers/runtime/` SHALL have a docstring or comment specifying:
- Thread-safety guarantee (single-threaded, asyncio-only, or thread-safe)
- Owner (which component creates/owns the instance)
- Lifecycle (when created, when destroyed)

#### Scenario: Bridge state documented
- **WHEN** `simulation/bridge/` defines `_bridge_state` or equivalent
- **THEN** it SHALL have a docstring stating: access contract (single-threaded asyncio), owner (PaperDeskBridge), lifecycle (created at bridge init, destroyed at bridge stop)

#### Scenario: Runtime kernel state documented
- **WHEN** `controllers/runtime/kernel/state.py` defines mutable state objects
- **THEN** each SHALL have a docstring specifying the access contract

### Requirement: Runtime assertion guards on critical singletons
Mutable singletons that MUST be accessed from a single thread/event-loop SHALL have a runtime check (debug-mode assertion) that detects cross-thread access.

#### Scenario: Bridge state access guard
- **WHEN** `_bridge_state` is accessed from a thread other than the creating thread (detectable via `threading.current_thread()` comparison)
- **THEN** an `AssertionError` SHALL be raised in debug mode (`__debug__` is True)

### Requirement: No unprotected global mutable state outside singletons
Module-level mutable dicts, lists, or sets that are NOT part of a documented singleton pattern SHALL be converted to:
- Class-level attributes (scoped to instance lifecycle), OR
- `threading.local()` storage, OR
- Immutable constants (frozen sets, tuples)

#### Scenario: No stray module-level mutables
- **WHEN** AST analysis scans for module-level `Dict`, `List`, or `Set` assignments in `simulation/` and `controllers/runtime/`
- **THEN** each SHALL be either: (a) documented as a singleton with access contract, (b) a constant (`UPPER_CASE` naming), or (c) type-annotated as `Final`

### Requirement: Resource cleanup on all long-lived handles
All file handles, database connections, and Redis clients opened by long-running processes SHALL be closed in a `finally` block, `__aexit__`, or registered with `atexit`.

#### Scenario: sim_broker CSV handle cleanup
- **WHEN** `sim_broker.stop()` is called (or the process exits)
- **THEN** the CSV file handle SHALL be closed (verified by `_csv_file.closed == True`)

#### Scenario: Bridge Redis cleanup
- **WHEN** the bridge is stopped
- **THEN** all Redis connections SHALL be closed and the connection pool SHALL be released
