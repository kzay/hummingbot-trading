## Why

The Strategy Research Lab and LLM Exploration Agent produce evaluation results, robustness scores, lifecycle states, and exploration session logs — all stored as local files (JSONL, JSON, YAML, Markdown). There is no way to view or monitor this data from the realtime dashboard. Operators must SSH into the host and parse files manually. Connecting the research pipeline to the dashboard enables at-a-glance visibility into strategy evaluation status, score trends, and live exploration progress — critical for a research workflow that generates dozens of candidates per session.

## What Changes

- **New REST API endpoints** on the existing `realtime_ui_api` Starlette service to expose research data (candidates, evaluations, scores, lifecycle, explorations).
- **New SSE endpoint** for live-streaming exploration session logs (mirrors the existing backtest log SSE pattern).
- **New `ResearchPage` React component** in the dashboard UI with sub-views: scoreboard, candidate detail, and exploration monitor.
- **New TypeScript types and API client** (`types/research.ts`, `utils/researchApi.ts`) following the backtest pattern.
- **Sidebar, TopBar, keyboard shortcuts** extended with the `"research"` view entry.
- **No changes to the research lab Python modules** — the API reads their output files directly.

## Capabilities

### New Capabilities
- `research-api`: Backend REST + SSE endpoints serving research lab data (candidates, evaluations, scores, lifecycle, explorations) from the existing file-based output.
- `research-ui`: Frontend React page with scoreboard, candidate detail, score visualisation, and live exploration log streaming.

### Modified Capabilities
_(none — no existing spec-level requirements change)_

## Impact

- **Backend**: `hbot/services/realtime_ui_api/` gains a new `research_api.py` sub-app mounted on `/api/research/*`, following the same auth and Starlette patterns as `backtest_api.py`.
- **Frontend**: New files under `hbot/apps/realtime_ui_v2/src/` (component, types, API util). Minor edits to `App.tsx`, `Sidebar.tsx`, `TopBar.tsx`, `useKeyboardShortcuts.ts`, `useReviewData.ts` for view registration.
- **Dependencies**: None new — all reads use stdlib (`json`, `pathlib`, `glob`). Frontend uses existing React + lightweight-charts stack.
- **Risk**: Read-only integration; no writes to research data. Low risk of side effects on the research pipeline.
