## Why

The backtesting engine (`BacktestHarness`, YAML presets, reports under `hbot/reports/backtest/`) is production-quality but **CLI-only**. Operators who already live in the realtime dashboard must context-switch to SSH to run the same validation — a split brain between "what the bot is doing now" and "what the harness says on historical data." That friction slows promotion checks, confuses less-technical stakeholders, and weakens auditability (who ran what, when, with which preset).

Beyond access, the harness itself has **incomplete metrics wiring**: `win_rate` returns `NaN`, `position_series` is never populated, regime attribution is counted but not forwarded to `compute_all_metrics`. Shipping a UI on top of broken numbers would destroy trust faster than having no UI at all.

This change delivers a **semi-professional** backtest page: trigger runs from the browser with safe parameter overrides, watch real-time progress and logs, review **visual results** (equity curve, metric cards, regime breakdown), browse **job history**, and compare outcomes — using the same harness as CLI but with the metrics gaps fixed first.

## Challenges this addresses

| Challenge | How the proposal addresses it |
|-----------|-------------------------------|
| **Remote execution risk** | Browser sends only **server-allowlisted** `preset_id`; safe scalar overrides (equity, dates) are validated server-side; no arbitrary `strategy_class` or YAML upload. |
| **Long-running CPU blocking HTTP** | Jobs run **out-of-process** (subprocess/pool); API returns `job_id` immediately. |
| **Broken metrics shown to operators** | Fix harness → `compute_all_metrics` wiring (position series, regime data, win rate, profit factor) as a prerequisite task **before** building the UI. |
| **No visual results** | Equity curve chart using existing `lightweight-charts` library; styled metric cards; warnings strip; fill distribution (phase 2). |
| **No progress feedback** | Harness emits `progress_pct` (it knows `total_ticks` upfront); status API includes progress; UI shows determinate progress bar. |
| **Choppy log delivery** | SSE (Server-Sent Events) for log streaming — FastAPI supports this natively; dashboard already has `EventSource` browser API available; no WebSocket overhead for a unidirectional stream. |
| **Ephemeral runs** | SQLite job store (one table, zero-config) survives restarts and enables a **job history list** with sorting and filtering. |
| **No run comparison** | Job history table with sortable metrics; side-by-side comparison of two selected runs (phase 2). |
| **Frozen presets** | Safe overrides (`initial_equity`, `start_date`, `end_date`) submitted alongside `preset_id` and validated against ranges. No class loading from client. |
| **Stuck perception** | Terminal states (`completed` / `failed` / `cancelled` / `timed_out`) with `updated_at`; timeout path must set terminal state. |
| **No cancel** | `POST /jobs/{id}/cancel` sends SIGTERM to worker; status transitions to `cancelled`. |
| **Deployment consistency** | API behind same auth + reverse-proxy as dashboard (`apiBase`, token, nginx location). |
| **Host protection** | Concurrency cap (`max_concurrent_jobs`) + wall-clock timeout + cancel endpoint. |
| **CLI vs UI parity** | Dashboard invokes same `load_backtest_config` → `BacktestHarness.run()` path; no duplicate simulation in Node or browser. |
| **Preset list out of sync** | API exposes `GET /presets` that scans server-side directory; UI fetches it dynamically. |

### Residual challenges (accepted limits for MVP)

| Limit | Why acceptable | Follow-up |
|-------|----------------|-----------|
| Log/report disk growth | Manageable for single-operator deployments. | Rotation policy, max retained jobs. |
| Single-tenant trust model | One operator team per deployment. | Per-user quotas if multi-tenant needed. |
| No sweep/walk-forward UI | CLI covers advanced quant workflows. | Future phase. |
| No fill scatter or regime chart in v1 | Metric cards + equity curve + warnings cover 80% of value. | Add in fast follow-up once data is wired. |

## Success criteria (MVP)

- An authenticated operator can start a run from a **named preset** with optional **safe overrides** (equity, dates), see a **determinate progress bar**, read **streaming log lines**, and review **visual results** (equity chart + metric cards + warnings) without using the CLI.
- Results include valid **win rate**, **profit factor**, **inventory half-life**, and **regime metrics** — not NaN/zero placeholders.
- **Job history** persists across restarts; operator can see their last N runs and their outcomes.
- **Cancel** terminates a running job promptly.
- CLI and dashboard runs for the same preset + data produce comparable reports (same code path).
- Unknown presets, invalid overrides, and unauthenticated calls are rejected; no arbitrary code execution.
- Every job has a stable `job_id` that appears in API responses, log filenames, and report paths for correlation.

## What Changes

### Prerequisite: harness metrics fixes

- Wire `position_series` (tick-level position history) from harness loop into `compute_all_metrics` so inventory half-life works.
- Forward `regime_ticks` → `returns_by_regime` / `fills_by_regime` so regime-conditional Sharpe is computed.
- Implement `win_rate` from round-trip fill pairs (FIFO matching on `FillRecord` list).
- Call `profit_factor` with gross profit/loss derived from fills.
- Fix equity snapshot `daily_return_pct` to use prior-day equity, not initial equity.
- Add `progress_pct` emission from the harness loop (write to a shared progress file or pipe).

### New: backtest control API

- `GET /presets` — scan allowlisted YAML directory, return list with metadata (strategy name, pair, resolution).
- `POST /jobs` — create job from `preset_id` + optional overrides; validate; start worker; return `job_id`.
- `GET /jobs/{id}` — status, progress_pct, timestamps, result summary or path, error.
- `GET /jobs/{id}/log` — SSE stream of log lines while running; full log on completed.
- `POST /jobs/{id}/cancel` — SIGTERM worker; set `cancelled`.
- `GET /jobs` — list all jobs (from SQLite), sortable by date/status.
- Job metadata persisted to **SQLite** (single file, zero config, survives restarts).
- Auth aligned with existing dashboard API (token / same-origin).
- Concurrency cap + wall-clock timeout enforced.

### New: dashboard backtest page

- Route `/backtest` (or `backtest` tab) in TopBar navigation.
- **Run panel**: preset dropdown (from `GET /presets`), safe override fields (equity, dates), Run / Cancel buttons.
- **Progress bar**: determinate, driven by `progress_pct` from status polling.
- **Log panel**: scrollable, fed by SSE stream; auto-scroll with lock.
- **Results panel** (on completion):
  - **Equity curve chart** — `lightweight-charts` `LineSeries`, reusing the theme from `DailyReviewPanel`.
  - **Metric cards** — total return, Sharpe, Sortino, Calmar, max DD (% and duration), fill count, maker ratio, fee drag, inventory half-life.
  - **Warnings strip** — `result.warnings[]` styled as alert badges.
  - **Download buttons** — JSON report, equity CSV.
- **Job history table**: list of past runs with date, preset, status, key metrics, click-to-view.

### Infrastructure

- API routes added to existing Python service (preferred) or new FastAPI module in compose.
- nginx location `/api/backtest/` → upstream.
- SQLite file under `hbot/data/backtest_jobs.db` (or similar).

**Explicitly deferred:** Sweep/walk-forward from UI; raw YAML upload; fill scatter plot; regime breakdown chart; side-by-side run comparison overlay; multi-user auth.

## Capabilities

### New Capabilities

- `backtest-control-api`: HTTP API for job lifecycle (create, status, log stream, cancel, history), process isolation, allowlisted presets with safe overrides, SSE log delivery, SQLite persistence, progress reporting, timeouts and concurrency limits.
- `dashboard-backtest-view`: Dashboard route with run controls, determinate progress bar, SSE log panel, equity curve chart, metric cards, warnings, job history table, download links.

### Modified Capabilities

_(none — additive integration; no existing OpenSpec requirement documents are amended.)_

## Impact

- **Harness fixes**: `hbot/controllers/backtesting/harness.py`, `hbot/controllers/backtesting/metrics.py` — wiring and implementation fixes (position series, regime, win rate, profit factor, daily return, progress).
- **New backend code**: Python service module or routes; SQLite job store; SSE streaming.
- **Frontend**: `hbot/apps/realtime_ui_v2/` — route, page component(s), chart integration, types, fetch/SSE helpers, job history.
- **Infrastructure**: `docker-compose.yml` + `nginx.conf` — new location or upstream.
- **Dependencies**: `aiosqlite` or stdlib `sqlite3` (Python); no new frontend deps (lightweight-charts already present).
- **Reuse**: `BacktestHarness`, `load_backtest_config`, existing presets, `lightweight-charts` + chart theme from `DailyReviewPanel`, `Panel` component, existing auth pattern.

## Out of scope

- Changing sweep, walk-forward, or book synthesizer behavior.
- Live trading or connector integration from the backtest page.
- Multi-user isolation beyond single-deployment operator use.
- Strategy editing in the browser.

## Related change

Engine and harness requirements live under `openspec/changes/backtesting-engine/`. This proposal does not re-open engine architecture — only fixes **metrics wiring gaps**, adds **exposure** via API, and delivers a **visual UX layer** from the dashboard.
