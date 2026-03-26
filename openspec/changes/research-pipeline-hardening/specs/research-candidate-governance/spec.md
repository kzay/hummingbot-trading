## ADDED Requirements

### Requirement: Governed research candidate contract

The system SHALL support a governed research candidate contract that extends the legacy strategy-candidate YAML with additive metadata required for production research governance.

The governed contract SHALL support these fields in addition to the legacy schema:

- `schema_version`
- `strategy_family`
- `template_id`
- `search_space`
- `constraints`
- `required_data`
- `market_conditions`
- `expected_trade_frequency`
- `evaluation_rules`
- `promotion_policy`
- `complexity_budget`

The system SHALL preserve backward compatibility with legacy candidate YAML files that only define the original strategy-candidate fields.

#### Scenario: Legacy candidate loads successfully

- **WHEN** a candidate YAML contains only the legacy research fields
- **THEN** the loader returns a valid candidate object
- **AND** it marks the candidate as `schema_version: 1`
- **AND** it derives the effective governed fields from legacy defaults where possible

#### Scenario: Governed candidate loads successfully

- **WHEN** a candidate YAML includes the governed fields
- **THEN** the loader preserves those values without discarding legacy compatibility fields

### Requirement: Effective search space normalization

The system SHALL normalize legacy `parameter_space` and governed `search_space` into one effective search definition before evaluation.

#### Scenario: Only legacy parameter_space exists

- **WHEN** a candidate defines `parameter_space` but omits `search_space`
- **THEN** the system treats `parameter_space` as the effective search definition

#### Scenario: Governed search_space exists

- **WHEN** a candidate defines `search_space`
- **THEN** the system uses it as the effective search definition
- **AND** any serialized compatibility view remains able to expose a legacy `parameter_space`

### Requirement: Candidate validation before any backtest

The system SHALL reject invalid candidates before starting verification backtests.

Validation SHALL include at minimum:

- `adapter_mode` and `base_config.strategy_class` compatibility
- supported strategy family
- required-data availability
- invalid parameter combinations
- position-risk and complexity-budget checks

#### Scenario: Adapter mismatch is rejected

- **WHEN** `adapter_mode` and `base_config.strategy_class` do not refer to the same executable adapter path
- **THEN** candidate evaluation fails before any backtest is started
- **AND** the rejection reason names the mismatch

#### Scenario: Missing required funding data is rejected

- **WHEN** a candidate declares `required_data` including funding inputs and the selected dataset is unavailable
- **THEN** candidate evaluation fails before any backtest is started
- **AND** the rejection reason states that funding data is missing

#### Scenario: Invalid combination is rejected

- **WHEN** a candidate defines an impossible combination such as target less than stop, reversed window ordering, or per-trade risk above the family budget
- **THEN** candidate evaluation fails before any backtest is started
- **AND** the rejection reason identifies the invalid combination
