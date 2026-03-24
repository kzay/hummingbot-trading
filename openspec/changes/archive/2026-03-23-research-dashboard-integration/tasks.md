## 1. Backend — Research API Sub-app

- [x] 1.1 Create `hbot/services/realtime_ui_api/research_api.py` with Starlette routes and file-reading helpers: `_scan_candidates()`, `_read_lifecycle()`, `_read_experiments()`, `_scan_explorations()`.
- [x] 1.2 Implement `GET /api/research/candidates` — scan `data/research/candidates/*.yml`, parse each with `StrategyCandidate.from_yaml`, cross-reference lifecycle state and best experiment score, return JSON array sorted by `best_score` descending.
- [x] 1.3 Implement `GET /api/research/candidates/{name}` — return full candidate data, lifecycle state with transition history, experiment manifest entries (from JSONL), and latest report path.
- [x] 1.4 Implement `GET /api/research/reports/{candidate_name}/{run_id}` — serve the Markdown report file as `text/markdown`.
- [x] 1.5 Implement `GET /api/research/explorations` — scan `data/research/explorations/` subdirectories, determine status from `session_result.json` presence, count iteration YAMLs, return JSON array.
- [x] 1.6 Implement `GET /api/research/explorations/{session_id}` — return `SessionResult` JSON if completed, or partial iteration state if running.
- [x] 1.7 Implement `GET /api/research/explorations/{session_id}/log` SSE endpoint — poll session directory for new iteration YAML files at 1-second intervals, emit `event: iteration` with parsed data, emit `event: done` when `session_result.json` appears.
- [x] 1.8 Apply `auth_check(request)` to all endpoints; support `?token=` query param on the SSE endpoint.

## 2. Backend — Mount and Integration

- [x] 2.1 Mount `research_api` sub-app on the main `realtime_ui_api` Starlette app in `main.py` at the `/api/research` prefix.
- [x] 2.2 Add `RESEARCH_DATA_DIR` env var to `.env.template` (default `data/research`).

## 3. Frontend — Types and API Client

- [x] 3.1 Create `hbot/apps/realtime_ui_v2/src/types/research.ts` with TypeScript interfaces: `ResearchCandidate`, `CandidateDetail`, `ComponentScore`, `ScoreBreakdown`, `ExperimentEntry`, `LifecycleTransition`, `ExplorationSession`, `IterationEvent`.
- [x] 3.2 Create `hbot/apps/realtime_ui_v2/src/utils/researchApi.ts` with fetch functions: `fetchCandidates()`, `fetchCandidateDetail(name)`, `fetchReport(name, runId)`, `fetchExplorations()`, `fetchExplorationDetail(sessionId)`, `explorationLogUrl(apiBase, sessionId, token)`. Follow `backtestApi.ts` patterns (headers, timeout, error handling).

## 4. Frontend — ResearchPage Component (UX/UI Implementation)

- [x] 4.1 Create `hbot/apps/realtime_ui_v2/src/components/ResearchPage.tsx` with local state for sub-view navigation (`scoreboard` | `detail` | `explorations`). Use the main `<div className="layout-grid">` wrapper.
- [x] 4.2 Implement Scoreboard sub-view (`panel-span-12`) — table with columns (Name, Adapter, Lifecycle badge, Score bar, Recommendation, Experiments). Use semantic colors (`var(--status-success)`, etc.) for lifecycle badges (`rounded-full px-2 py-1 text-xs`). Implement a pure CSS horizontal bar for the score column. Add 30-second auto-refresh and empty state handling.
- [x] 4.3 Implement Candidate Detail sub-view (Split Layout) — Left column (`panel-span-4`) for hypothesis, entry/exit logic, and parameter space JSON. Right column (`panel-span-8`) for CSS-based horizontal score breakdown chart, lifecycle vertical stepper timeline, and experiment history table.
- [x] 4.4 Implement Markdown viewer for Candidate Detail — When a report is selected, render it inside a `<div className="markdown-body">` wrapper below the history table, ensuring dark-mode compatible typography.
- [x] 4.5 Implement Exploration Monitor sub-view — Left column (`panel-span-4`) for sessions table. Right column (`panel-span-8`) for SSE live log panel (reusing `LogPanel` styling from `BacktestPage`) and completed session summary display.
- [x] 4.6 Implement error handling — dismissible error banners styled as inline panel alerts for network errors, 404s, and 500s.

## 5. Frontend — View Registration

- [x] 5.1 Add `"research"` to `ActiveView` type in `hooks/useReviewData.ts` and include it in the storage allowlist.
- [x] 5.2 Add "Research" button to `Sidebar.tsx` in the "Dashboard" group (between "Backtest" and "Analytics"), with a beaker/flask SVG icon.
- [x] 5.3 Add "Research" entry to `VIEW_OPTIONS` in `TopBar.tsx` with shortcut digit.
- [x] 5.4 Add `"research"` to `VIEW_ORDER` in `hooks/useKeyboardShortcuts.ts`.
- [x] 5.5 Add lazy import and conditional render block for `ResearchPage` in `App.tsx` following the `BacktestPage` pattern.

## 6. Verification

- [x] 6.1 Compile-check `research_api.py` with `python -m py_compile`.
- [x] 6.2 Manually verify the scoreboard renders with the example candidate (`example_mean_reversion.yml`) — or write a simple smoke test.
- [x] 6.3 Verify TypeScript compiles: `npx tsc --noEmit` in the `realtime_ui_v2` directory.
- [x] 6.4 Verify sidebar, top bar, and keyboard shortcuts include the "Research" view.
