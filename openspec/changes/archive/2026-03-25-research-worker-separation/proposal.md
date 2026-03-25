## Why

The research lab runs heavy workloads (LLM exploration sessions, multi-hour backtests, parameter sweeps with 6 parallel workers) inside the `realtime-ui-api` container. This container is also the dashboard API serving health checks, WebSocket streams, SSE, and REST endpoints. An OOM crash during a backtest (1.6M+ simulated orders exhausting 1.5GB RAM) kills the entire dashboard. CPU contention from sweep workers starves the API. Research and dashboard concerns must be separated.

Additionally, the exploration system hardcodes `1m` resolution across prompts, market context, and backtest defaults. The desk has moved to 15m trading with higher-timeframe analysis. The research lab must reflect this decision.

## What Changes

- Extract research API routes and subprocess management into a dedicated `research-worker` Docker service with its own generous resource limits (6GB RAM, 8 CPUs).
- Remove research routes from `realtime-ui-api` and revert its resources to dashboard-appropriate levels (1.5GB RAM, 1 CPU).
- Route `/api/research/*` requests through nginx to the new `research-worker` service instead of `realtime-ui-api`.
- Switch the default backtest resolution from `1m` to `15m` across all research modules (prompts, session config, orchestrator defaults).
- Make resolution configurable via `SessionConfig` so the LLM or user can still propose other resolutions when a hypothesis requires it.

## Capabilities

### New Capabilities
- `research-worker-service`: Dedicated Docker service for research workloads — runs exploration subprocesses, serves research API routes, isolated resource limits.
- `configurable-resolution`: Resolution and step interval as first-class `SessionConfig` fields with 15m defaults, propagated through prompts, market context, and orchestrator.

### Modified Capabilities
- None.

## Impact

- **Docker Compose**: New `research-worker` service added; `realtime-ui-api` resource limits reverted.
- **nginx.conf**: New `location /api/research/` upstream block routing to `research-worker:9920`.
- **`services/research_worker/main.py`**: New minimal Starlette server hosting research routes and health checks.
- **`realtime_ui_api/main.py`**: Research route imports and mounting removed.
- **`realtime_ui_api/research_api.py`**: Route factory reused by the dedicated worker; stale hosting comments updated.
- **`research/exploration_session.py`**: `SessionConfig` gains `resolution` and `step_interval_s` fields; 4 hardcoded `"1m"` references replaced with config values.
- **`research/exploration_prompts.py`**: 6 hardcoded `"1m"` / `step_interval_s: 60` references updated to `15m` / `900`.
- **`research/experiment_orchestrator.py`**: Default fallback resolution changed from `"1m"` to `"15m"`, step interval from `60` to `900`.
- **Frontend**: No changes — `researchApi.ts` already uses `apiBase` which resolves through nginx.
