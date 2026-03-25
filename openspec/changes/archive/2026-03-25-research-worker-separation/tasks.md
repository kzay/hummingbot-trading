## 1. Research Worker Service

- [x] 1.1 Create `hbot/services/research_worker/__init__.py` (empty)
- [x] 1.2 Create `hbot/services/research_worker/main.py` — minimal Starlette/uvicorn server that imports `create_research_routes` from `research_api`, mounts routes, adds `/health` endpoint, listens on port 9920
- [x] 1.3 Remove `from services.realtime_ui_api.research_api import create_research_routes` import and `*research_routes` from the route list in `hbot/services/realtime_ui_api/main.py`
- [x] 1.4 Update `hbot/services/realtime_ui_api/research_api.py` module comments/docstring so they no longer describe research as mounted on `realtime-ui-api`
- [x] 1.5 Add a lightweight service test for `hbot/services/research_worker/main.py` that asserts `/health` responds and research routes are mounted

## 2. nginx Routing

- [x] 2.1 Add `location /api/research/` block in `hbot/apps/realtime_ui_v2/nginx.conf` routing to `research-worker:9920`, placed before the catch-all `/api/` block
- [x] 2.2 Include SSE-compatible headers: `proxy_read_timeout 86400s`, `proxy_buffering off`, `X-Accel-Buffering: no`

## 3. Docker Compose

- [x] 3.1 Add `research-worker` service to `hbot/infra/compose/docker-compose.yml` using the shared control-plane image, command `python /workspace/hbot/services/research_worker/main.py`, internal port 9920, memory 6144M, cpus 8.0
- [x] 3.2 Add `env_file: ../env/.env` to the `research-worker` service for LLM API keys
- [x] 3.3 Mount the workspace and reports volumes for `research-worker`, mirroring other control-plane services so file-backed exploration state and reports persist
- [x] 3.4 Revert `realtime-ui-api` resource limits from 6144M/8.0 back to 1536M/1.0

## 4. Resolution — SessionConfig

- [x] 4.1 Add `resolution: str = "15m"` and `step_interval_s: int = 900` fields to `SessionConfig` in `hbot/controllers/research/exploration_session.py`
- [x] 4.2 Replace hardcoded `"1m"` references in `exploration_session.py` market context building with `config.resolution`
- [x] 4.3 Replace hardcoded `60` step interval references in `exploration_session.py` with `config.step_interval_s`
- [x] 4.4 Update `catalog.find()` calls in `exploration_session.py` to use `config.resolution` instead of `"1m"`

## 5. Resolution — Prompts

- [x] 5.1 Update YAML examples in `SYSTEM_PROMPT` (`hbot/controllers/research/exploration_prompts.py`) from `"1m"` / `step_interval_s: 60` to `"15m"` / `step_interval_s: 900`
- [x] 5.2 Update `GENERATE_PROMPT` and `REVISE_PROMPT` resolution references from `"1m"` to `"15m"`
- [x] 5.3 Add guidance text stating the LLM may propose other resolutions when the hypothesis justifies it

## 6. Resolution — Orchestrator

- [x] 6.1 Change default `resolution` from `"1m"` to `"15m"` in `_build_backtest_config` in `hbot/controllers/research/experiment_orchestrator.py`
- [x] 6.2 Change default `step_interval_s` from `60` to `900` in `_build_backtest_config`
- [x] 6.3 Extend `hbot/tests/controllers/test_research/test_exploration_session.py` to assert the new `SessionConfig` defaults and prompt text reference `15m` / `900`
- [x] 6.4 Extend `hbot/tests/controllers/test_research/test_experiment_orchestrator.py` to assert `_build_backtest_config` defaults to `15m` / `900` and still respects explicit candidate overrides

## 7. Build and Deploy

- [x] 7.1 Rebuild the shared control-plane image via one of its services (for example `docker compose build realtime-ui-api research-worker`) and rebuild the frontend image (`docker compose build realtime-ui-web`)
- [x] 7.2 Deploy the affected services (`docker compose up -d realtime-ui-api research-worker realtime-ui-web`)
- [x] 7.3 Verify `research-worker` health check responds on port 9920 from inside the Compose network
- [x] 7.4 Verify `realtime-ui-api` health still responds on port 9910
- [x] 7.5 Verify `/api/research/candidates` returns data through nginx
- [x] 7.6 Verify `realtime-ui-api` no longer serves `/api/research/*` (404 expected)
- [x] 7.7 Launch a test exploration and verify the SSE log stream works end-to-end
- [x] 7.8 Run targeted validation: `python -m py_compile hbot/services/research_worker/main.py hbot/services/realtime_ui_api/main.py hbot/controllers/research/exploration_session.py hbot/controllers/research/experiment_orchestrator.py`
- [x] 7.9 Run targeted tests: `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_research/test_exploration_session.py hbot/tests/controllers/test_research/test_experiment_orchestrator.py -q`
