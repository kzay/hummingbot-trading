## ADDED Requirements

### Requirement: Zero `print()` in production code
All `print()` statements in `controllers/` and `services/` SHALL be replaced with structured `logger.*` calls. CLI scripts (`scripts/`) MAY use `print()` for user-facing output.

#### Scenario: No print in controllers
- **WHEN** `grep -rn "print(" hbot/controllers/` is run (excluding `__pycache__`)
- **THEN** zero matches SHALL be returned

#### Scenario: No print in services
- **WHEN** `grep -rn "print(" hbot/services/` is run (excluding `__pycache__`)
- **THEN** zero matches SHALL be returned

### Requirement: Structured logging with context fields
All logger calls in trading-critical paths SHALL include structured context via `extra={}` or `logger.bind()`:
- Fill events: `order_id`, `price`, `quantity`, `side`
- Risk decisions: `gate_reason`, `edge_pct`, `risk_level`
- Bridge events: `event_type`, `connector`, `timestamp`

#### Scenario: Fill logging includes order context
- **WHEN** a fill event is logged in `fill_handler_mixin.py` (or its kernel successor)
- **THEN** the log message SHALL include `order_id` and `fill_price` in structured fields

### Requirement: Logger per module, not per class
Each Python module SHALL define its own logger at module level: `logger = logging.getLogger(__name__)`. Class-level or function-level logger instantiation SHALL NOT be used.

#### Scenario: Module-level logger in kernel modules
- **WHEN** any `controllers/runtime/kernel/*.py` file is inspected
- **THEN** it SHALL contain exactly one `logger = logging.getLogger(__name__)` at module level

### Requirement: No f-string in logger calls
Logger calls SHALL use `%s` formatting (lazy evaluation), not f-strings, to avoid string construction when the log level is disabled.

#### Scenario: Lazy formatting
- **WHEN** `grep -rn 'logger.*f"' hbot/controllers/ hbot/services/` is run
- **THEN** zero matches SHALL be returned in newly written/modified code
