## ADDED Requirements

### Requirement: relative_value family is registered
The system SHALL register a `relative_value` strategy family in `FAMILY_REGISTRY` with `required_data: ["multi_asset"]`, `supported_adapters: ["ta_composite", "simple", "atr_mm"]`, `default_complexity_budget: 5`, `per_trade_risk_min_pct: 0.15`, and `per_trade_risk_max_pct: 0.75`.

#### Scenario: Family lookup succeeds
- **WHEN** `get_family("relative_value")` is called
- **THEN** a `StrategyFamily` instance is returned with `name == "relative_value"`

#### Scenario: Family appears in SUPPORTED_FAMILIES
- **WHEN** `is_supported_family("relative_value")` is called
- **THEN** the result is `True`

### Requirement: relative_value parameter bounds are enforced
The family SHALL define `ParameterBounds` for: `spread_window` [10, 100], `zscore_threshold` [1.0, 3.0], `hedge_ratio` [0.5, 2.0], `hold_bars` [2, 48], `stop_atr` [0.5, 3.0].

#### Scenario: Valid hedge_ratio passes bounds check
- **WHEN** `check_bounds({"hedge_ratio": [0.8, 1.0, 1.2]})` is called on the `relative_value` family
- **THEN** an empty violations list is returned

#### Scenario: hedge_ratio below minimum is rejected
- **WHEN** `check_bounds({"hedge_ratio": [0.2]})` is called on the `relative_value` family
- **THEN** a non-empty violations list is returned containing a message about `hedge_ratio`

#### Scenario: hedge_ratio above maximum is rejected
- **WHEN** `check_bounds({"hedge_ratio": [2.5]})` is called on the `relative_value` family
- **THEN** a non-empty violations list is returned containing a message about `hedge_ratio`

#### Scenario: zscore_threshold below minimum is rejected
- **WHEN** `check_bounds({"zscore_threshold": [0.5]})` is called on the `relative_value` family
- **THEN** a non-empty violations list is returned

### Requirement: relative_value invalid combinations are enforced
The family SHALL define invalid-combination rules: `zscore_threshold < 1.0` (no edge, too close to mean) and `hold_bars < 2` (spread latency risk).

#### Scenario: Invalid combination rules are present
- **WHEN** the `relative_value` family definition is inspected
- **THEN** `invalid_combinations` contains at least two entries referencing `zscore_threshold` and `hold_bars`

### Requirement: relative_value has three templates
The family SHALL define templates: `relative_value_ratio` (ratio z-score mean-reversion on correlated pair), `relative_value_cross_venue` (cross-exchange basis capture), `relative_value_spot_perp` (spot vs perp basis excluding funding yield).

#### Scenario: Ratio template is retrievable
- **WHEN** `get_template("relative_value_ratio")` is called on the `relative_value` family
- **THEN** a `FamilyTemplate` instance is returned with `template_id == "relative_value_ratio"`

#### Scenario: Cross-venue template is retrievable
- **WHEN** `get_template("relative_value_cross_venue")` is called on the `relative_value` family
- **THEN** a `FamilyTemplate` instance is returned

#### Scenario: Spot/perp template is retrievable
- **WHEN** `get_template("relative_value_spot_perp")` is called on the `relative_value` family
- **THEN** a `FamilyTemplate` instance is returned

### Requirement: relative_value required data is enforced by validator
The `candidate_validator` SHALL raise `CandidateValidationError` when a candidate declares `strategy_family: relative_value` but does not declare `multi_asset` in its `required_data` list.

#### Scenario: Missing multi_asset data raises error
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="relative_value"` and `required_data=[]`
- **THEN** `CandidateValidationError` is raised with a message referencing `multi_asset`

#### Scenario: multi_asset declared passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="relative_value"` and `required_data=["multi_asset"]`
- **THEN** no `CandidateValidationError` is raised for the data requirement
