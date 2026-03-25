## MODIFIED Requirements

### Requirement: Reconciliation service connects to Redis with authentication
The `reconciliation-service` in `docker-compose.yml` SHALL include `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD` environment variables matching the Redis service credentials. The `RedisStreamClient` in `reconciliation_service/main.py` SHALL successfully authenticate on startup.

#### Scenario: Service publishes reconciliation events to Redis
- **WHEN** the reconciliation service starts and completes a reconciliation cycle
- **THEN** it SHALL successfully publish at least one event to the configured Redis stream without `NOAUTH` errors

#### Scenario: Service logs auth failure clearly
- **WHEN** the reconciliation service starts with an incorrect `REDIS_PASSWORD`
- **THEN** it SHALL log a `CRITICAL`-level message indicating Redis authentication failure within 10 seconds

## ADDED Requirements

### Requirement: Architecture tests runnable in Docker via test-runner service
A `test-runner` compose service SHALL exist under the `test` profile that mounts the full `hbot/` tree (including `tests/`) and can execute `pytest hbot/tests/architecture/ -q` successfully.

#### Scenario: Architecture tests pass in container
- **WHEN** `docker compose --profile test run test-runner pytest hbot/tests/architecture/ -q` is executed
- **THEN** all architecture contract tests SHALL pass with exit code 0

#### Scenario: Test runner does not start by default
- **WHEN** `docker compose up` is run without the `--profile test` flag
- **THEN** the `test-runner` service SHALL NOT start

### Requirement: Dependency versions aligned across requirement files
Shared libraries (`redis`, `pydantic`, `numpy`) SHALL have identical pinned versions in `requirements-control-plane.txt` and `requirements-ml-feature-service.txt`.

#### Scenario: Version consistency check
- **WHEN** both requirement files are compared for `redis`, `pydantic`, and `numpy`
- **THEN** the pinned versions SHALL match exactly
