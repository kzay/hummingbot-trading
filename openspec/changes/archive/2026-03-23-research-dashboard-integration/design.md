## Context

The realtime dashboard (`realtime_ui_v2`) already serves a backtest page that follows a proven pattern: a Starlette sub-app (`backtest_api.py`) mounted on the main `realtime_ui_api`, a dedicated React page lazy-loaded via `App.tsx`, TypeScript types, and an API client module. The Strategy Research Lab outputs evaluation data to `hbot/data/research/` as flat files (YAML candidates, JSONL experiment manifests, JSON lifecycle states, Markdown reports, and exploration session YAMLs). The integration reads these files through new REST + SSE endpoints without modifying any research module.

## Goals / Non-Goals

**Goals:**
- Expose all research lab outputs via REST endpoints on the existing `realtime_ui_api`.
- Provide SSE streaming for live exploration session log tailing (following the backtest log pattern).
- Add a `ResearchPage` in the dashboard with a scoreboard, candidate detail view, and exploration monitor.
- Follow existing patterns exactly (Starlette sub-app, lazy-loaded React page, sidebar/topbar/keyboard registration).

**Non-Goals:**
- Triggering or controlling exploration sessions from the UI (future scope — would require a process manager like backtest).
- Writing or mutating research data from the dashboard (read-only integration).
- Adding new Python dependencies to the research modules.
- Real-time push of evaluation events via WebSocket (SSE for log streaming is sufficient for v1).
- Score trend charts over time (v1 shows the latest score; historical charting is a follow-up).

## Decisions

### D1: Mount as Starlette sub-app on existing API

**Choice:** Create `hbot/services/realtime_ui_api/research_api.py` and mount it on the existing `main.py` app at `/api/research`.

**Rationale:** This is exactly how `backtest_api.py` works. No new services, no new ports, no new Docker containers. The research data lives on the same filesystem as the API service.

**Alternatives considered:**
- Separate microservice — rejected; adds deployment complexity for a read-only data reader.
- Embed in the main `realtime_ui_api/main.py` directly — rejected; the backtest precedent shows sub-apps scale better.

### D2: File-based reads, no database

**Choice:** Read research data directly from `hbot/data/research/` using `pathlib` and `json`/`yaml` parsing. No SQLite or other persistence layer.

**Rationale:** The research lab already writes structured files (JSONL manifests, JSON lifecycle states, YAML candidates). Adding a database would require a sync mechanism. The data volume is low (tens of candidates, not thousands).

**Alternatives considered:**
- SQLite mirroring (like backtest `JobStore`) — rejected; unnecessary for read-only access to ~10-50 files.
- Redis cache — rejected; adds infrastructure for negligible latency gain on local file reads.

### D3: SSE for exploration log streaming

**Choice:** Add `GET /api/research/explorations/{session_id}/log` as an SSE endpoint that tail-follows the exploration session's output directory for new iteration YAML files.

**Rationale:** Mirrors the backtest log SSE pattern (`GET /api/backtest/jobs/{id}/log`). EventSource is simple, works with the existing auth token-in-query-param pattern, and doesn't require WebSocket protocol changes.

**Implementation detail:** Unlike backtest (which tails a single `run.log` file), exploration sessions produce per-iteration YAML files (`iter_01_name.yml`, `iter_02_name.yml`, ...) and a `session_result.json` at completion. The SSE generator polls the directory for new files and emits events as they appear, then sends a `done` event when `session_result.json` exists.

### D4: Frontend follows backtest page pattern exactly

**Choice:** Create `ResearchPage.tsx` as a single-file page component with inline sub-components (like `BacktestPage.tsx`), plus `types/research.ts` and `utils/researchApi.ts`.

**Rationale:** The backtest page is the established pattern. Consistency reduces cognitive load and review effort.

**Sub-views within the page:**
1. **Scoreboard** (default) — table of all candidates with lifecycle state, best score, recommendation.
2. **Candidate Detail** — expanded view when clicking a row: score breakdown bar chart, lifecycle timeline, experiment history, inline Markdown report.
3. **Exploration Monitor** — list of exploration sessions; clicking one opens live SSE log + iteration results.

Navigation between sub-views is local state within `ResearchPage` (no URL router needed, matching backtest precedent).

### D5: View registration pattern

**Choice:** Add `"research"` to `ActiveView` union, sidebar nav (under "Dashboard" group between "Backtest" and "Analytics"), TopBar `VIEW_OPTIONS`, keyboard shortcuts `VIEW_ORDER`, and `useReviewData` allowlist.

**Rationale:** Follows the exact 5-point wiring documented in the codebase exploration.

### D6: UX/UI and Layout Decisions

**Choice:** Leverage existing layout grids (`.layout-grid`, `.panel`) and typography to maintain visual continuity with the rest of the dashboard. Specifically:
- **Scoreboard view:** Full width `<section className="panel panel-span-12">`. Data visualization for the score should be an inline CSS-based progress bar (no heavy charting libraries needed). Badges for lifecycle states will reuse or mimic existing `.status-badge` or `statusColor` patterns (`rounded-full px-2 py-1 text-xs font-semibold`).
- **Detail view:** Split layout. Left column (`panel-span-4`) for candidate metadata (hypothesis, logic snippets). Right column (`panel-span-8`) for the horizontal score breakdown bars, timeline, and experiment history. 
- **Colors:** Use semantic colors already established in the app (e.g., `var(--status-success)` for `pass` or `promoted`, `var(--status-warning)` for `revise`, `var(--status-error)` for `rejected`).
- **Typography:** Markdown reports will be rendered using a clean, dark-mode friendly typographic scale inside a dedicated `<div className="markdown-body">` wrapper within a panel.

**Rationale:** A "pixel-perfect" integration requires feeling native to the host app. Reusing BEM-like classes (`panel-span-12`, `panel-span-6`) and semantic CSS variables avoids injecting external UI frameworks (like Tailwind, unless already natively supported) while keeping the bundle size small and maintaining consistency.

## Risks / Trade-offs

- **[Stale data]** File reads may show slightly outdated data if an evaluation is in progress. → *Mitigation:* The scoreboard auto-refreshes every 30 seconds (configurable). Acceptable for a research monitoring tool.
- **[Large reports]** Markdown reports can be 2-5 KB each; loading all at once for the scoreboard is wasteful. → *Mitigation:* The list endpoint returns summary data only (name, score, lifecycle, recommendation). Full report is fetched on demand in the detail view.
- **[Exploration session detection]** There's no central registry of exploration sessions; we must scan the `explorations/` directory for subdirectories. → *Mitigation:* Each `ExplorationSession` writes a `session_result.json` on completion and iteration YAMLs during execution. We can enumerate sessions by scanning subdirectories.
- **[No process control]** The dashboard cannot start/stop explorations in v1. → *Mitigation:* This is an explicit non-goal. Future scope would add a process manager similar to backtest's `_spawn_worker`.
- **[Auth consistency]** The SSE endpoint must use query-param token authentication (EventSource limitation). → *Mitigation:* Already solved by the backtest SSE pattern — reuse `auth_check(request)` and `?token=` fallback.
