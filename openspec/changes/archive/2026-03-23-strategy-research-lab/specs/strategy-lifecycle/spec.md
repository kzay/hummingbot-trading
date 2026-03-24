## ADDED Requirements

### Requirement: Promotion gates

The system SHALL enforce configurable promotion gates before a candidate can transition from `paper` to `promoted`. Default gates: (1) robustness score >= 0.55, (2) minimum 3 OOS walk-forward windows passed, (3) fee stress test completed with all multipliers producing Sharpe > 0, (4) at least one experiment with `latency_aware` fill model.

#### Scenario: All gates pass
- **WHEN** a candidate has robustness score 0.7, 5 OOS windows, fee stress all positive, and latency_aware run exists
- **THEN** `LifecycleManager.can_promote(candidate_name)` returns `True`

#### Scenario: Insufficient OOS windows
- **WHEN** a candidate has only 2 OOS windows
- **THEN** `can_promote()` returns `False` with reason "minimum 3 OOS windows required, has 2"

### Requirement: Lifecycle transitions

The system SHALL track lifecycle state in `hbot/data/research/lifecycle/{candidate_name}.json` containing `current_state`, `history` (list of `{from, to, timestamp, reason}`), and `gate_results` (dict of gate name to pass/fail).

#### Scenario: Transition recorded
- **WHEN** `LifecycleManager.transition(candidate, "candidate", "paper", reason="score 0.62")` is called
- **THEN** the lifecycle JSON is updated with the new state and history entry

#### Scenario: Invalid transition rejected
- **WHEN** a transition from `rejected` to `promoted` is attempted
- **THEN** a `ValueError` is raised

### Requirement: CLI evaluation

The system SHALL provide `python -m controllers.research.evaluate --candidate path/to/candidate.yml` that loads the candidate, runs the evaluation pipeline, prints a summary with robustness score and recommendation, and updates the lifecycle state.

#### Scenario: CLI full run
- **WHEN** `python -m controllers.research.evaluate --candidate candidate.yml` is executed
- **THEN** stdout shows the robustness score, component breakdown, and lifecycle recommendation

#### Scenario: CLI dry-run
- **WHEN** `--dry-run` flag is passed
- **THEN** the candidate is validated and the pipeline is described but not executed
