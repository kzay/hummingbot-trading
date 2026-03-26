### Requirement: basis_carry family is registered
The system SHALL register a `basis_carry` strategy family in `FAMILY_REGISTRY` with `required_data: ["funding", "spot"]`, `supported_adapters: ["simple", "atr_mm", "ta_composite"]`, `default_complexity_budget: 4`, `per_trade_risk_min_pct: 0.10`, and `per_trade_risk_max_pct: 0.50`.

#### Scenario: Family lookup succeeds
- **WHEN** `get_family("basis_carry")` is called
- **THEN** a `StrategyFamily` instance is returned with `name == "basis_carry"`

#### Scenario: Family appears in SUPPORTED_FAMILIES
- **WHEN** `is_supported_family("basis_carry")` is called
- **THEN** the result is `True`

### Requirement: basis_carry parameter bounds are enforced
The family SHALL define `ParameterBounds` for: `funding_threshold` [0.0001, 0.01], `basis_threshold` [0.0005, 0.05], `hedge_ratio` [0.80, 1.20], `holding_period` [4, 96], `rebalance_bars` [1, 24].

#### Scenario: Valid search space passes bounds check
- **WHEN** `check_bounds({"funding_threshold": [0.0005, 0.001], "holding_period": [16, 32]})` is called on the `basis_carry` family
- **THEN** an empty violations list is returned

#### Scenario: Out-of-range funding_threshold is rejected
- **WHEN** `check_bounds({"funding_threshold": [0.05]})` is called on the `basis_carry` family
- **THEN** a non-empty violations list is returned

#### Scenario: hedge_ratio outside [0.80, 1.20] is rejected
- **WHEN** `check_bounds({"hedge_ratio": [0.5]})` is called on the `basis_carry` family
- **THEN** a non-empty violations list is returned containing a message about `hedge_ratio`

### Requirement: basis_carry has three templates
The family SHALL define templates: `basis_carry_funding_yield` (delta-neutral funding collection), `basis_carry_delta_neutral_grid` (grid-style carry with rebalancing), `basis_carry_semi_directional` (semi-directional carry with regime tilt).

#### Scenario: Funding yield template is retrievable
- **WHEN** `get_template("basis_carry_funding_yield")` is called on the `basis_carry` family
- **THEN** a `FamilyTemplate` instance is returned with `template_id == "basis_carry_funding_yield"`

#### Scenario: Delta neutral grid template is retrievable
- **WHEN** `get_template("basis_carry_delta_neutral_grid")` is called on the `basis_carry` family
- **THEN** a `FamilyTemplate` instance is returned

#### Scenario: Semi-directional template is retrievable
- **WHEN** `get_template("basis_carry_semi_directional")` is called on the `basis_carry` family
- **THEN** a `FamilyTemplate` instance is returned

### Requirement: basis_carry required data is enforced by validator
The `candidate_validator` SHALL raise `CandidateValidationError` when a candidate declares `strategy_family: basis_carry` but does not declare `funding` and `spot` in its `required_data` list.

#### Scenario: Missing funding data raises error
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="basis_carry"` and `required_data=["spot"]`
- **THEN** `CandidateValidationError` is raised with a message referencing `funding`

#### Scenario: Both required data sources present passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="basis_carry"` and `required_data=["funding", "spot"]`
- **THEN** no `CandidateValidationError` is raised for the data requirement

### Requirement: basis_carry per-trade risk is lower than directional families
The family's `per_trade_risk_max_pct` SHALL be lower than directional trend families to reflect larger notional exposure in carry trades.

#### Scenario: Carry max risk is below trend_continuation max risk
- **WHEN** `get_family("basis_carry").per_trade_risk_max_pct` is compared to `get_family("trend_continuation").per_trade_risk_max_pct`
- **THEN** the carry value is strictly less
