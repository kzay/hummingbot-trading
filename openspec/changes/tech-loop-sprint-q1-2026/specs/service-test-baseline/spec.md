## ADDED Requirements

### Requirement: ops_scheduler has baseline unit tests
The `hbot/services/ops_scheduler/` module SHALL have a test file at `hbot/tests/services/test_ops_scheduler/test_main.py` with at least 3 test functions covering: initialization, scheduled task dispatch, and error handling for a failed task.

#### Scenario: Test file exists and passes
- **WHEN** `pytest hbot/tests/services/test_ops_scheduler/ -q` is executed
- **THEN** at least 3 tests SHALL pass with no failures

#### Scenario: Tests do not require running Redis or external services
- **WHEN** tests run on a clean host with no Redis instance
- **THEN** all tests SHALL pass using mocked dependencies

### Requirement: exchange_snapshot_service has baseline unit tests
The `hbot/services/exchange_snapshot_service/` module SHALL have a test file at `hbot/tests/services/test_exchange_snapshot_service/test_main.py` with at least 3 test functions covering: snapshot fetching, file writing, and error handling.

#### Scenario: Test file exists and passes
- **WHEN** `pytest hbot/tests/services/test_exchange_snapshot_service/ -q` is executed
- **THEN** at least 3 tests SHALL pass with no failures

#### Scenario: Tests mock exchange API calls
- **WHEN** tests execute snapshot fetching logic
- **THEN** all HTTP/exchange calls SHALL be mocked (no real network I/O)

### Requirement: shadow_execution service has baseline unit tests
The `hbot/services/shadow_execution/` module SHALL have a test file at `hbot/tests/services/test_shadow_execution/test_main.py` with at least 3 test functions covering: shadow order creation, position tracking, and divergence detection.

#### Scenario: Test file exists and passes
- **WHEN** `pytest hbot/tests/services/test_shadow_execution/ -q` is executed
- **THEN** at least 3 tests SHALL pass with no failures
