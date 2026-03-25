## Why

The March 2026 tech loop INITIAL_AUDIT uncovered systemic reliability, code health, and infrastructure debt that, if unaddressed, will block the ROAD-5 testnet-live promotion gate. The reconciliation service cannot connect to Redis (P0), architecture tests cannot run inside production containers, Redis streams grow unbounded risking OOM, and key services like `ops_scheduler` have zero test coverage. Addressing these now prevents compounding debt during the testnet push.

## What Changes

- **P0 — Fix reconciliation-service Redis authentication** — the fill reconciler fails with `NOAUTH` because it uses the wrong Redis URL; update to include credentials.
- **P0 — Mount tests directory in containers** — architecture contract tests cannot run in production containers because `hbot/tests/` is not volume-mounted; add the mount so gates can run end-to-end.
- **P1 — Cap Redis stream lengths** — `XTRIM MAXLEN` or `MAXLEN ~` all published streams to prevent unbounded memory growth under continuous operation.
- **P1 — Add test coverage for untested services** — `ops_scheduler`, `exchange_snapshot_service`, and `shadow_execution` have zero or near-zero test files; add baseline unit tests.
- **P1 — Reduce giant functions and files** — split functions exceeding 100 lines and files exceeding 500 lines in the kernel mixins and controller runtime.
- **P1 — Add `pytest.mark.parametrize` to existing test suites** — replace copy-paste test cases with parametrized equivalents in `test_ml`, `test_research`, and `test_kernel`.
- **P2 — Pin and align dependency versions** — resolve version drift between `requirements-control-plane.txt` and `requirements-ml-feature-service.txt` for shared libraries (`redis`, `pydantic`, `numpy`).
- **P2 — Suppress noisy `except Exception: pass`** — audit remaining bare `except Exception: pass` blocks and add justification comments or narrow the exception type.

### Performance Loop Additions (March 2026 INITIAL_AUDIT)

- **P0 — Fix cadvisor resource saturation** — cadvisor at 51% CPU and 99.5% of 128MB memory limit; fs overlay2 scans take 20–47 seconds per container, stealing CPU from trading-critical services.
- **P1 — Reduce realtime-ui-api CPU usage** — at 66% CPU due to 6-stream polling with per-message JSON fan-out to all WebSocket clients; 30-second full-state rebuild per connection amplifies load.
- **P1 — Enforce per-stream Redis MAXLEN caps** — `hb.market_trade.v1` at 500K entries (10× others); tighten trade stream cap and enforce MAXLEN on `hb.paper_exchange.event.v1` (105K) and `hb.audit.v1` (100K).
- **P1 — Investigate ops-scheduler disk I/O anomaly** — 4.07GB reads / 5.09GB writes in 10 hours for a service using only 8.5MB RAM.
- **P2 — Reduce Redis XAUTOCLAIM overhead** — 6.83M calls consuming 44.8s cumulative CPU; tune claim interval and idle threshold.
- **P2 — Right-size container memory limits** — bot7 at 69% of 512MB, kill-switch at 55% of 128MB, Grafana at 65% of 256MB. Adjust limits based on observed usage.
- **P2 — Docker volume and build cache cleanup** — 267.8GB volumes, 9.1GB build cache (8GB reclaimable), 20GB images (96% reclaimable).
- **P3 — Split React vendor chunk** — React/zustand currently in default bundle; split into `vendor-core` for better caching.
- **P3 — Reduce UI-API 30s full-state broadcast** — per-connection full state rebuild every 30s is heavy; consider delta-only or on-demand.

### Ops Loop Additions (March 2026 INITIAL_AUDIT)

- **P1 — Fix keyboard shortcut mismatch** — `ShortcutHelp.tsx` documents keys 1–6, `TopBar.tsx` advertises 1–9, but `useKeyboardShortcuts.ts` only handles 1–8; key 9 (ML Features) is dead.
- **P1 — Add Zod validation to research/backtest API responses** — `researchApi.ts` and `backtestApi.ts` use raw `res.json()` + type casts with no schema validation; malformed payloads can crash panels.
- **P1 — Remove `any` types from RealtimeDashboard.tsx** — production code uses `any` at lines ~118 and ~140 for grid layout callbacks; breaks type safety.
- **P1 — Add missing observability alerts** — no alerts for Prometheus/Grafana health, Postgres availability, metrics exporter scrape failures, or `up == 0` job-level targets.
- **P2 — Clean up stale promotion gate report** — `reports/promotion_gates/latest.json` last updated 03/07/2026 (17 days stale); parity directory has 11,618 files with no rotation.
- **P2 — Normalize BotDailyPnlDrawdown alert threshold** — currently hardcoded at -50 quote units; not account-size-normalized.
- **P2 — Add explicit "STALE" label to TopBar** — data age is shown as numeric seconds only; operator cannot distinguish loading vs stale at a glance.
- **P2 — Split useDashboardStore.ts** — at 1,780 lines, the largest TypeScript file; mixing ingest, connection, alerts, and UI state in a single store.
- **P3 — Reduce App.css to design tokens** — at 1,904 lines, the largest file; repeated patterns and magic values instead of CSS variables.
- **P3 — Add playbooks for Postgres outage and metrics exporter failure** — 10 playbooks exist but no coverage for DB or metrics infra failures.

### Frontend Loop Additions (March 2026 INITIAL_AUDIT)

- **P1 — Fix ResearchPage/BacktestPage mixed responsibilities** — both are 500–680 line files combining SSE transport, state management, and rendering in one module; extract data hooks.
- **P2 — Add loading/error distinction to BotGateBoardPanel** — no `loading` prop on Panel; "No gate status available" is ambiguous between loading and empty.
- **P2 — Split realtimeParsers.ts (717 lines)** — monolithic Zod schema file; split by domain (market, telemetry, review).

## Capabilities

### New Capabilities
- `redis-stream-trimming`: Automated MAXLEN trimming for all Redis streams to enforce memory budgets under continuous operation.
- `service-test-baseline`: Minimum viable unit test suites for `ops_scheduler`, `exchange_snapshot_service`, and `shadow_execution` services.
- `container-performance-baseline`: Evidence-based CPU/memory limits, cadvisor tuning, and Docker resource hygiene.
- `frontend-code-health`: Keyboard shortcut consistency, Zod validation at API boundaries, type safety enforcement, and file size guardrails.
- `ops-observability`: Missing alert coverage for infrastructure health, stale report rotation, and alert threshold normalization.

### Modified Capabilities
- `modern-python-idioms`: Extend with function/file size guardrails and bare-except audit rules.
- `signal-diagnostics`: Extend reconciliation-service connectivity to handle Redis auth properly.
- `realtime-ui-performance`: Reduce UI-API CPU via batched fan-out, reduced polling frequency, and deferred state rebuilds.

## Impact

- **Code**: `hbot/services/reconciliation_service/fill_reconciler.py`, `hbot/services/ops_scheduler/main.py`, `hbot/services/exchange_snapshot_service/main.py`, `hbot/services/shadow_execution/main.py`, kernel mixin files in `hbot/controllers/runtime/kernel/`, stream publishers in `hbot/platform_lib/contracts/stream_names.py` and `hbot/services/*/main.py`.
- **Infrastructure**: `hbot/infra/compose/docker-compose.yml` (volume mounts, Redis MAXLEN config), `hbot/infra/compose/images/*/requirements-*.txt` (dependency alignment).
- **Tests**: New test files in `hbot/tests/services/`, expanded parametrize usage in `hbot/tests/controllers/`.
- **Dependencies**: `redis`, `pydantic`, `numpy` version alignment across requirement files.
- **Risk**: Low — all changes are additive or tightening; no strategy logic is modified, no breaking API changes.
- **Performance**: `hbot/infra/compose/docker-compose.yml` (cadvisor limits, container memory right-sizing), `hbot/services/realtime_ui_api/stream_consumer.py` and `state.py` (CPU reduction), `hbot/services/ops_scheduler/main.py` (disk I/O audit).
- **Frontend**: `hbot/apps/realtime_ui_v2/src/hooks/useKeyboardShortcuts.ts`, `src/components/ShortcutHelp.tsx`, `src/components/TopBar.tsx`, `src/utils/researchApi.ts`, `src/utils/backtestApi.ts`, `src/components/RealtimeDashboard.tsx`, `src/store/useDashboardStore.ts`, `src/utils/realtimeParsers.ts`, `src/components/ResearchPage.tsx`, `src/components/BacktestPage.tsx`, `src/components/BotGateBoardPanel.tsx`, `src/App.css`.
- **Ops/Monitoring**: `hbot/infra/monitoring/prometheus/alert_rules.yml` (new alerts, threshold normalization), `hbot/reports/` (rotation, staleness), `hbot/docs/ops/incident_playbooks/` (new playbooks).
