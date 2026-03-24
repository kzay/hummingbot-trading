## ADDED Requirements

### Requirement: Dedicated backtest page in navigation
The realtime dashboard SHALL provide a dedicated route labeled for backtesting, reachable from primary navigation (TopBar tab or equivalent), visually consistent with existing views (dark theme, typography, spacing, `Panel` component).

#### Scenario: User opens backtest page
- **WHEN** the operator navigates to the backtest route
- **THEN** the page SHALL render without errors and SHALL show the run panel, log panel, results area, and job history table

#### Scenario: Keyboard shortcut
- **WHEN** a keyboard shortcut is assigned (e.g. `7`)
- **THEN** pressing it SHALL navigate to the backtest view, consistent with other view shortcuts

### Requirement: Preset selection with safe overrides
The page SHALL display a dropdown of available presets fetched from `GET /presets`. Below the dropdown, the page SHALL show optional override fields for `initial_equity` (numeric input), `start_date`, and `end_date` (date inputs). These fields SHALL be pre-populated with the preset's defaults when a preset is selected.

#### Scenario: Presets load on mount
- **WHEN** the page mounts
- **THEN** it SHALL fetch presets from the API and populate the dropdown; if the fetch fails, it SHALL show an error state in the dropdown area

#### Scenario: Override fields pre-fill from preset
- **WHEN** the user selects a preset
- **THEN** `initial_equity`, `start_date`, and `end_date` fields SHALL populate with the preset's default values, editable by the operator

#### Scenario: Empty override uses preset default
- **WHEN** the user clears an override field and submits
- **THEN** the request SHALL omit that override, and the server SHALL use the preset's original value

### Requirement: Run and cancel controls
The page SHALL provide a **Run** button that starts a job and a **Cancel** button visible while a job is running. The Run button SHALL be disabled while a job is in progress. Clicking Cancel SHALL call the cancel endpoint and update the UI to reflect cancellation.

#### Scenario: Start a run
- **WHEN** the user selects a preset and clicks Run
- **THEN** the client SHALL POST to the jobs endpoint with `preset_id` and any non-empty overrides, display the returned `job_id`, and begin polling status / opening SSE log stream

#### Scenario: Cancel a running job
- **WHEN** the user clicks Cancel while a job is running
- **THEN** the client SHALL POST to the cancel endpoint, disable the Cancel button, and update status to `cancelled` once confirmed

#### Scenario: Duplicate submit prevention
- **WHEN** a job is already running
- **THEN** the Run button SHALL be disabled with a visual indicator (e.g. grayed out with tooltip)

### Requirement: Determinate progress bar
The page SHALL display a progress bar driven by the `progress_pct` field from the status API. The bar SHALL show 0–100% with numeric label. Before the first status response, the bar SHALL show an indeterminate state.

#### Scenario: Progress updates
- **WHEN** the status response includes `progress_pct: 45`
- **THEN** the progress bar SHALL fill to 45% and display "45%"

#### Scenario: Completion
- **WHEN** the job status becomes `completed`
- **THEN** the progress bar SHALL show 100% and transition to a success color

#### Scenario: Failure
- **WHEN** the job status becomes `failed` or `timed_out`
- **THEN** the progress bar SHALL stop and transition to an error color

### Requirement: SSE log panel
The page SHALL display a scrollable log area fed by an SSE connection to the log endpoint. New lines SHALL append at the bottom. The panel SHALL auto-scroll to the bottom unless the user has manually scrolled up (scroll lock). After the job reaches a terminal state, the log SHALL remain visible and scrollable.

#### Scenario: Logs stream during run
- **WHEN** the SSE stream emits new log lines
- **THEN** the log panel SHALL append them and auto-scroll if scroll lock is not engaged

#### Scenario: User scrolls up
- **WHEN** the user scrolls up in the log panel
- **THEN** auto-scroll SHALL pause; a "Jump to bottom" indicator SHALL appear

#### Scenario: SSE connection fails
- **WHEN** the SSE connection drops
- **THEN** `EventSource` SHALL auto-reconnect; the panel SHALL show a brief reconnecting indicator

#### Scenario: Terminal state
- **WHEN** the job finishes
- **THEN** the SSE stream SHALL close and the full log SHALL remain visible

### Requirement: Visual results panel
On successful completion, the page SHALL display results in two sections: a **metric cards row** and an **equity curve chart**.

#### Scenario: Metric cards
- **WHEN** the job status becomes `completed` and result summary is available
- **THEN** the page SHALL render metric cards for: total return (%), Sharpe ratio, Sortino ratio, Calmar ratio, max drawdown (% and duration), fill count, maker fill ratio, fee drag (%), and inventory half-life (min). Each card SHALL show the metric label and formatted value. Values that are NaN or missing SHALL display "—" not "NaN".

#### Scenario: Equity curve chart
- **WHEN** equity curve data is available (from the result or a separate fetch)
- **THEN** the page SHALL render a `lightweight-charts` `LineSeries` chart using the dashboard's dark theme, with time on the x-axis and equity (quote) on the y-axis

#### Scenario: Warnings strip
- **WHEN** the result contains one or more `warnings`
- **THEN** each warning SHALL be displayed as a styled alert badge below the metric cards

#### Scenario: Download buttons
- **WHEN** the result includes report and equity CSV paths
- **THEN** the page SHALL show download buttons or links for each file

#### Scenario: Failed run
- **WHEN** the job status is `failed`
- **THEN** the results panel SHALL NOT render; the error message from the API SHALL be shown instead, and the log panel SHALL remain accessible

### Requirement: Job history table
The page SHALL display a table of past jobs fetched from `GET /jobs`. Each row SHALL show: date, preset name, status (with color-coded badge), and key metrics (return, Sharpe, max DD) for completed runs. Clicking a row SHALL load that job's results and log into the results and log panels.

#### Scenario: History loads on mount
- **WHEN** the backtest page mounts
- **THEN** it SHALL fetch the job list and render the history table

#### Scenario: Click to view past run
- **WHEN** the user clicks a completed job row
- **THEN** the results panel SHALL populate with that job's metrics and equity curve, and the log panel SHALL show that job's log

#### Scenario: Running job in history
- **WHEN** a job is currently running
- **THEN** it SHALL appear at the top of the history table with a "running" badge and its progress percentage

### Requirement: API and auth alignment
The backtest page SHALL use the same `apiBase` and authentication headers (bearer token) as the rest of the dashboard. All backtest API requests SHALL go through the same proxy path.

#### Scenario: Token configured
- **WHEN** the user has set an API token in dashboard settings
- **THEN** all backtest API requests (REST and SSE) SHALL include that token

#### Scenario: API unreachable
- **WHEN** the backtest API returns a network error
- **THEN** the UI SHALL show a clear error state in the affected panel without breaking other dashboard views
