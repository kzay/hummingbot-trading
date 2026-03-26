## ADDED Requirements

### Requirement: Operational paper promotion

The system SHALL treat paper promotion as an operational workflow, not only as a lifecycle label.

A paper-eligible candidate SHALL produce a deployable paper artifact containing at minimum:

- candidate identifier
- experiment run identifier
- pinned parameters
- expected operating regime or market conditions
- risk budget
- expected backtest bands for fills, slippage, trade count, and PnL

#### Scenario: Candidate qualifies for auto-paper

- **WHEN** a candidate passes all hard gates
- **AND** replay-grade validation exists
- **AND** the composite score is at least `0.65`
- **THEN** the system generates a paper artifact
- **AND** the candidate becomes eligible for automatic paper promotion

#### Scenario: Candle-only candidate cannot auto-paper

- **WHEN** a candidate has only candle-harness validation
- **THEN** the system SHALL not auto-promote it to paper

### Requirement: Research-owned paper run records

The system SHALL track paper runs as research-owned artifacts keyed by candidate and experiment run.

#### Scenario: Paper run starts

- **WHEN** a promoted candidate is launched in paper mode
- **THEN** the system records a paper run identifier linked to the exact validated candidate and experiment manifest

### Requirement: Paper-vs-backtest divergence monitoring

The system SHALL compare paper behavior to validated backtest expectations and support downgrade or rejection when divergence breaches configured bands.

Phase-one divergence monitoring SHALL cover:

- entry timing differences
- fill quality
- slippage divergence
- trade frequency divergence
- realized PnL divergence
- regime mismatch
- operational failures

#### Scenario: Divergence breaches threshold

- **WHEN** paper behavior breaches configured divergence bands
- **THEN** the system downgrades or rejects the candidate
- **AND** the recorded reason names the breached paper-validation dimension

### Requirement: Manual live promotion boundary

The system SHALL stop automatic workflow decisions at research retention, rejection, or paper-validation outcomes.

#### Scenario: Candidate completes paper validation

- **WHEN** a candidate survives paper validation
- **THEN** the system may mark it ready for human review
- **BUT** it SHALL not automatically promote the candidate to live trading
