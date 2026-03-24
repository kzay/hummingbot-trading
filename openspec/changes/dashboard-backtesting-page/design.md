## Context

The v2 realtime dashboard (`hbot/apps/realtime_ui_v2`) consumes live bot state via REST/WebSocket from an existing Python API. Backtests run only via CLI. `BacktestHarness` + `load_backtest_config` are solid building blocks, but the harness has **metrics wiring gaps** (win rate, position series, regime data never reach `compute_all_metrics`). The dashboard already includes `lightweight-charts` with a dark-theme equity curve component (`EquityCurveChart` in `DailyReviewPanel`), `Panel` shells, and an auth pattern (`apiBase` + token).

Constraints: single-operator deployment; dashboard behind nginx; strategy execution from untrusted input is code-execution risk; VPS resources are finite.

## Goals / Non-Goals

**Goals:**

- Fix harness metrics wiring so results shown in the UI are **trustworthy**.
- Serve a thin backtest API (presets, jobs, logs, cancel) from the **existing Python service** or a minimal FastAPI module.
- Persist job metadata in **SQLite** (survives restarts, enables history).
- Deliver logs via **SSE** for responsive streaming with zero new deps.
- Show an **equity curve chart**, **metric cards**, **warnings strip**, and **job history table** in a new dashboard route.
- Support **safe scalar overrides** (initial equity, start/end date) alongside preset selection.
- Expose **determinate progress** (harness knows total ticks) and a **cancel** action.

**Non-Goals:**

- Full strategy editor, YAML upload, sweep/walk-forward from the UI.
- WebSocket for log delivery (SSE is simpler for unidirectional streams).
- Fill scatter plot, regime breakdown chart, or side-by-side comparison (fast follow-ups, not MVP).
- Running backtests inside the nginx container (Python must host the harness).
- Replacing the CLI.

## Decisions

### D1. API host

**Decision:** Add routes to the existing Python service that the dashboard already talks to (the `apiBase` service). If that service cannot host additional routes, introduce a minimal FastAPI app in `hbot/services/backtest_api/` sharing the same compose network.

**Rationale:** Avoids a new container for 6 endpoints. Auth, CORS, and nginx are already configured.

**Alternative:** Separate microservice — rejected unless the existing service is Node-only or not extensible.

### D2. Job persistence

**Decision:** SQLite database (`hbot/data/backtest_jobs.db`), one table: `jobs(id, preset_id, overrides_json, status, progress_pct, created_at, updated_at, result_summary_json, error, log_path, report_path, pid)`.

**Rationale:** Zero-config, file-based, survives process restarts; stdlib `sqlite3` — no new deps. Sufficient for hundreds-of-jobs scale. Enables job history list and filtering.

**Alternative:** In-memory dict — rejected (loses state on restart, no history). Redis — overkill for single-tenant.

### D3. Log delivery

**Decision:** SSE (`text/event-stream`) on `GET /jobs/{id}/log`. FastAPI streams lines from the log file as they appear (tail -f style using `watchdog` or simple poll-read loop). Falls back to full-file dump once the job is terminal.

**Rationale:** Browser-native `EventSource` API; no WebSocket handshake or protocol overhead; auto-reconnect built in. Dashboard already handles event-driven data.

**Alternative:** Polling `GET /log?tail=N` — rejected (choppy UX, extra requests). WebSocket — rejected (heavier, bidirectional not needed).

### D4. Progress reporting from harness

**Decision:** Harness writes a JSON progress file (`{job_dir}/progress.json`) every N ticks (e.g. every 1000 ticks or every 5 seconds): `{ "current_tick": ..., "total_ticks": ..., "progress_pct": ... }`. The API reads this file on status poll. Cheap, no shared memory or IPC complexity.

**Rationale:** Harness runs in a subprocess; file I/O is the simplest cross-process channel. Writing every 1000 ticks adds negligible overhead.

**Alternative:** Pipe/queue — more complex; progress file is sufficient for 1–2s polling.

### D5. Equity curve chart

**Decision:** Reuse the `lightweight-charts` `LineSeries` pattern from `DailyReviewPanel.tsx` (`EquityCurveChart` component) with the same dark theme colors (`#121a28` bg, `#dce3f0` text, `#273244` grid). Extract the chart component into a shared module if not already shared. Feed it `BacktestResult.equity_curve[]` mapped to `{ time, value }`.

**Rationale:** Library already bundled, theme already defined, component pattern already proven. Near-zero incremental effort.

**Alternative:** New charting lib — rejected (adds bundle size, visual inconsistency).

### D6. Safe overrides

**Decision:** The `POST /jobs` body accepts optional fields: `initial_equity` (Decimal, server-validated range 10–100000), `start_date` (ISO string), `end_date` (ISO string). Server applies these to the loaded `BacktestConfig` before passing to `BacktestHarness`. No other fields are accepted from the client.

**Rationale:** These are safe scalars; they don't involve class loading or path manipulation. They make the page genuinely useful beyond re-running frozen YAML.

**Alternative:** No overrides — rejected (page becomes a "run the same thing" button with no iteration value).

### D7. Cancel

**Decision:** `POST /jobs/{id}/cancel` sends `SIGTERM` to the worker PID (stored in SQLite), waits briefly, then `SIGKILL` if still alive. Status transitions to `cancelled`. Partial artifacts (log, incomplete report) are retained with a warning.

**Rationale:** One endpoint, one signal, one state transition. Operators need this for 5+ minute runs.

### D8. Preset discovery

**Decision:** `GET /presets` scans `hbot/data/backtest_configs/*.yml`, parses each with `load_backtest_config`, returns `[{ id, label, strategy, pair, resolution }]`. UI fetches this on page mount. No static mirror that can drift.

**Rationale:** Single source of truth; adding a YAML file to the directory automatically makes it available.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Long runs exhaust CPU/disk | `max_concurrent_jobs=1`, wall-clock timeout (default 600s), cancel endpoint |
| SQLite file corruption under concurrent writes | Single writer (API process); WAL mode; job table is append-mostly |
| SSE connection dropped by proxy | `EventSource` auto-reconnects; nginx `proxy_buffering off` for SSE path |
| Progress file stale if harness crashes | API detects dead PID → marks job `failed`; stale progress is overwritten by terminal status |
| Safe overrides can still cause slow runs (huge date range) | Server validates `end - start ≤ max_days` (e.g. 180 days); reject or warn |
| Path traversal on preset_id | `GET /presets` returns canonical ids; `POST /jobs` resolves preset_id via map lookup, never path concatenation |

## Migration Plan

1. Fix harness metrics (position series, regime, win rate, progress) — test with CLI `run_backtest_v2` first.
2. Deploy API routes + SQLite + SSE on existing service (or new module in compose).
3. Add nginx location; smoke: `POST` preset → SSE log stream → `GET` status → completed.
4. Ship frontend page.
5. **Rollback:** Remove nginx location; disable route in TopBar; CLI is unaffected.

## Open Questions

- Exact endpoint prefix: `/api/backtest/` vs `/api/v1/backtest/` — follow whatever convention the existing API uses.
- Should `GET /presets` expose the full YAML content for operator review, or just metadata?
