## ADDED Requirements

### Requirement: Template-first strategy discovery

The system SHALL support template-first strategy discovery for governed research candidates.

Phase-one supported families SHALL be:

- `trend_continuation`
- `trend_pullback`
- `compression_breakout`
- `mean_reversion`
- `regime_conditioned_momentum`
- `funding_dislocation`

Each generated candidate SHALL declare both `strategy_family` and `template_id`.

#### Scenario: Exploration emits template-backed candidate

- **WHEN** the exploration workflow generates a new backtestable candidate
- **THEN** the candidate includes a supported `strategy_family`
- **AND** the candidate includes a concrete `template_id`
- **AND** the candidate conforms to the governed candidate contract

### Requirement: Bounded family search contracts

The system SHALL define bounded parameter contracts for each supported family and SHALL reject unconstrained or nonsensical search spaces.

Phase-one defaults SHALL bound at least:

- trend windows to `20-200` bars
- volatility windows to `10-50` bars
- retrace depth to `0.25-1.5` ATR
- breakout lookbacks to `12-96` bars
- band and z-score thresholds to `1.0-3.0`
- stop and target multiples to `0.5-4.0` ATR
- cooldown and holding windows to `1-48` bars
- per-trade risk to `0.25%-1.0%` of equity

#### Scenario: Invalid bounded search is rejected

- **WHEN** a candidate search space exceeds family bounds or encodes an impossible ordering such as a fast window greater than a slow window
- **THEN** the candidate is rejected before backtest

### Requirement: Data-aware derivatives family support

The system SHALL allow derivatives-aware discovery only when the required data architecture supports it.

#### Scenario: Funding dislocation is allowed with funding data

- **WHEN** a funding-dislocation candidate declares funding data and the selected dataset includes funding history
- **THEN** the candidate may proceed to evaluation

#### Scenario: Open-interest or liquidation family is not first-class in phase one

- **WHEN** discovery attempts to generate an open-interest or liquidation-driven family without dedicated first-class research inputs
- **THEN** the system SHALL not treat it as a supported phase-one family
- **AND** it SHALL require explicit future capability work before it becomes a standard discovery template
