## 1. Harness metrics fixes (prerequisite)

- [x] 1.1 Implement `win_rate` in `metrics.py` using FIFO round-trip matching on `FillRecord` list (replace NaN stub).
- [x] 1.2 Compute `gross_profit` and `gross_loss` from round-trip fills; call `profit_factor()` from `compute_all_metrics`.
- [x] 1.3 Collect `position_series` (tick-level `float(position_base)` list) in harness loop; pass to `compute_all_metrics` so inventory half-life is computed.
- [x] 1.4 Build `returns_by_regime` and `fills_by_regime` dicts from `regime_ticks` + fills in harness loop; pass to `compute_all_metrics` for regime-conditional Sharpe.
- [x] 1.5 Fix equity snapshot `daily_return_pct` to use prior-day equity instead of initial equity.
- [x] 1.6 Add progress emission: harness writes `{job_dir}/progress.json` with `current_tick`, `total_ticks`, `progress_pct` every 1000 ticks (when `job_dir` is set in config, no-op otherwise).
- [x] 1.7 Run `pytest hbot/tests/controllers/test_backtesting/` — verify existing tests pass; add a test for win_rate round-trip matching and progress file emission.
- [x] 1.8 Smoke-test full CLI run: `python -m scripts.backtest.run_backtest_v2 --config hbot/data/backtest_configs/bot1_baseline.yml` — verify results include non-NaN win_rate, non-zero inventory_half_life, and regime_metrics.

## 2. API: preset discovery and job store

- [x] 2.1 Choose API host (extend existing Python service vs new FastAPI module); document decision in a code comment.
- [x] 2.2 Create SQLite schema: `jobs` table (id, preset_id, overrides_json, status, progress_pct, created_at, updated_at, result_summary_json, error, log_path, report_path, pid). Init on startup with `CREATE TABLE IF NOT EXISTS`.
- [x] 2.3 Implement `GET /presets` — scan `hbot/data/backtest_configs/*.yml`, parse each, return `[{ id, label, strategy, pair, resolution, initial_equity, start_date, end_date }]`.
- [x] 2.4 Implement auth middleware matching existing dashboard API pattern (token header check).

## 3. API: job lifecycle

- [x] 3.1 Implement `POST /jobs` — validate `preset_id` against allowlist; validate overrides (equity range, date range ≤ max_days); create SQLite row; spawn subprocess running `BacktestHarness` with log redirect to `hbot/reports/backtest/jobs/{job_id}/run.log` and progress file path set.
- [x] 3.2 Implement `GET /jobs/{id}` — read SQLite row + progress file; return status, progress_pct, timestamps, result_summary (if completed), error (if failed).
- [x] 3.3 Implement `GET /jobs/{id}/log` as SSE (`text/event-stream`) — tail the log file, yield lines as SSE events; close stream on terminal state. Include `id` field in events for `Last-Event-ID` reconnection.
- [x] 3.4 Implement `POST /jobs/{id}/cancel` — SIGTERM worker PID, brief wait, SIGKILL if alive; update SQLite row to `cancelled`.
- [x] 3.5 Implement `GET /jobs` — list all jobs from SQLite, sorted by `created_at` desc; include key result metrics for completed jobs.
- [x] 3.6 Implement worker completion callback: on subprocess exit, update SQLite (status, result_summary from report JSON, error if non-zero exit).
- [x] 3.7 Implement stale job detection on startup: scan SQLite for `status=running`, check PIDs, mark dead ones `failed`.
- [x] 3.8 Enforce `max_concurrent_jobs` (reject with 429) and `max_wall_time_s` (watchdog timer kills worker, sets `timed_out`).
- [x] 3.9 Add pytest: preset listing, job creation happy path (mock harness), override validation, unknown preset rejection, cancel flow.

## 4. Infrastructure

- [x] 4.1 Add or extend Docker service for the API in `docker-compose.yml`; set `PYTHONPATH`, mount volumes for configs/reports/data.
- [x] 4.2 Update `nginx.conf` to proxy `/api/backtest/` to the API upstream; set `proxy_buffering off` for SSE path. (N/A — nginx serves static files only; frontend calls API directly at configured host:port)
- [x] 4.3 Smoke-test from host: `POST /presets` → `POST /jobs` → SSE log → `GET /jobs/{id}` → completed with summary.

## 5. Dashboard UI: page shell and run panel

- [x] 5.1 Add `"backtest"` to `ActiveView` type and `VIEW_OPTIONS` in `TopBar.tsx` (label "Backtest", shortcut "7").
- [x] 5.2 Create `BacktestPage.tsx` with three sections: run panel (top), log + results (middle), job history (bottom). Use `Panel` component for visual consistency.
- [x] 5.3 Wire route in `App.tsx` / `RealtimeDashboard.tsx` so `activeView === "backtest"` renders `BacktestPage`.
- [x] 5.4 Add types: `BacktestPreset`, `BacktestJob`, `BacktestJobStatus`, `BacktestResultSummary` in a new types file or extend `realtime.ts`.
- [x] 5.5 Add fetch helpers: `fetchPresets()`, `createJob()`, `fetchJobStatus()`, `cancelJob()`, `fetchJobHistory()` using `apiBase` + token headers.

## 6. Dashboard UI: run controls and progress

- [x] 6.1 Build preset dropdown (populated from `fetchPresets` on mount); show strategy name, pair, resolution per option.
- [x] 6.2 Build override fields: `initial_equity` (number input), `start_date`, `end_date` (date inputs); pre-fill from selected preset defaults.
- [x] 6.3 Build Run button (disabled when job running) and Cancel button (visible when running).
- [x] 6.4 Build determinate progress bar: driven by `progress_pct` from status polling (1–2s interval while running); show percentage label; success/error colors on terminal state.
- [x] 6.5 Implement polling lifecycle: start on job creation, stop on terminal state, clean up on unmount.

## 7. Dashboard UI: log panel (SSE)

- [x] 7.1 Build SSE log panel: open `EventSource` to `/api/backtest/jobs/{id}/log` on job start; append lines to a scrollable `<pre>` or virtualized list.
- [x] 7.2 Implement auto-scroll with scroll-lock: auto-scroll to bottom by default; pause when user scrolls up; show "Jump to bottom" button.
- [x] 7.3 Close `EventSource` on terminal state or unmount; retain log content for viewing.
- [x] 7.4 Handle SSE auth: pass token via query param or custom header (EventSource limitation — may need polyfill or fetch-based SSE if header auth required).

## 8. Dashboard UI: results panel

- [x] 8.1 Build metric cards row: total return, Sharpe, Sortino, Calmar, max DD (% + duration), fill count, maker ratio, fee drag, inventory half-life. Format NaN/missing as "—".
- [x] 8.2 Extract `EquityCurveChart` from `DailyReviewPanel.tsx` into a shared component (or duplicate with same theme); feed it `equity_curve[]` from result mapped to `{ time, value }`.
- [x] 8.3 Build warnings strip: render each `warnings[]` entry as a styled alert badge.
- [x] 8.4 Build download buttons: link to JSON report and equity CSV paths from result.
- [x] 8.5 Build error state: show error message from API when job failed; keep log panel accessible.

## 9. Dashboard UI: job history table

- [x] 9.1 Build job history table: fetch from `GET /jobs` on mount; columns: date, preset, status (color badge), return, Sharpe, max DD.
- [x] 9.2 Click-to-view: clicking a completed row loads its result summary into results panel and fetches its log.
- [x] 9.3 Running job row: show at top with "running" badge and progress percentage.
- [x] 9.4 Auto-refresh history after a job completes.

## 10. Hardening and tests

- [x] 10.1 Verify no path traversal on preset_id (map lookup, not path concat).
- [x] 10.2 Vitest tests: preset dropdown rendering, metric card formatting (NaN → "—"), progress bar states, job history table rendering.
- [x] 10.3 Run `npx vitest run` in `realtime_ui_v2` — all tests pass (111/111).
- [x] 10.4 Run Python API tests — all pass (57/57).
- [ ] 10.5 End-to-end smoke: select preset → override equity → Run → watch progress bar + SSE logs → results with chart + metrics → job appears in history → click history row → view past results.
