## Context

The research lab runs LLM-driven exploration sessions that spawn multi-hour backtests, parameter sweeps (6 parallel workers), and walk-forward analyses. These CPU- and memory-intensive workloads currently execute inside the `realtime-ui-api` container — a lightweight Starlette server also responsible for dashboard WebSocket streams, SSE, and REST endpoints.

A recent `combo_mm` backtest processing 1.6M+ simulated orders exhausted the container's 1.5GB memory limit, triggering an OOM kill that restarted the entire container and silently killed the exploration. Meanwhile, the desk has migrated from 1-minute to 15-minute trading resolution, but the research modules still default to 1m across prompts, session config, and orchestrator defaults.

### Current architecture

```
nginx :80
  └─ /api/* → realtime-ui-api :9910
                ├─ dashboard routes (state, candles, depth, fills, reviews, WS, SSE)
                ├─ backtest routes
                └─ research routes  ← heavy workload shares container
```

### Target architecture

```
nginx :80
  ├─ /api/research/* → research-worker :9920  (6GB RAM, 8 CPUs)
  └─ /api/*          → realtime-ui-api :9910  (1.5GB RAM, 1 CPU)
```

## Goals / Non-Goals

**Goals:**
- Isolate research workloads so an OOM or CPU saturation in research never impacts the dashboard.
- Provide the research worker with generous, independently tunable resource limits.
- Switch all research modules to 15m resolution by default, matching the current desk configuration.
- Keep resolution configurable so the LLM or user can propose other timeframes when a hypothesis requires it.
- Zero frontend changes — nginx handles the rerouting transparently.

**Non-Goals:**
- Persistent job queue or database-backed exploration state. The file-based subprocess model is sufficient for now.
- Multi-node distribution of research workers.
- Changing the backtest API location (it stays in `realtime-ui-api`).
- Modifying the `explore_cli.py` module or the 6-step evaluation pipeline logic.

## Decisions

### D1: Dedicated Docker service with its own Starlette server

**Choice**: Create `hbot/services/research_worker/main.py` — a minimal Starlette/uvicorn server (~40 lines) that imports and mounts `create_research_routes` from the existing `research_api.py` module, listens on port `9920`, and has its own `/health` endpoint.

**Why not just scale `realtime-ui-api`**: The dashboard API is stateful (WebSocket subscribers, SSE streams, RealtimeState in-memory). Running multiple replicas would require shared state infrastructure. Separating the stateless research workload is simpler and directly addresses the resource contention.

**Why not a completely separate codebase**: `research_api.py` already has clean boundaries — `create_research_routes()` is a factory function that returns a route list. It imports no dashboard state. We reuse it by importing it into the new server.

### D2: nginx-level routing split

**Choice**: Add a `location /api/research/` block in `nginx.conf` that proxies to `research-worker:9920`, placed *before* the catch-all `location /api/` block.

**Why not application-level proxy**: nginx is already the entry point, handles connection upgrades (for SSE), and Docker DNS resolution. Adding one location block is the simplest path.

### D3: Resolution as SessionConfig fields

**Choice**: Add `resolution: str = "15m"` and `step_interval_s: int = 900` to `SessionConfig`. All downstream code (`exploration_session.py`, `experiment_orchestrator.py`) reads these fields instead of hardcoded values. Prompts reference `15m` as the default but explicitly tell the LLM it may propose other resolutions.

**Why not env vars**: Resolution is a per-session property that the LLM or user may want to override. SessionConfig is the right scope.

### D4: Reuse `control-plane-image` for the research worker

**Choice**: The `research-worker` Docker service uses the same `control-plane-image` that `realtime-ui-api` uses. This image already has all Python dependencies (anthropic, yaml, etc.) and the full `hbot/` PYTHONPATH.

**Why**: No new Docker image to build or maintain. The `command:` override in compose selects the entry point.

## Migration Plan

1. Add the new `research-worker` server and extract route mounting from `realtime-ui-api` without changing the frontend client.
2. Update nginx so `/api/research/*` is routed to `research-worker:9920` while all other `/api/*` traffic continues to hit `realtime-ui-api:9910`.
3. Add the new Compose service with the shared control-plane image, repo mounts, env file, and higher resource limits; then restore `realtime-ui-api` to dashboard-sized limits.
4. Update the research defaults from `1m` / `60` to `15m` / `900` in `SessionConfig`, prompts, and orchestrator fallbacks.
5. Extend the existing research controller tests to lock in the new defaults before deployment.
6. Validate routing, health checks, SSE log streaming, and a smoke exploration end-to-end.

## Open Questions

- No blocking questions for implementation.
- Follow-up question for a later change: if dashboard-triggered backtests grow materially heavier, should the backtest API follow the same extraction pattern as research?

## Risks / Trade-offs

- **[Risk] Research worker container OOM on extremely large backtests** → Mitigation: 6GB limit is 4x what caused the OOM. Monitor and increase if needed. The separation means only research dies, not the dashboard.

- **[Risk] nginx routing order matters** → Mitigation: `location /api/research/` is a longer prefix match and will naturally take priority over `location /api/`. Place it first for clarity.

- **[Risk] SSE streams for exploration logs go through nginx to a different backend** → Mitigation: The existing `proxy_read_timeout 86400s` configuration handles long-lived connections. The SSE log endpoint already works through nginx today.

- **[Risk] `research_api.py` imported by two different servers** → Mitigation: The module is stateless except for in-memory `_exploration_meta` dict. Since each server runs in its own container, there's no shared-state conflict. The file-based `session_meta.json` provides persistence across restarts.

- **[Trade-off] Backtest API stays in `realtime-ui-api`** → This is acceptable for now. Backtests launched from the dashboard are typically short-lived and do not have the same resource profile as multi-hour explorations. If backtests grow heavier, they can follow the same extraction pattern later.
