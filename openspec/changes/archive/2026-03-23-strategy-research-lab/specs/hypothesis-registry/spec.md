## ADDED Requirements

### Requirement: Experiment manifest creation

The system SHALL create an immutable experiment manifest for every evaluation run. The manifest SHALL include: `run_id` (UUID), `candidate_name`, `timestamp_utc`, `config_hash` (SHA-256 of the serialised backtest config), `git_sha` (current HEAD, or "dirty" if uncommitted changes), `data_window` (start/end dates), `seed`, `fill_model`, `result_path` (relative path to the JSON result file), and `robustness_score` (float or null if not yet scored).

#### Scenario: Manifest written on evaluation
- **WHEN** the experiment orchestrator completes an evaluation run
- **THEN** a manifest line is appended to `hbot/data/research/experiments/{candidate_name}.jsonl`

#### Scenario: Manifest immutability
- **WHEN** a manifest line has been written
- **THEN** it SHALL NOT be modified or deleted by the system (append-only)

### Requirement: Registry query

The system SHALL provide `HypothesisRegistry.list_experiments(candidate_name, filters=None)` returning a list of manifest dicts, optionally filtered by date range, minimum robustness score, or fill model.

#### Scenario: List all experiments for a candidate
- **WHEN** `list_experiments("my-strategy")` is called with no filters
- **THEN** all manifest entries for "my-strategy" are returned in chronological order

#### Scenario: Filter by minimum score
- **WHEN** `list_experiments("my-strategy", filters={"min_score": 0.5})` is called
- **THEN** only entries with `robustness_score >= 0.5` are returned

### Requirement: Git SHA capture

The system SHALL capture the git SHA via `subprocess.run(["git", "rev-parse", "HEAD"])`. If the working tree has uncommitted changes, the SHA SHALL be suffixed with `-dirty`.

#### Scenario: Clean repo
- **WHEN** the git working tree is clean
- **THEN** `git_sha` is a 40-character hex string

#### Scenario: Dirty repo
- **WHEN** the git working tree has uncommitted changes
- **THEN** `git_sha` ends with `-dirty`
