## ADDED Requirements

### Requirement: List all candidates with summary data

The system SHALL expose `GET /api/research/candidates` returning a JSON array of all strategy candidates found under `data/research/candidates/`. Each entry SHALL include: `name`, `hypothesis`, `adapter_mode`, `lifecycle` (current state from lifecycle manager), `best_score` (highest `total_score` across experiments, or `null`), `best_recommendation` (recommendation from the best-scoring evaluation, or `null`), and `experiment_count` (number of recorded experiments).

#### Scenario: Candidates exist
- **WHEN** the `data/research/candidates/` directory contains YAML files
- **THEN** the endpoint returns HTTP 200 with a JSON array, one entry per YAML file, sorted by `best_score` descending (nulls last)

#### Scenario: No candidates exist
- **WHEN** the `data/research/candidates/` directory is empty or missing
- **THEN** the endpoint returns HTTP 200 with an empty JSON array `[]`

#### Scenario: Malformed candidate YAML
- **WHEN** a YAML file in `data/research/candidates/` cannot be parsed
- **THEN** the endpoint skips that file and logs a warning; other candidates are still returned

---

### Requirement: Get candidate detail

The system SHALL expose `GET /api/research/candidates/{name}` returning the full candidate data plus evaluation history. The response SHALL include: all `StrategyCandidate` fields, the lifecycle state with full transition history, all experiment manifest entries (from the JSONL registry), and the path to the latest evaluation report.

#### Scenario: Candidate exists
- **WHEN** a valid candidate `name` is provided and a matching YAML file exists
- **THEN** the endpoint returns HTTP 200 with the full candidate detail JSON

#### Scenario: Candidate not found
- **WHEN** the `name` does not match any YAML file in `data/research/candidates/`
- **THEN** the endpoint returns HTTP 404 with `{"error": "Candidate not found"}`

---

### Requirement: Get evaluation report

The system SHALL expose `GET /api/research/reports/{candidate_name}/{run_id}` returning the Markdown evaluation report as plain text.

#### Scenario: Report exists
- **WHEN** the file `data/research/reports/{candidate_name}/{run_id}/report.md` exists
- **THEN** the endpoint returns HTTP 200 with `Content-Type: text/markdown` and the file contents

#### Scenario: Report not found
- **WHEN** the report file does not exist
- **THEN** the endpoint returns HTTP 404 with `{"error": "Report not found"}`

---

### Requirement: List exploration sessions

The system SHALL expose `GET /api/research/explorations` returning a JSON array of exploration sessions found under `data/research/explorations/`. Each entry SHALL include: `session_id` (directory name), `status` (`running` if no `session_result.json`, otherwise `completed`), `iteration_count`, `best_score`, `best_candidate`, and `created_at` (directory mtime).

#### Scenario: Sessions exist
- **WHEN** the `data/research/explorations/` directory contains session subdirectories
- **THEN** the endpoint returns HTTP 200 with a JSON array sorted by `created_at` descending

#### Scenario: No sessions exist
- **WHEN** the `data/research/explorations/` directory is empty or contains only `.gitkeep`
- **THEN** the endpoint returns HTTP 200 with an empty JSON array `[]`

---

### Requirement: Get exploration session detail

The system SHALL expose `GET /api/research/explorations/{session_id}` returning the full session result if completed, or the current iteration state if running.

#### Scenario: Completed session
- **WHEN** a `session_result.json` file exists in the session directory
- **THEN** the endpoint returns HTTP 200 with the parsed `SessionResult` JSON

#### Scenario: Running session
- **WHEN** no `session_result.json` exists but iteration YAML files are present
- **THEN** the endpoint returns HTTP 200 with `{"status": "running", "iterations": [...]}` listing each iteration's YAML filename and parsed score/recommendation if available

#### Scenario: Session not found
- **WHEN** the session directory does not exist
- **THEN** the endpoint returns HTTP 404 with `{"error": "Session not found"}`

---

### Requirement: Stream exploration session log via SSE

The system SHALL expose `GET /api/research/explorations/{session_id}/log` as a Server-Sent Events stream. The stream SHALL emit an `iteration` event each time a new iteration YAML file appears in the session directory, and a `done` event when `session_result.json` is created.

#### Scenario: Live session streaming
- **WHEN** a client connects to the SSE endpoint for a running session
- **THEN** the server emits `event: iteration` with `data:` containing the iteration number, candidate name, score, and recommendation as JSON for each new iteration file detected (poll interval 1 second)

#### Scenario: Session completes during streaming
- **WHEN** a `session_result.json` file appears while the client is connected
- **THEN** the server emits `event: done` with `data:` containing the final `SessionResult` summary and closes the stream

#### Scenario: Session already completed
- **WHEN** a client connects to the SSE endpoint for a session that already has `session_result.json`
- **THEN** the server emits all iteration events from the stored data, then emits `event: done` and closes

#### Scenario: Session not found
- **WHEN** the session directory does not exist
- **THEN** the endpoint returns HTTP 404 (not SSE)

---

### Requirement: Authentication

All `/api/research/*` endpoints SHALL use the same `auth_check(request)` mechanism as existing API endpoints. SSE endpoints SHALL accept the auth token via `?token=` query parameter (EventSource limitation).

#### Scenario: Valid token
- **WHEN** a request includes a valid auth token (header or query param)
- **THEN** the request is processed normally

#### Scenario: Missing or invalid token
- **WHEN** no token or an invalid token is provided
- **THEN** the endpoint returns HTTP 401
