## ADDED Requirements

### Requirement: Research view registered in navigation

The dashboard SHALL include a `"research"` view accessible from the sidebar, top bar, and keyboard shortcuts. The sidebar SHALL display a "Research" button in the "Dashboard" group. The top bar SHALL include "Research" in the view selector. The keyboard shortcut system SHALL include `"research"` in the view cycling order.

#### Scenario: Navigate to research via sidebar
- **WHEN** the user clicks the "Research" button in the sidebar
- **THEN** the `activeView` changes to `"research"` and the `ResearchPage` component renders

#### Scenario: Navigate to research via keyboard
- **WHEN** the user presses the keyboard shortcut assigned to "Research"
- **THEN** the `activeView` changes to `"research"`

#### Scenario: View persists across sessions
- **WHEN** the user is on the "Research" view and refreshes the page
- **THEN** the dashboard restores the `"research"` view from local storage

---

### Requirement: Scoreboard sub-view

The `ResearchPage` SHALL display a scoreboard as its default sub-view. The scoreboard SHALL show a table of all candidates with columns: Name, Adapter, Lifecycle State, Best Score (formatted 0-100), Recommendation, and Experiment Count. Rows SHALL be clickable to navigate to candidate detail. The scoreboard SHALL auto-refresh every 30 seconds.

#### Scenario: Candidates loaded
- **WHEN** the research page mounts
- **THEN** the scoreboard fetches `GET /api/research/candidates` and displays all candidates in a table sorted by best score descending

#### Scenario: Empty state
- **WHEN** no candidates exist
- **THEN** the scoreboard displays a message: "No strategy candidates found. Run the research pipeline to generate candidates."

#### Scenario: Auto-refresh
- **WHEN** 30 seconds have elapsed since the last fetch
- **THEN** the scoreboard re-fetches the candidate list without user interaction

#### Scenario: Lifecycle state badge
- **WHEN** a candidate has a lifecycle state
- **THEN** the state is displayed as a colored badge: `candidate` (blue), `revise` (amber), `paper` (green), `rejected` (red), `promoted` (purple)

---

### Requirement: Candidate detail sub-view

When a user selects a candidate from the scoreboard, the `ResearchPage` SHALL display a detail sub-view. The detail view SHALL include: the candidate's hypothesis, entry/exit logic, parameter space, a score breakdown visualisation, lifecycle transition timeline, experiment history table, and an inline Markdown report viewer.

#### Scenario: View candidate detail
- **WHEN** the user clicks a candidate row in the scoreboard
- **THEN** the page fetches `GET /api/research/candidates/{name}` and displays the detail view with a back button to return to the scoreboard

#### Scenario: Score breakdown display
- **WHEN** the candidate has a score breakdown
- **THEN** the detail view renders a horizontal bar chart showing each component's normalised score (0-1) with the component name as label

#### Scenario: Experiment history
- **WHEN** the candidate has experiment records
- **THEN** the detail view shows a table with columns: Run ID (truncated), Timestamp, Score, Recommendation, and a "View Report" link

#### Scenario: View report inline
- **WHEN** the user clicks "View Report" for an experiment
- **THEN** the page fetches `GET /api/research/reports/{name}/{run_id}` and renders the Markdown report in a panel below the experiment table

---

### Requirement: Exploration monitor sub-view

The `ResearchPage` SHALL include an exploration monitor sub-view accessible via a tab or toggle. The monitor SHALL list all exploration sessions and allow selecting one for live log streaming.

#### Scenario: List sessions
- **WHEN** the user switches to the exploration monitor tab
- **THEN** the page fetches `GET /api/research/explorations` and displays sessions with columns: Session ID (truncated), Status, Iterations, Best Score, Best Candidate, Created At

#### Scenario: Live exploration streaming
- **WHEN** the user selects a running session
- **THEN** the page connects to `GET /api/research/explorations/{session_id}/log` via EventSource and displays iteration events in a live log panel (candidate name, score, recommendation per iteration)

#### Scenario: Completed session review
- **WHEN** the user selects a completed session
- **THEN** the page fetches `GET /api/research/explorations/{session_id}` and displays the final session result (best score, best candidate, total iterations, token usage)

#### Scenario: SSE done event
- **WHEN** the SSE stream emits a `done` event
- **THEN** the log panel stops appending, displays the final summary, and the session status updates to "completed"

---

### Requirement: Error handling

The `ResearchPage` SHALL handle API errors gracefully. Network errors, 404s, and 500s SHALL be displayed as dismissible error banners within the page, not as unhandled exceptions.

#### Scenario: API endpoint unreachable
- **WHEN** a fetch to any `/api/research/*` endpoint fails with a network error
- **THEN** the page displays an error banner: "Failed to load research data. Check API connection."

#### Scenario: Candidate not found
- **WHEN** the detail view receives a 404 for a candidate
- **THEN** the page returns to the scoreboard and shows a warning: "Candidate no longer exists."

---

### Requirement: Lazy loading

The `ResearchPage` component SHALL be lazy-loaded via `React.lazy()` and wrapped in `Suspense` with a loading fallback, following the same pattern as `BacktestPage`.

#### Scenario: First navigation to research
- **WHEN** the user navigates to the "Research" view for the first time
- **THEN** a loading indicator is shown while the component bundle loads, then the research page renders
