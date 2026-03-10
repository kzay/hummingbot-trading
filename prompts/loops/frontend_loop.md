# Frontend Loop — Recurring Frontend And Dependency Review

**Cadence**: Weekly or per release candidate  
**Mode**: Set MODE below before running

```text
MODE = INITIAL_AUDIT   ← first run: establish frontend baseline and identify all gaps
MODE = ITERATION       ← subsequent runs: compare vs last cycle, confirm fixes, find regressions
```

---

```text
You are a senior frontend engineer + design systems reviewer + web performance specialist
running a recurring review for the trading supervision frontend and its dependencies.

## System context
- Primary frontend: hbot/apps/realtime_ui_v2/ (React 19 + TypeScript + Vite + Zustand + Zod)
- Legacy fallback frontend: hbot/apps/realtime_ui/
- Frontend entry: hbot/apps/realtime_ui_v2/src/main.tsx
- Main shell: hbot/apps/realtime_ui_v2/src/App.tsx
- Components: hbot/apps/realtime_ui_v2/src/components/
- Hooks: hbot/apps/realtime_ui_v2/src/hooks/
- Store: hbot/apps/realtime_ui_v2/src/store/useDashboardStore.ts
- Shared types/utils: hbot/apps/realtime_ui_v2/src/types/ and src/utils/
- Frontend package: hbot/apps/realtime_ui_v2/package.json
- Lockfile: hbot/apps/realtime_ui_v2/package-lock.json
- API backend feeding the UI: hbot/services/realtime_ui_api/main.py
- Docker/runtime integration: hbot/apps/realtime_ui_v2/Dockerfile, hbot/apps/realtime_ui_v2/nginx.conf, hbot/compose/docker-compose.yml
- Docs: hbot/apps/realtime_ui_v2/README.md and hbot/apps/realtime_ui/README.md
- Scope rule: listed files/folders are anchors, not limits. Inspect any additional relevant paths in the repo.

## Current dependency baseline
- Runtime deps: react, react-dom, @tanstack/react-table, lightweight-charts, zod, zustand
- Tooling deps: vite, typescript, eslint, @eslint/js, typescript-eslint, @vitejs/plugin-react
- Review both runtime and devDependencies each cycle for:
  - outdated versions,
  - security issues,
  - unnecessary packages,
  - duplicate responsibilities,
  - migration opportunities with bounded risk.

## Inputs I will provide (paste values below)
- MODE: {{INITIAL_AUDIT or ITERATION}}
- Period covered: {{e.g. 2026-03-01 to 2026-03-08}}
- Target frontend: {{realtime_ui_v2 / legacy realtime_ui / both}}
- Release context: {{feature work / stabilization / pre-release / post-incident}}
- Build status: {{pass / fail}}
- Lint error count: {{N}}
- Type error count: {{N}}
- Bundle size (main chunks): {{list or "unknown"}}
- Build time: {{X s}}
- Largest route/panel render time: {{X ms or "unknown"}}
- Frontend console errors in period: {{N or examples}}
- API error rate surfaced in UI: {{X% or "unknown"}}
- Reconnect count for realtime transport: {{N}}
- Web Vitals / Lighthouse summary: {{paste or "not measured"}}
- Accessibility issues found: {{list or "none checked"}}
- Browser support target: {{latest Chrome only / desktop modern browsers / other}}
- Dependency updates available: {{list or "not checked"}}
- Dependency vulnerabilities / advisories: {{list or "none checked"}}
- Known debt from last cycle: {{paste or "first run"}}
- User/operator complaints: {{list or "none"}}

## Data completion protocol (non-blocking)
- If a placeholder can be inferred from repository context, known defaults, or recent reports, fill it.
- If a value is unknown, state `ASSUMPTION:` with a conservative estimate and continue.
- If evidence is missing for a claim, state `DATA_GAP:` and reduce confidence for that finding.
- Never stop the review only because some inputs are missing; produce best-effort output.

---

## PHASE 1 — Baseline / delta

### If MODE=INITIAL_AUDIT
Score each dimension 0–10 and document current state:
| Dimension | Score | Evidence | Top risk |
|---|---|---|---|
| UX clarity | | | |
| Runtime reliability | | | |
| Performance | | | |
| Code health | | | |
| Accessibility | | | |
| Dependency hygiene | | | |

### If MODE=ITERATION
For each dimension: current score vs last cycle score + what changed.
Confirm: did last cycle's fixes have the expected effect?
Identify: any new regressions introduced since last cycle?

---

## PHASE 2 — Product and UX review

### Operator workflow correctness
- Can an operator understand system state within 5 seconds after opening the app?
- Are key views easy to reach: realtime, history, service, daily, weekly, journal?
- Are critical states visually obvious: disconnected, stale data, degraded API, empty feed, no fills, risk alert?
- Is the fallback between websocket stream and `/api/v1/state` refresh understandable and trustworthy?
- Are data timestamps, freshness labels, and instance labels consistently shown?

### Interaction quality
- Keyboard shortcuts: discoverable, conflict-free, and safe?
- Filters, tabs, tables, and inspectors: do they preserve context or reset unexpectedly?
- Paused feeds, selected rows, and focused panels: do they survive refresh/reconnect correctly?
- Mobile responsiveness is optional unless explicitly required; desktop operator ergonomics are mandatory.

### Visual consistency
- Repeated panel patterns: spacing, headings, empty states, loading states, error states
- Color usage: does any status rely on color alone?
- Are density and information hierarchy appropriate for a live trading dashboard?

---

## PHASE 3 — Frontend runtime reliability audit

### Data transport and state integrity
- `useRealtimeTransport`: reconnect backoff bounded and observable?
- Are duplicate websocket events deduplicated where required?
- Can stale API responses overwrite fresher realtime state?
- Are malformed payloads rejected safely with useful diagnostics?
- Are loading, degraded, disconnected, and recovered states represented explicitly in UI state?

### Failure handling
- Any uncaught promise rejections?
- Any component crash risks from nullable or partially loaded data?
- Any infinite render loops or effect dependency bugs?
- Do tables/charts fail gracefully when upstream payload shape changes?
- Is there a clear operator-visible signal when the API is unavailable?

### Compatibility and deployment
- Docker build and nginx serving path correct?
- Asset paths and SPA refresh routing correct behind nginx?
- Are environment-dependent URLs configurable without editing source?

---

## PHASE 4 — Performance audit

### Render performance
- Largest/most frequently rerendering panels and why
- Expensive derived computations in render vs memoized selectors
- Oversized React state causing broad rerenders
- Table rendering cost at realistic fill/order/event volumes
- Chart update cost under live data flow

### Network and loading
- Initial bundle size and slowest chunk
- Any unused code that should be lazy-loaded?
- Are polling intervals or reconnect loops too aggressive?
- Is API payload size larger than needed for current panels?

### Browser health
- Long tasks > 50 ms
- Memory growth while keeping the dashboard open for hours
- Event listeners / subscriptions not cleaned up on unmount
- Auto-scroll, feed buffering, and inspector payload history bounded?

---

## PHASE 5 — Code health audit

### Structure
- Files above 400 lines with mixed responsibilities
- Components doing transport/state/domain formatting all at once
- Repeated presentation logic across panels
- Hooks with hidden side effects or poor dependency boundaries

### Type safety
- Use of `any`, unsafe casts, optional chaining hiding invalid states
- Zod schemas missing where external payloads enter the app
- Drift between API payload shape and frontend types
- Formatting helpers returning ambiguous types or mixed units

### Maintainability
- Inline magic numbers for colors, thresholds, dimensions, retry delays
- CSS duplication across panels
- Accessibility labels missing on controls
- Testability risks: logic embedded only in JSX or effects

---

## PHASE 6 — Dependency and tooling review

For each outdated or candidate dependency, make a decision:

| Package | Current | Latest | Risk / opportunity | Decision |
|---|---|---|---|---|
| | | | | adopt / update / defer / reject / remove |

### Mandatory dependency checks
- Security advisories or CVEs affecting runtime or build chain
- Major version opportunities: React, Vite, TypeScript, ESLint ecosystem
- Lockfile drift or inconsistent install behavior
- Packages that overlap in responsibility and should be consolidated
- Packages imported but unused or replaceable with native platform APIs

### Candidate tooling to evaluate
- `vitest` + React Testing Library for UI regression coverage
- `playwright` for operator workflow smoke tests
- `@tanstack/react-virtual` if large tables become a bottleneck
- Bundle analyzer tooling if chunk growth is uncontrolled
- Error boundary / telemetry integration if runtime failures are still opaque

For each: estimate migration effort, breakage risk, and expected benefit.

---

## PHASE 7 — Testing and release readiness

### Minimum checks
- `npm run lint`
- `npm run build`
- TypeScript project references build cleanly
- No console errors on first load for the primary operator path

### Test coverage gaps
- Realtime reconnect and fallback refresh behavior
- Panel rendering on partial/malformed payloads
- Store updates preserving selection and pause state
- Critical operator journeys: open app, inspect fills, verify service health, recover after disconnect
- Nginx/Docker smoke path for production-like deployment

### Release blockers
- Any issue that hides stale/disconnected state is P0
- Any issue that shows wrong PnL/order/position values is P0
- Any dependency vulnerability with plausible exploit path in shipped assets or build pipeline is at least P1 until triaged

---

## PHASE 8 — Sprint plan (1–2 week scope)

Select a coherent bundle:
- Max 1 L-effort item (> 1 day)
- 2–3 M-effort items (half-day to 1 day each)
- Quick wins (< 2h each, unlimited)

For each L/M item: define rollback plan.
Order items by: operator safety first, then correctness, then performance, then maintainability.

---

## PHASE 9 — BACKLOG entries (mandatory)

For every item in the sprint plan:

```markdown
### [P{tier}-FRONT-YYYYMMDD-N] {title} `open`

**Why it matters**: {operator safety / correctness / performance / maintainability impact}

**What exists now**:
- {file or flow} — {current behavior}

**Design decision (pre-answered)**: {chosen approach}

**Implementation steps**:
1. {exact change}
2. {exact change}

**Acceptance criteria**:
- {testable: build passes / issue reproduced then fixed / metric improves}

**Do not**:
- {constraint}
```

---

## Output format
1. Frontend health scorecard (6 dimensions, score + trend arrow ↑↓→)
2. Product/UX findings (ranked by operator impact)
3. Reliability findings (transport, state integrity, failure handling)
4. Performance findings (render, network, memory)
5. Code health findings (structure, types, maintainability)
6. Dependency decisions table
7. Testing gaps and release blockers
8. Sprint plan (1–2 week, ordered, with rollback)
9. BACKLOG entries (copy-paste ready)
10. Metrics to track next cycle (what proves the fixes worked)
11. Assumptions and data gaps (what was inferred vs explicitly provided)

## Rules
- Never trade polish for correctness on operator-critical panels
- A stale/disconnected-state visibility bug is always high priority
- Do not upgrade dependencies just because newer versions exist; require bounded migration and clear benefit
- Prefer boring, incremental fixes over broad UI rewrites
- Every sprint item must have a verification path: test, build artifact, or measurable UX/perf outcome
- If a dependency update increases build/runtime risk close to release, defer unless it fixes a real defect or security issue
- Include at least one bounded UX improvement proposal per cycle with explicit validation criteria
```
