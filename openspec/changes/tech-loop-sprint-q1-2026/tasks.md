## 1. P0 — Reconciliation Service Redis Auth

- [x] 1.1 Add `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` env vars to `reconciliation-service` section in `hbot/infra/compose/docker-compose.yml`, pulling from the `x-kzay-env` anchor
- [x] 1.2 Verify `RedisStreamClient` in `hbot/services/reconciliation_service/main.py` correctly reads these env vars (confirm existing code matches)
- [ ] 1.3 Restart reconciliation-service container and confirm Redis `AUTH` succeeds in logs (no `NOAUTH` errors)

## 2. P0 — Test Runner Compose Service

- [x] 2.1 Add `test-runner` service to `docker-compose.yml` with `profiles: [test]`, mounting full `hbot/` tree including `tests/`
- [x] 2.2 Set `PYTHONPATH=/workspace/hbot` and install test dependencies (`pytest`, `pytest-mock`) in the test-runner image — pytest already in control-plane requirements
- [ ] 2.3 Run `docker compose --profile test run test-runner pytest hbot/tests/architecture/ -q` and confirm all architecture tests pass

## 3. P1 — Redis Stream Trimming

- [x] 3.1 Add `maxlen` parameter to `RedisStreamClient.xadd()` in the shared Redis client wrapper, defaulting to `int(os.getenv("STREAM_RETENTION_MAXLEN", "50000"))` — ALREADY IMPLEMENTED via `STREAM_RETENTION_MAXLEN` dict in `stream_names.py`
- [x] 3.2 Pass `maxlen` with approximate flag (`~`) to the underlying `redis.xadd()` call — ALREADY IMPLEMENTED (`approximate=True` in `xadd`)
- [x] 3.3 Audit all direct `self._redis.xadd` / `r.xadd` calls outside `RedisStreamClient` and route them through the wrapper — VERIFIED: all calls go through `RedisStreamClient.xadd()`
- [ ] 3.4 Add unit test verifying `xadd` is called with `maxlen` argument

## 4. P1 — Service Test Baseline: ops_scheduler

- [x] 4.1 Create `hbot/tests/services/test_ops_scheduler.py` with tests for `_get_interval()`, heartbeat write, and job config validation
- [x] 4.2 28 tests covering: env-var parsing (4), job structural checks (parametrized over all jobs), heartbeat JSON write
- [x] 4.3 Run `PYTHONPATH=hbot pytest hbot/tests/services/test_ops_scheduler.py -v` — all 28 pass

## 5. P1 — Service Test Baseline: exchange_snapshot_service

- [x] 5.1 Create `hbot/tests/services/test_exchange_snapshot_service.py` with tests for pure functions
- [x] 5.2 12 tests covering: credential parsing, redaction, account map loading, bot account resolution
- [x] 5.3 Run `PYTHONPATH=hbot pytest hbot/tests/services/test_exchange_snapshot_service.py -v` — all 12 pass

## 6. P1 — Service Test Baseline: shadow_execution

- [x] 6.1 Expanded `hbot/tests/services/test_shadow_execution.py` with tests for `_read_json`, `_latest_market_mid`, `_metric_result`
- [x] 6.2 19 tests covering: `_to_ms` (6), `_read_json` (4), `_latest_market_mid` (4), `_metric_result` (5)
- [x] 6.3 Run `PYTHONPATH=hbot pytest hbot/tests/services/test_shadow_execution.py -v` — all 19 pass

## 7. P1 — Kernel Function Decomposition

- [x] 7.1 Extract `SharedRuntimeKernel.__init__` into `_validate_config()`, `_init_core_components()`, `_init_price_buffer()` helpers — __init__ reduced from 351 to 265 lines
- [x] 7.2 Extract `_compute_adaptive_spread_knobs` into `_compute_adaptive_edge_bps()` (55 lines) + `_compute_pnl_governor()` (95 lines) — main reduced from 216 to 106 lines
- [x] 7.3 Extract `_compute_alpha_policy` into `_compute_alpha_scores()` (60 lines) + `_resolve_alpha_state()` (70 lines) — main reduced from 131 to 36 lines
- [x] 7.4 Run `PYTHONPATH=hbot pytest hbot/tests/controllers/test_kernel/ -q` — all 13 tests pass after all extractions
- [x] 7.5 Function size audit: 5 new helpers under 100 lines each; remaining large methods (`__init__` 265, `update_processed_data` 131) are sequential initialization/tick-loop code that resists further decomposition without artificial fragmentation

## 8. P1 — Parametrize Existing Tests

- [x] 8.1 `test_indicators.py` — SMA/EMA/RSI/Stddev tests consolidated into `TestScalarIndicatorMatchesDecimal` via `pytest.mark.parametrize`
- [x] 8.2 `test_visible_candle.py` — `test_always_visible_fields` parametrized over open/volume/timestamp
- [x] 8.3 All parametrized tests pass — no regressions

## 9. P2 — Dependency Version Alignment

- [x] 9.1 Compared versions: `pandas`, `pyarrow`, `ccxt`, `redis`, `joblib`, `scikit-learn`, `pydantic` all differed
- [x] 9.2 Pinned `requirements-ml-feature-service.txt` to match control-plane: `pandas==2.2.3`, `pyarrow==18.1.0`, `ccxt==4.5.39`, `redis==7.0.1`, `joblib==1.5.3`, `scikit-learn==1.6.1`, `pydantic==2.12.5`
- [ ] 9.3 Run `python -m py_compile` on key service entrypoints to verify import compatibility
- [ ] 9.4 Run `PYTHONPATH=hbot pytest hbot/tests/ -x -q --ignore=hbot/tests/integration` to confirm no breakage

## 10. P2 — Bare Except Audit

- [x] 10.1 Searched all production directories — found ~40 unjustified blocks across controllers, services, scripts, and infra
- [x] 10.2 Added `# Justification: <reason>` to every block — zero remaining `except Exception: pass` without justification in controllers/, services/, simulation/, platform_lib/, scripts/
- [ ] 10.3 Verify architecture contract test for bare-except still passes

---

## Performance Loop Tasks (March 2026 INITIAL_AUDIT)

## 11. P0 — Fix cadvisor Resource Saturation

- [x] 11.1 In `docker-compose.yml`, increase cadvisor `mem_limit` from `128m` to `256m`
- [x] 11.2 Add `--housekeeping_interval=30s` and `--docker_only=true` to cadvisor command/entrypoint
- [ ] 11.3 Restart cadvisor and confirm CPU drops below 15% and memory stays below 80% of 256MB via `docker stats`
- [ ] 11.4 Verify Grafana container dashboards still populate correctly after cadvisor flag changes

## 12. P1 — Reduce realtime-ui-api CPU Usage

- [x] 12.1 In `hbot/services/realtime_ui_api/stream_consumer.py`, batch `_notify` calls: collect all entries from one `read_group` call, then notify subscribers once per batch instead of per entry
- [x] 12.2 Change default `poll_ms` from 200 to 500 (via `REALTIME_UI_API_POLL_MS` env var or code default)
- [x] 12.3 In `hbot/services/realtime_ui_api/main.py`, increase the 30-second full-state rebuild interval to 60 seconds
- [ ] 12.4 Restart realtime-ui-api and confirm CPU drops below 30% via `docker stats` under normal load
- [ ] 12.5 Verify dashboard data freshness is still acceptable (events visible within 1 second)

## 13. P1 — Investigate and Fix ops-scheduler Disk I/O

- [x] 13.1 Root cause: heartbeat written from 7 threads + main loop without rate-limiting; subprocess spawning loads full Python runtime from disk each invocation
- [x] 13.2 Fix: added thread-safe heartbeat write coalescing (min 30s between writes), added `PYTHONPYCACHEPREFIX=/tmp/pycache` to subprocess env to redirect bytecache off workspace volume
- [x] 13.3 All 28 ops_scheduler tests pass after changes
- [ ] 13.4 Restart ops-scheduler and monitor block I/O via `docker stats` for 1 hour; confirm < 500MB total (requires running containers)

## 14. P2 — Tune Redis XAUTOCLAIM Overhead

- [x] 14.1 Identified: `RedisStreamClient.claim_pending()` in `redis_client.py`, called from `paper_exchange_service/main.py` and `desk_service.py`
- [x] 14.2 Increased idle threshold from 30s to 120s in `redis_client.py`, `models.py`, `desk_service.py`, `main.py`; also increased reclaim interval from 5s to 15s
- [x] 14.3 COUNT already at 100 (task assumed 500) — no change needed
- [ ] 14.4 Monitor Redis `INFO commandstats` for `xautoclaim` after restart; confirm call count drops by > 50%

## 15. P2 — Right-size Container Memory Limits

- [ ] 15.1 In `docker-compose.yml`, change `desk-snapshot` mem_limit from `64m` to `32m`
- [ ] 15.2 Verify desk-snapshot continues running stable at 32MB for at least 2 hours
- [ ] 15.3 Document current peak memory for bot7, kill-switch, and Grafana as baseline for next review cycle
- [ ] 15.4 If bot7 peak exceeds 450MB during stress testing, increase limit from `512m` to `640m`

## 16. P2 — Docker Disk Hygiene

- [ ] 16.1 Run `docker image prune -a --filter "until=168h"` to reclaim unused images
- [ ] 16.2 Run `docker builder prune --filter "until=168h"` to reclaim stale build cache
- [ ] 16.3 Confirm Docker volume total drops below 200GB after cleanup
- [ ] 16.4 Add a weekly cleanup script to `hbot/scripts/ops/` that performs these prune operations

## 17. P3 — Frontend Vendor Chunk Splitting

- [x] 17.1 In `vite.config.ts`, added `manualChunks` for `vendor-react` (react+react-dom+zustand), `vendor-grid` (react-grid-layout), `vendor-zod` (zod); zustand merged into vendor-react to resolve circular dep
- [x] 17.2 `npm run build` succeeds — vendor-react 168KB, vendor-grid 67KB, vendor-zod 34KB
- [x] 17.3 Fixed Zod 4 API migration (.parse→z.parse, .safeParse→z.safeParse, z.record requires key+value)
- [x] 17.4 Fixed react-grid-layout type imports (import type { Layout, ResponsiveLayouts })
- [ ] 17.5 Verify bundle sizes and chunk distribution are optimized (needs browser DevTools)
- [ ] 17.6 Visual smoke test in browser — ensure no runtime errors

---

## Ops Loop Tasks (March 2026 INITIAL_AUDIT)

## 18. P1 — Fix Keyboard Shortcut Mismatch

- [x] 18.1 In `hbot/apps/realtime_ui_v2/src/hooks/useKeyboardShortcuts.ts`, change digit regex from `/^[1-8]$/` to `/^[1-9]$/` to include ML Features view
- [x] 18.2 In `hbot/apps/realtime_ui_v2/src/components/ShortcutHelp.tsx`, update documented range from "1–6" to "1–9"
- [ ] 18.3 Verify pressing keys 1–9 switches to the correct views in the browser

## 19. P1 — Add Zod Validation to Research/Backtest API Responses

- [x] 19.1 In `hbot/apps/realtime_ui_v2/src/utils/researchApi.ts`, add Zod schemas for `CandidateDetail`, exploration list, and exploration detail responses
- [x] 19.2 Replace `as CandidateDetail` cast with `schema.parse()` calls; return structured error on parse failure
- [x] 19.3 In `hbot/apps/realtime_ui_v2/src/utils/backtestApi.ts`, add Zod schemas for `BacktestJobStatus`, `BacktestResultSummary`, and overrides
- [x] 19.4 Replace bare `Record<string, unknown>` casts with validated parse calls
- [ ] 19.5 Run `npm run build` and `npx vitest run` to confirm no type or runtime regressions

## 20. P1 — Remove `any` Types from RealtimeDashboard.tsx

- [x] 20.1 Replace `(item: any)` at ~line 118 with proper `ReactGridLayout.Layout` type
- [x] 20.2 Replace `_layout: any, allLayouts: any` at ~line 140 with `react-grid-layout` callback types from `@types/react-grid-layout`
- [ ] 20.3 Run `npx tsc --noEmit` and confirm zero type errors

## 21. P1 — Add Infrastructure Health Alerts

- [x] 21.1 In `hbot/infra/monitoring/prometheus/alert_rules.yml`, add `PrometheusTargetDown` alert: `up == 0`, severity warning, `for: 5m`
- [x] 21.2 Add `PostgresDown` alert: absence of postgres container metrics, severity critical, `for: 2m`
- [x] 21.3 Add `MetricsExporterScrapeFailed` alert: absent or zero `scrape_duration_seconds` for exporter jobs, severity warning, `for: 5m`
- [ ] 21.4 Reload Prometheus config and verify new alerts appear in Prometheus `/alerts` UI

## 22. P2 — Stale Report Cleanup and Rotation

- [x] 22.1 Created `hbot/scripts/ops/report_rotation.py` with `--dry-run` flag: parity 7d, reconciliation 14d, verification 14d + tmp cleanup
- [ ] 22.2 Re-run strict promotion cycle to refresh `reports/promotion_gates/latest.json`
- [ ] 22.3 Confirm report directory file counts drop to manageable levels

## 23. P2 — Normalize BotDailyPnlDrawdown Alert Threshold

- [x] 23.1 Changed `BotDailyPnlDrawdown` from `-50` to `(daily_pnl / equity) < -0.05` (5% of equity)
- [x] 23.2 Changed `RealizedPnlNegative` from `-20` to `(realized_pnl / equity) < -0.02` (2% of equity)
- [ ] 23.3 Reload Prometheus and verify modified alerts evaluate correctly

## 24. P2 — Add Explicit "STALE" Label to TopBar

- [x] 24.1 In `hbot/apps/realtime_ui_v2/src/components/TopBar.tsx`, add conditional label when `ageMs > 30000` showing "STALE" in red next to the numeric age
- [x] 24.2 Add CSS class for stale indicator in `App.css` or inline style
- [ ] 24.3 Verify label appears/disappears correctly when websocket reconnects

---

## Frontend Loop Tasks (March 2026 INITIAL_AUDIT)

## 25. P1 — Extract ResearchPage/BacktestPage Data Hooks

- [x] 25.1 Create `hbot/apps/realtime_ui_v2/src/hooks/useResearchData.ts` — extract SSE, fetch, and state management logic from `ResearchPage.tsx` (95 lines, 18 return props)
- [x] 25.2 Create `hbot/apps/realtime_ui_v2/src/hooks/useBacktestData.ts` — extract polling, normalization and state logic from `BacktestPage.tsx` (117 lines, 15 return props)
- [x] 25.3 Refactor `ResearchPage.tsx` (794→726 lines) and `BacktestPage.tsx` (517→404 lines) to consume hooks; pages only render UI
- [x] 25.4 SSE cleanup (EventSource) stays in page-level sub-components (ExplorationLogPanel, LogPanel) since it's tightly coupled to rendering; polling moved to useBacktestData hook
- [x] 25.5 `npx tsc --noEmit` clean with zero errors

## 26. P2 — Add Loading State to BotGateBoardPanel

- [x] 26.1 Added `hasConnected` flag from store; shows "Loading…" before first WS connect, "No gate status available" after
- [x] 26.2 Verified: loading state shows when `quoteGates.length === 0 && !hasConnected`
- [x] 26.3 TypeScript clean (`npx tsc --noEmit` passes)

## 27. P2 — Split useDashboardStore.ts

- [ ] 27.1 Create `hbot/apps/realtime_ui_v2/src/store/useConnectionStore.ts` — extract WebSocket/REST transport state, health, reconnect logic
- [ ] 27.2 Create `hbot/apps/realtime_ui_v2/src/store/useAlertStore.ts` — extract alerts, alert history, gate status
- [ ] 27.3 Update all imports across components to use the new stores
- [ ] 27.4 Verify `useDashboardStore.ts` is below 800 lines after extraction
- [ ] 27.5 Run `npx vitest run` and `npm run build` to confirm no regressions

## 28. P2 — Split realtimeParsers.ts

- [x] 28.1 Split into `parsers/marketParsers.ts`, `parsers/telemetryParsers.ts`, `parsers/reviewParsers.ts`
- [x] 28.2 Original `realtimeParsers.ts` converted to barrel re-exporting all symbols — zero import changes needed
- [x] 28.3 `npx tsc --noEmit` clean; vitest 112 tests pass

## 29. P3 — Reduce App.css with Design Tokens

- [x] 29.1 Identified 20 repeated patterns (fonts, spacing, radius, letter-spacing, colors) with 3+ occurrences
- [x] 29.2 Created `:root` block with 20 CSS custom properties (semantic names)
- [x] 29.3 Replaced 195 inline magic values with `var(--token)` references
- [ ] 29.4 File grew to 2070 lines (+34 for `:root` block) — net reduction requires further consolidation (P3)
- [ ] 29.5 Visual smoke test in browser — no style regressions

## 30. P3 — Add Incident Playbooks for Postgres and Metrics Exporter

- [x] 30.1 Create `hbot/docs/ops/incident_playbooks/11_postgres_outage.md` — symptoms, diagnosis, recovery steps, verification
- [x] 30.2 Create `hbot/docs/ops/incident_playbooks/12_metrics_exporter_failure.md` — symptoms, diagnosis, recovery steps, verification
- [ ] 30.3 Update playbook index if one exists
