## MODIFIED Requirements

### Requirement: Unified research storage root

The research API SHALL default to the same research storage root used by the controllers: `hbot/data/research`.

#### Scenario: API uses default research root

- **WHEN** no explicit research root override is provided
- **THEN** the API reads candidates, lifecycle state, experiments, reports, and explorations from `hbot/data/research`

### Requirement: Rich candidate summaries

The candidate list and detail surfaces SHALL expose the richer governance metadata needed for desk review.

Candidate list entries SHALL include, when available:

- `strategy_family`
- `validation_tier`
- `best_score`
- `best_recommendation`
- `paper_status`
- `experiment_count`

Candidate detail responses SHALL include, when available:

- `gate_results`
- `score_breakdown`
- `stress_results`
- `artifact_paths`
- `paper_run_id`
- `paper_vs_backtest`

#### Scenario: Candidate detail is requested

- **WHEN** the API returns detail for a governed candidate
- **THEN** the response includes the richer manifest- and lifecycle-derived governance fields alongside legacy fields

### Requirement: Canonical candidate registry visibility

The research API SHALL treat the central candidate registry as the authoritative candidate universe, including candidates created by exploration sessions.

#### Scenario: Exploration emits candidate

- **WHEN** the exploration workflow generates a candidate artifact
- **THEN** the canonical candidate registry receives a copy
- **AND** the API can list and fetch that candidate without depending on the session-local directory alone

### Requirement: Ranked leaderboard view

The API SHALL support a read-only ranked candidate view for research review.

#### Scenario: Ranked candidates are requested

- **WHEN** the client requests ranked research output
- **THEN** the API returns candidates ordered by the governed ranking methodology
- **AND** the response distinguishes research-only candidates from replay-validated and paper-active candidates
