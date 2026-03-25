## Context

The March 2026 tech-loop INITIAL_AUDIT exposed reliability and code-health issues across the hbot platform. The system runs 7+ strategy bots, 26+ microservices, and a Redis-centric event bus, all orchestrated via `docker-compose.yml`. Key findings:

- **Reconciliation service** defaults `REDIS_HOST=redis` and `REDIS_PASSWORD=""` but the compose stack's Redis requires authentication (`kzay_redis_paper_2026`). The service silently fails to publish reconciliation events.
- **Architecture contract tests** (`hbot/tests/architecture/`) cannot run inside bot containers because no compose service mounts the `tests/` directory.
- **Redis streams** (17 defined in `stream_names.py`) have no enforced `MAXLEN` at publish time; under continuous 24/7 operation streams grow unbounded, risking Redis OOM.
- **Zero test coverage** for `ops_scheduler` (202 lines), `exchange_snapshot_service`, and `shadow_execution`.
- **Giant functions/files** in `controllers/runtime/kernel/`: `controller.py` (1032 lines), `__init__` (354 lines), `_compute_adaptive_spread_knobs` (216 lines), `quoting_mixin.py` (800 lines), `supervisory_mixin.py` (718 lines).
- **Dependency drift** between requirement files: `redis`, `pydantic`, `numpy` versions differ across `requirements-control-plane.txt` and `requirements-ml-feature-service.txt`.

## Goals / Non-Goals

**Goals:**
- Restore reconciliation-service Redis connectivity so fill-reconciliation events flow to downstream consumers.
- Enable architecture tests to run inside containers for CI-in-Docker parity.
- Enforce bounded Redis stream memory via `MAXLEN` on all `xadd` calls.
- Establish baseline test coverage (≥ 3 test functions each) for `ops_scheduler`, `exchange_snapshot_service`, `shadow_execution`.
- Begin kernel code-health decomposition: extract the 3 largest functions into focused helpers.
- Align shared dependency versions across requirement files.

**Non-Goals:**
- Full kernel rewrite or API changes — only extract helpers within existing classes.
- Strategy logic changes — no modification to any `controllers/bots/*` file.
- New Redis infrastructure (Sentinel, Cluster) — out of scope.
- Test coverage for integration or end-to-end paths — only unit tests.
- Monitoring/alerting for stream lengths — deferred to next cycle.

## Decisions

### D1: Reconciliation Redis auth — inject compose env vars

**Decision**: Add `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` environment variables to the `reconciliation-service` section in `docker-compose.yml`, referencing the existing `x-kzay-env` anchor.

**Alternatives considered**:
- *Hardcode password in `main.py` defaults*: rejected — violates secret management policy and diverges from compose-based config.
- *Switch to `REDIS_URL` single string*: rejected — `RedisStreamClient` constructor takes discrete `host/port/password` params; refactoring the client is out of scope.

### D2: Mount tests directory — add read-only volume to a `test-runner` service

**Decision**: Add a new lightweight `test-runner` service in compose that mounts the full `hbot/` tree including `tests/`, intended for gate-check CI runs. Bot containers remain unchanged (they don't need tests at runtime).

**Alternatives considered**:
- *Mount tests into every bot container*: rejected — increases attack surface and container size for no runtime benefit.
- *Run tests only on host*: current state; works but means container-parity checks are impossible.

### D3: Redis stream trimming — centralize MAXLEN in `RedisStreamClient.xadd()`

**Decision**: Add a `maxlen` parameter (default from env `STREAM_RETENTION_MAXLEN`, fallback `50000`) to the shared `RedisStreamClient.xadd()` wrapper. All callers inherit the trim automatically. The `~` approximate trimming flag is used for performance.

**Alternatives considered**:
- *Per-stream configured maxlen*: more flexible but premature — uniform cap is sufficient for now.
- *External cron `XTRIM` script*: rejected — races with publishers and adds operational complexity.

### D4: Service test baseline — use `unittest.mock` + `pytest` with no real Redis

**Decision**: Each new test file imports the service's core logic, mocks Redis/HTTP/file I/O, and validates the happy path plus one error path. Target: ≥ 3 test functions per service.

### D5: Kernel decomposition — extract helpers, don't restructure

**Decision**: For the 3 largest functions (`__init__`, `_compute_adaptive_spread_knobs`, `_compute_alpha_policy`):
1. Extract logical blocks into private `_setup_*` / `_compute_*` helper methods on the same class.
2. No change to the public API or mixin inheritance.
3. Add `# NOTE: extracted from <original_method>` comments for traceability.

**Alternatives considered**:
- *Move to new mixins*: rejected — creates import churn and risks breaking the mixin resolution order.
- *Full rewrite*: too risky for a hardening sprint.

### D6: Dependency alignment — pin to highest compatible version

**Decision**: For each shared library (`redis`, `pydantic`, `numpy`), pin both requirement files to the same version — the higher of the two currently specified, after verifying compatibility.

### D7: cadvisor resource saturation — increase memory limit + reduce scan scope

**Decision**: Increase cadvisor memory limit from 128MB to 256MB and add `--housekeeping_interval=30s` and `--docker_only=true` flags to reduce fs scan frequency and scope. The current 128MB limit causes 99.5% memory utilization with fs overlay2 scans consuming 20–47 seconds each.

**Alternatives considered**:
- *Remove cadvisor entirely*: rejected — Grafana/Prometheus dashboards depend on it for container metrics.
- *Replace with `docker stats` polling*: rejected — loses per-container metric granularity needed for Prometheus.

### D8: realtime-ui-api CPU reduction — batch fan-out + reduce stream poll frequency

**Decision**: In `stream_consumer.py`, increase default `poll_ms` from 200 to 500 and batch `_notify` calls per stream read cycle instead of per-entry. In `main.py`, increase the 30-second full-state interval to 60s and only rebuild for clients that haven't received a delta within that window.

**Alternatives considered**:
- *Dedicated WebSocket broadcast thread*: adds complexity; batching achieves similar throughput reduction with less risk.
- *Server-Sent Events only*: loses bidirectional control channel needed for subscription management.

### D9: ops-scheduler disk I/O investigation — add logging and tracing

**Decision**: Add disk I/O profiling to the ops-scheduler startup and main loop. Instrument file operations with timing metrics to identify the source of 4GB+ reads/writes. Likely candidates: heartbeat JSON overwrites, repeated log rotation, or SQLite journal flushes.

### D10: Redis XAUTOCLAIM tuning — increase idle threshold

**Decision**: Increase XAUTOCLAIM idle threshold from 30s to 120s and reduce claim frequency. Currently 6.83M calls in 10 hours (190/s) consuming 44.8s cumulative CPU. Most pending messages are processed within seconds; the 30s threshold causes unnecessary re-claiming of recently-delivered messages.

### D11: Container memory right-sizing — evidence-based limits

**Decision**: Adjust container memory limits based on observed peak usage + 30% headroom:
- cadvisor: 128MB → 256MB
- kill-switch: 128MB → 96MB (or keep 128MB with investigation)
- bot7: monitor; at 69% of 512MB, consider raising to 640MB if stress tests show spikes
- desk-snapshot: 64MB → 32MB (only using 13MB)

### D12: Keyboard shortcut alignment — fix range and help text

**Decision**: In `useKeyboardShortcuts.ts`, extend the digit handler regex from `/^[1-8]$/` to `/^[1-9]$/` to include the ML Features view. In `ShortcutHelp.tsx`, update the documented range from "1–6" to "1–9" to match `TopBar.tsx` shortcut labels.

### D13: Zod validation at research/backtest API boundaries

**Decision**: Add Zod schemas in `researchApi.ts` and `backtestApi.ts` for all `res.json()` responses. Replace bare `as CandidateDetail` and `as BacktestJobStatus` casts with `parse()` calls. On parse failure, return structured error instead of crashing the panel.

### D14: Remove `any` types from RealtimeDashboard.tsx

**Decision**: Replace `(item: any)` at ~line 118 with `ReactGridLayout.Layout` and the `_layout: any, allLayouts: any` at ~line 140 with the correct `react-grid-layout` callback types from `@types/react-grid-layout`.

### D15: Add infrastructure health alerts to alert_rules.yml

**Decision**: Add alert rules for:
- `PrometheusTargetDown`: `up == 0` for any scrape target, severity warning, `for: 5m`
- `PostgresDown`: absence of postgres container metrics, severity critical, `for: 2m`
- `MetricsExporterScrapeFailed`: `scrape_duration_seconds == 0` or absent, severity warning, `for: 5m`

### D16: Report rotation and stale-report housekeeping

**Decision**: Add a scheduled task to `ops_scheduler` to prune report directories that accumulate unbounded files:
- `reports/parity/` (11,618 files): retain last 7 days
- `reports/reconciliation/` (thousands of historical files): retain last 14 days
- `reports/verification/` (530 files + `.tmp` leftovers): delete `.tmp` files, retain last 14 days
- Re-run `strict_cycle` to refresh `reports/promotion_gates/latest.json`

### D17: Split useDashboardStore.ts into focused stores

**Decision**: Extract from the 1,780-line monolithic store into:
- `useConnectionStore.ts` — WebSocket/REST transport state, health, reconnect
- `useAlertStore.ts` — alerts, alert history, gate status
- Keep `useDashboardStore.ts` for market data, fills, orders, position state
Follow the Zustand slice pattern to avoid breaking existing selectors.

### D18: Extract ResearchPage/BacktestPage data hooks

**Decision**: For both 500–680 line pages:
- Extract SSE + fetch logic into `useResearchData.ts` and `useBacktestData.ts`
- Pages become pure rendering components consuming hook return values
- SSE cleanup and abort handling move into the hooks

### D19: Add BotGateBoardPanel loading state

**Decision**: Pass `loading={!gateSummary && awaitingData}` to `Panel` in `BotGateBoardPanel.tsx` so operators can distinguish "still loading" from "no gates".

## Risks / Trade-offs

- **[Stream trimming drops old data]** → Mitigation: 50K entries at ~1 msg/sec = ~14 hours of history, well beyond the 1-hour consumer replay window. Ops-db-writer and event-store have already consumed and persisted these events.
- **[Test-runner service adds compose complexity]** → Mitigation: service has `profiles: [test]` so it only starts when explicitly invoked (`docker compose --profile test run test-runner`).
- **[Kernel helper extraction could introduce regressions]** → Mitigation: extract is purely mechanical (move lines → call helper); run full kernel test suite (`test_kernel/`) after each extraction. No logic changes.
- **[Dependency version bump could break import]** → Mitigation: bump one library at a time, run `py_compile` + test suite after each.
- **[Increasing poll_ms reduces event freshness]** → Mitigation: 500ms poll is still well within the 1-second dashboard refresh target; most panels throttle at 200–333ms already.
- **[cadvisor memory increase reduces resources for other containers]** → Mitigation: 128MB increase is negligible on a 23.4GB host; cadvisor crash-restarts are more expensive.
- **[XAUTOCLAIM idle increase may delay dead-letter recovery]** → Mitigation: at 120s, a stalled consumer's messages are still re-claimed within 2 minutes; the dead-letter stream provides a safety net.

## Open Questions

- Should `STREAM_RETENTION_MAXLEN` be per-stream configurable in the next cycle? (Deferred — uniform 50K is safe for now.)
- Should the `test-runner` compose service also run integration tests, or only unit + architecture? (Recommend unit + architecture only for this sprint.)
- What is the root cause of ops-scheduler's 4GB+ disk I/O? (Requires runtime profiling — scheduled for D9.)
- Should the 30s full-state broadcast be replaced with WebSocket delta compression? (Deferred — increasing interval to 60s is sufficient for now.)
- Should `useDashboardStore` decomposition use Zustand slices or separate stores? (D17 recommends separate stores for better code splitting; slices are an alternative if cross-store access is frequent.)
- Should `BotDailyPnlDrawdown` threshold be percentage-based or use account equity? (Account equity is more correct but requires a new metric; percentage is simpler.)
- Should `App.css` be migrated to CSS modules or a utility framework? (Deferred — CSS variables and deduplication first.)
