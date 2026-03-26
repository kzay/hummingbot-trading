## ADDED Requirements

### Requirement: Staged validation tiers

The system SHALL validate candidates in stages rather than relying on a single backtest mode.

The validation stages SHALL be:

1. fast verification on the candle harness
2. replay-grade validation for candidates that pass first-pass quality gates and have the required replay inputs

#### Scenario: Replay validation runs when eligible

- **WHEN** a candidate passes verification and the required replay datasets are available
- **THEN** the system runs replay-grade validation before paper eligibility is considered

#### Scenario: Candle-only survivor remains research-only

- **WHEN** a candidate passes candle-harness validation but replay validation cannot run because required replay inputs are missing
- **THEN** the system may retain the candidate as a research artifact
- **BUT** it SHALL mark the candidate ineligible for automatic paper promotion

### Requirement: Hard reject gates before ranking

The system SHALL enforce hard reject gates before applying composite ranking.

Default hard gates SHALL include:

- positive net PnL after fees
- max drawdown `<= 20%`
- profit factor `>= 1.15`
- mean OOS Sharpe `>= 0.5`
- OOS degradation ratio `>= 0.6`
- deflated Sharpe `> 0`
- minimum trade count by expected trade frequency:
  - low frequency `>= 20`
  - medium frequency `>= 40`
  - high frequency `>= 80`

#### Scenario: Candidate fails hard gate

- **WHEN** a candidate fails any hard gate
- **THEN** the system rejects the candidate before composite ranking is used for promotion decisions

### Requirement: Overfitting defenses are explicit

The system SHALL compute and persist explicit overfitting defenses in addition to a final score.

Phase-one defenses SHALL include:

- no single month contributes more than `50%` of total PnL
- no single trade contributes more than `15%` of total PnL
- neighboring parameter settings retain at least `80%` of the center candidate's median robust score
- candidates with more than `6` tunable parameters incur a simplicity penalty

#### Scenario: Concentrated PnL is flagged

- **WHEN** a candidate derives more than half of total PnL from a single month
- **THEN** the system flags the candidate as fragile
- **AND** the fragility signal is persisted in evaluation artifacts

#### Scenario: Excessive complexity is penalized

- **WHEN** a candidate defines more than `6` tunable parameters
- **THEN** the composite ranking applies a simplicity penalty

### Requirement: Rich experiment manifests

The system SHALL persist desk-grade experiment manifests for every evaluation run.

Each manifest SHALL include at minimum:

- `recommendation`
- `score_breakdown`
- `gate_results`
- `validation_tier`
- `stress_results`
- `artifact_paths`
- `paper_run_id`
- `paper_status`
- `paper_vs_backtest`
- reproducibility metadata

#### Scenario: Evaluation run is recorded

- **WHEN** a candidate evaluation completes
- **THEN** the recorded manifest includes the richer governance fields needed by operators and API consumers
