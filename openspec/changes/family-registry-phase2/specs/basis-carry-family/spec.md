## ADDED Requirements

### Requirement: basis_carry family is registered
The system SHALL register a `basis_carry` strategy family in `FAMILY_REGISTRY` with `required_data: ["funding", "spot"]`, `supported_adapters: ["ta_composite", "directional_mm", "atr_mm"]`, `default_complexity_budget: 4`, `per_trade_risk_min_pct: 0.15`, and `per_trade_risk_max_pct: 0.50`.

#### Scenario: Family lookup succeeds
- **WHEN** `get_family("basis_carry")` is called
- **THEN** a `StrategyFamily` instance is returned with `name == "basis_carry"`

#### Scenario: Family appears in SUPPORTED_FAMILIES
- **WHEN** `is_supported_family("basis_carry")` is called
- **THEN** the result is `True`

### Requirement: basis_carry parameter bounds are enforced
The family SHALL define `ParameterBounds` for: `funding_zscore_window` [4, 48], `carry_threshold` [0.01, 0.10], `basis_spread_threshold` [0.001, 0.02], `hold_bars` [8, 96], `stop_atr` [0.3, 2.0], `delta_exposure` [0.0, 0.25].

#### Scenario: Valid search space passes bounds check
- **WHEN** `check_bounds({"funding_zscore_window": [8, 16], "hold_bars": [16, 32]})` is called on the `basis_carry` family
- **THEN** an empty violations list is returned

#### Scenario: Out-of-range carry_threshold is rejected
- **WHEN** `check_bounds({"carry_threshold": [0.15]})` is called on the `basis_carry` family
- **THEN** a non-empty violations list is returned containing a message about `carry_threshold`

#### Scenario: Delta exposure above cap is rejected
- **WHEN** `check_bounds({"delta_exposure": [0.50]})` is called on the `basis_carry` family
- **THEN** a non-empty violations list is returned containing a message about `delta_exposure`

### Requirement: basis_carry has three templates
The family SHALL define templates: `basis_carry_neutral` (pure delta-neutral funding collection), `basis_carry_convergence` (basis mean-reversion with funding kicker), `basis_carry_regime_gated` (carry only when regime is range-bound).

#### Scenario: Neutral template is retrievable
- **WHEN** `get_template("basis_carry_neutral")` is called on the `basis_carry` family
- **THEN** a `FamilyTemplate` instance is returned with `template_id == "basis_carry_neutral"`

#### Scenario: Convergence template is retrievable
- **WHEN** `get_template("basis_carry_convergence")` is called on the `basis_carry` family
- **THEN** a `FamilyTemplate` instance is returned

#### Scenario: Regime-gated template is retrievable
- **WHEN** `get_template("basis_carry_regime_gated")` is called on the `basis_carry` family
- **THEN** a `FamilyTemplate` instance is returned

### Requirement: basis_carry required data is enforced by validator
The `candidate_validator` SHALL raise `CandidateValidationError` when a candidate declares `strategy_family: basis_carry` but does not declare `funding` and `spot` in its `required_data` list.

#### Scenario: Missing funding data raises error
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="basis_carry"` and `required_data=["spot"]`
- **THEN** `CandidateValidationError` is raised with a message referencing `funding`

#### Scenario: Both required data sources present passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="basis_carry"` and `required_data=["funding", "spot"]`
- **THEN** no `CandidateValidationError` is raised for the data requirement
