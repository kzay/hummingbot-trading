## ADDED Requirements

### Requirement: Research worker runs as a dedicated Docker service
The system SHALL provide a `research-worker` Docker Compose service that hosts all research API routes on port 9920, isolated from the dashboard `realtime-ui-api` service.

#### Scenario: Research worker starts and responds to health checks
- **WHEN** the `research-worker` container starts
- **THEN** it SHALL respond to `GET /health` with `{"status": "ok"}` and HTTP 200

#### Scenario: Research worker serves research API routes
- **WHEN** a client sends `GET /api/research/candidates` to the research worker
- **THEN** the response SHALL be identical in schema to the existing research API response

### Requirement: Research routes removed from realtime-ui-api
The `realtime-ui-api` service SHALL NOT import or mount research routes. All `/api/research/*` traffic MUST be handled by the `research-worker` service.

#### Scenario: realtime-ui-api does not serve research endpoints
- **WHEN** a client sends `GET /api/research/candidates` directly to `realtime-ui-api:9910`
- **THEN** the response SHALL be HTTP 404

#### Scenario: Dashboard routes remain functional
- **WHEN** a client sends `GET /api/v1/state` to `realtime-ui-api:9910`
- **THEN** the response SHALL return the dashboard state payload as before

### Requirement: nginx routes research traffic to the research worker
The nginx reverse proxy SHALL route all requests matching `/api/research/` to `research-worker:9920` instead of `realtime-ui-api:9910`.

#### Scenario: Research request routed through nginx
- **WHEN** a client sends `GET /api/research/explorations` through the nginx frontend
- **THEN** the request SHALL be proxied to `research-worker:9920`

#### Scenario: Non-research API requests still routed to UI API
- **WHEN** a client sends `GET /api/v1/candles` through the nginx frontend
- **THEN** the request SHALL be proxied to `realtime-ui-api:9910`

### Requirement: Research worker has independent resource limits
The `research-worker` service SHALL have its own `deploy.resources.limits` in Docker Compose, independent of the `realtime-ui-api` limits.

#### Scenario: Research worker memory limit is sufficient for heavy backtests
- **WHEN** the `research-worker` service is defined in docker-compose.yml
- **THEN** its memory limit SHALL be at least 6144M and its CPU limit SHALL be at least 8.0

#### Scenario: UI API reverted to dashboard-appropriate resources
- **WHEN** the `realtime-ui-api` service is defined in docker-compose.yml
- **THEN** its memory limit SHALL be 1536M and its CPU limit SHALL be 1.0

### Requirement: Research worker uses the same Docker image as control plane
The `research-worker` service SHALL use the shared control-plane Docker image with a `command:` override that starts the dedicated research worker entry point.

#### Scenario: No new Docker image required
- **WHEN** the Docker Compose file is processed
- **THEN** the `research-worker` service SHALL reference the same image as other control-plane services (e.g., `realtime-ui-api`)

### Requirement: SSE log streams work through nginx to research worker
Long-lived SSE connections for exploration log streaming SHALL work correctly when proxied through nginx to the research worker.

#### Scenario: Exploration log SSE stream proxied correctly
- **WHEN** a client opens an SSE connection to `/api/research/explorations/{session_id}/log` through nginx
- **THEN** the connection SHALL remain open and deliver `event: iteration` and `event: done` messages until the session completes
