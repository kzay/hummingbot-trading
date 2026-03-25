# Frontend Code Health Spec

## Context

The March 2026 frontend loop INITIAL_AUDIT scored the `realtime_ui_v2` application across 6 dimensions. Key findings: keyboard shortcuts are inconsistent (documented range doesn't match implementation), API responses from research/backtest endpoints lack Zod validation, the main dashboard uses `any` types, the Zustand store is 1,780 lines with mixed responsibilities, and research/backtest pages embed transport logic in rendering components.

## ADDED Requirements

### Requirement: Keyboard shortcuts 1–9 all function correctly

`useKeyboardShortcuts.ts` SHALL handle digits 1–9 (not just 1–8). `ShortcutHelp.tsx` SHALL document all 9 shortcuts matching the labels in `TopBar.tsx`.

**Verification**: Pressing each key 1–9 in the browser navigates to the correct view. `ShortcutHelp.tsx` lists all 9 entries.

### Requirement: Research and backtest API responses are Zod-validated

`researchApi.ts` and `backtestApi.ts` SHALL define Zod schemas for all `res.json()` response shapes. Bare `as Type` casts on API data SHALL be replaced with `schema.parse()`. Parse failures SHALL return a structured error, not crash the component.

**Verification**: `npm run build` succeeds. No `as CandidateDetail`, `as BacktestJobStatus`, or `as BacktestResultSummary` casts remain on `res.json()` data.

### Requirement: No `any` types in production components

`RealtimeDashboard.tsx` SHALL not use `any`. Grid layout callbacks SHALL use proper types from `@types/react-grid-layout`.

**Verification**: `npx tsc --noEmit` passes with zero errors related to `any` in `RealtimeDashboard.tsx`.

### Requirement: ResearchPage and BacktestPage are pure rendering components

SSE transport, fetch logic, and state management SHALL be extracted into dedicated hooks (`useResearchData.ts`, `useBacktestData.ts`). Pages SHALL import and call these hooks; no `fetch()`, `EventSource`, or `AbortController` in the page component bodies.

**Verification**: `ResearchPage.tsx` and `BacktestPage.tsx` contain no `fetch(`, `new EventSource(`, or `AbortController` calls. Each is under 300 lines.

### Requirement: BotGateBoardPanel distinguishes loading from empty

`BotGateBoardPanel.tsx` SHALL pass a `loading` prop to `Panel` when gate data has not yet arrived. "No gate status available" SHALL only render after data is confirmed loaded and empty.

**Verification**: On fresh page load, the panel shows a loading indicator before gate data arrives.

### Requirement: TopBar shows explicit "STALE" label

When `ageMs > 30000` (30 seconds), the TopBar SHALL display a visible "STALE" label (red text) adjacent to the numeric data age.

**Verification**: Disconnecting the API for >30s causes "STALE" to appear. Reconnecting clears it.

## MODIFIED Requirements

### Requirement: useDashboardStore.ts is decomposed into focused stores

The monolithic 1,780-line `useDashboardStore.ts` SHALL be split into:
- `useConnectionStore.ts` — WebSocket/REST transport state, health, reconnect
- `useAlertStore.ts` — alerts, alert history, gate status
- `useDashboardStore.ts` — market data, fills, orders, position state (remaining)

Each file SHALL be under 800 lines. Existing selectors in `selectors.ts` SHALL continue to work.

**Verification**: `useDashboardStore.ts` is under 800 lines. `npx vitest run` passes. `npm run build` succeeds.

### Requirement: realtimeParsers.ts is split by domain

The 717-line `realtimeParsers.ts` SHALL be split into:
- `parsers/marketParsers.ts`
- `parsers/telemetryParsers.ts`
- `parsers/reviewParsers.ts`

A barrel re-export from `realtimeParsers.ts` SHALL maintain backward compatibility.

**Verification**: No import changes required in consuming files. `npm run build` succeeds.

## Metrics to Track Next Cycle

| Metric | Baseline | Target |
|--------|----------|--------|
| `any` count in production `src/components/` | 3 | 0 |
| Unvalidated API response casts | 5+ | 0 |
| Largest component file (lines) | 680 (ResearchPage) | < 350 |
| `useDashboardStore.ts` lines | 1,780 | < 800 |
| `realtimeParsers.ts` lines | 717 | < 200 (barrel) |
| Keyboard shortcut coverage | 8/9 | 9/9 |
| `App.css` lines | 1,904 | < 1,400 |
