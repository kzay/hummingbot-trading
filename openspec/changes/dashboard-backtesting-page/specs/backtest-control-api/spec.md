## ADDED Requirements

### Requirement: Preset discovery endpoint
The system SHALL expose an authenticated endpoint that returns the list of available backtest presets by scanning the server-side allowlisted directory (e.g. `hbot/data/backtest_configs/*.yml`). Each entry SHALL include at minimum a canonical `id`, a human label, the strategy class name, trading pair, and resolution.

#### Scenario: Presets listed successfully
- **WHEN** an authenticated client requests the preset list
- **THEN** the system SHALL return a JSON array where each element contains `id`, `label`, `strategy`, `pair`, and `resolution` derived from parsing each YAML file

#### Scenario: New YAML added to directory
- **WHEN** an operator adds a new YAML file to the backtest configs directory and requests the preset list
- **THEN** the new preset SHALL appear in the response without a service restart

#### Scenario: Unauthenticated preset request
- **WHEN** a client calls the preset endpoint without valid credentials
- **THEN** the system SHALL return `401` or `403`

### Requirement: Job creation with allowlisted preset and safe overrides
The system SHALL expose an authenticated endpoint that starts a backtest when the client provides a valid `preset_id` and optional safe scalar overrides (`initial_equity`, `start_date`, `end_date`). The system SHALL NOT accept arbitrary `strategy_class` strings, raw YAML, or file paths from the client. Overrides SHALL be validated against server-defined ranges before applying to the loaded config.

#### Scenario: Valid preset starts a job
- **WHEN** an authenticated client sends `{ "preset_id": "bot1_baseline" }`
- **THEN** the system SHALL create a unique job id, start or enqueue execution of `BacktestHarness` with the loaded config, persist the job row to SQLite, and return `{ job_id, status }` with HTTP 200 or 202

#### Scenario: Valid preset with safe overrides
- **WHEN** the client sends `{ "preset_id": "bot1_baseline", "initial_equity": 1000, "start_date": "2025-02-01" }`
- **THEN** the system SHALL apply the overrides to the loaded `BacktestConfig`, validate ranges (e.g. equity 10–100000, date range ≤ max_days), and start the job with the modified config

#### Scenario: Override out of range
- **WHEN** the client sends `initial_equity` outside the allowed range
- **THEN** the system SHALL return `400` with a validation error and SHALL NOT start a job

#### Scenario: Unknown preset rejected
- **WHEN** the client sends a `preset_id` not in the allowlist
- **THEN** the system SHALL return `400` or `404` and SHALL NOT start a process

#### Scenario: Unauthenticated request rejected
- **WHEN** a client calls the create endpoint without valid credentials
- **THEN** the system SHALL return `401` or `403`

### Requirement: Job status with progress
The system SHALL expose a read endpoint that returns the current job status, a `progress_pct` field (0–100) while running, timestamps, and on completion the result summary (inline metrics or report path). Failed jobs SHALL include a safe error string.

#### Scenario: Running job reports determinate progress
- **WHEN** a client requests status for a running job
- **THEN** the response SHALL include `status: "running"`, `progress_pct` (numeric 0–100), `started_at`, and `updated_at`

#### Scenario: Completed job exposes result summary
- **WHEN** the harness finishes successfully
- **THEN** the response SHALL include `status: "completed"`, a `result_summary` object with at minimum `total_return_pct`, `sharpe_ratio`, `max_drawdown_pct`, `fill_count`, and `warnings`, plus paths to full report JSON and equity CSV

#### Scenario: Failed job reports error
- **WHEN** the harness raises or the worker exits with error
- **THEN** the response SHALL include `status: "failed"` and a safe `error` string; full traceback MAY remain server-side only

#### Scenario: Timed-out job
- **WHEN** a job exceeds `max_wall_time_s`
- **THEN** the worker SHALL be terminated and status SHALL be `timed_out` or `failed` with an appropriate error message

#### Scenario: Unknown job id
- **WHEN** a client requests status for a non-existent job_id
- **THEN** the system SHALL return `404`

### Requirement: SSE log streaming
The system SHALL expose an endpoint that streams log lines via Server-Sent Events (SSE, `text/event-stream`) while the job is running. After the job reaches a terminal state, the endpoint SHALL send remaining lines and close the stream. Each SSE event SHALL contain one or more log lines.

#### Scenario: Log lines stream during execution
- **WHEN** a client opens an SSE connection for a running job
- **THEN** new log lines SHALL be pushed to the client as they are written, without requiring the client to poll

#### Scenario: Stream completes on terminal state
- **WHEN** the job finishes (completed, failed, cancelled, timed_out)
- **THEN** the SSE stream SHALL send any remaining buffered lines and then close

#### Scenario: SSE reconnection
- **WHEN** the SSE connection drops and the client's `EventSource` reconnects
- **THEN** the system SHALL resume from the current position (or re-send the full log tail) without duplicate lines if the `Last-Event-ID` header is provided

#### Scenario: Unknown job id
- **WHEN** a client opens SSE for a non-existent job_id
- **THEN** the system SHALL return `404`

### Requirement: Job cancellation
The system SHALL expose an endpoint to cancel a running job. Cancellation SHALL terminate the worker process and set the job status to `cancelled`. Partial artifacts (log file, incomplete report) SHALL be retained.

#### Scenario: Cancel a running job
- **WHEN** a client sends a cancel request for a running job
- **THEN** the system SHALL send SIGTERM to the worker, wait briefly, SIGKILL if still alive, and set status to `cancelled`

#### Scenario: Cancel a non-running job
- **WHEN** a client sends a cancel request for a job that is already terminal
- **THEN** the system SHALL return `409` or `200` (idempotent) and SHALL NOT change the existing terminal status

### Requirement: Job history list
The system SHALL expose an endpoint that returns all jobs persisted in the SQLite store, sorted by creation date descending. Each entry SHALL include job_id, preset_id, status, created_at, and key result metrics (if completed).

#### Scenario: List with mixed statuses
- **WHEN** a client requests the job list
- **THEN** the response SHALL include completed, failed, cancelled, and running jobs with their respective fields populated

#### Scenario: Empty history
- **WHEN** no jobs have been created yet
- **THEN** the response SHALL return an empty array, not an error

### Requirement: Concurrency and timeout limits
The system SHALL enforce `max_concurrent_jobs` and `max_wall_time_s`. When limits are exceeded, new jobs SHALL be rejected with a clear message.

#### Scenario: Concurrent limit reached
- **WHEN** `max_concurrent_jobs` is 1 and one job is already running
- **THEN** a new create request SHALL return `429` with a message indicating the limit

#### Scenario: Timeout kills worker
- **WHEN** a job exceeds `max_wall_time_s`
- **THEN** the worker SHALL be terminated and job status SHALL reflect timeout

### Requirement: Job metadata persistence
All job metadata (id, preset, overrides, status, progress, timestamps, result summary, error, log/report paths) SHALL be persisted to SQLite so that job history survives API process restarts.

#### Scenario: API restarts mid-run
- **WHEN** the API process restarts while a job was running
- **THEN** the persisted job row SHALL still be queryable; the system SHALL detect the dead worker PID and mark the job `failed` with an appropriate error
