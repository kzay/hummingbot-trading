## MODIFIED Requirements

### Requirement: mean_reversion family enforces regime gate
The `mean_reversion` family definition SHALL include a `regime_window` parameter bound [20, 100] and SHALL add the invalid-combination rule: `no regime filter parameter present (mean reversion without regime gate is prohibited)`. The two existing templates SHALL be renamed to `mean_reversion_zscore_regime_filtered` and `mean_reversion_mm_regime_filtered`, each with `regime_ema` added to `required_params`.

#### Scenario: regime_window bounds are present in family
- **WHEN** the `mean_reversion` family's `parameter_bounds` are inspected
- **THEN** a bound named `regime_window` exists with `min_val=20` and `max_val=100`

#### Scenario: Invalid combination rule references regime gate
- **WHEN** the `mean_reversion` family's `invalid_combinations` list is inspected
- **THEN** at least one entry references "regime" or "regime gate"

#### Scenario: Renamed templates are retrievable
- **WHEN** `get_template("mean_reversion_zscore_regime_filtered")` is called on the `mean_reversion` family
- **THEN** a `FamilyTemplate` instance is returned

#### Scenario: Old template IDs are no longer present
- **WHEN** `get_template("mean_reversion_zscore")` is called on the `mean_reversion` family
- **THEN** `None` is returned

### Requirement: candidate_validator rejects ungated mean_reversion candidates
The `candidate_validator` SHALL raise `CandidateValidationError` with message `"mean_reversion requires a regime filter parameter"` when `strategy_family == "mean_reversion"` and the candidate's `effective_search_space` contains no parameter whose name matches any of the patterns: `regime*`, `trend_filter*`, `htf_*`.

#### Scenario: Candidate without regime parameter raises error
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="mean_reversion"` and `effective_search_space={"zscore_window": [20], "zscore_threshold": [2.0]}`
- **THEN** `CandidateValidationError` is raised with a message referencing regime filter

#### Scenario: Candidate with regime_ema parameter passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="mean_reversion"` and `effective_search_space={"zscore_window": [20], "regime_ema": [50, 100]}`
- **THEN** no `CandidateValidationError` is raised for the regime gate check

#### Scenario: Candidate with htf_ema parameter passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="mean_reversion"` and `effective_search_space={"zscore_threshold": [2.0], "htf_ema": [200]}`
- **THEN** no `CandidateValidationError` is raised for the regime gate check

#### Scenario: Candidate with trend_filter parameter passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="mean_reversion"` and `effective_search_space={"zscore_threshold": [2.0], "trend_filter_period": [50]}`
- **THEN** no `CandidateValidationError` is raised for the regime gate check

#### Scenario: Non-mean_reversion families are unaffected
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="trend_continuation"` and a search space with no regime parameter
- **THEN** no `CandidateValidationError` is raised for the regime gate check
