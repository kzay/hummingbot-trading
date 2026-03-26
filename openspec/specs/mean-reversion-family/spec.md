### Requirement: mean_reversion family enforces regime gate
The `mean_reversion` family definition SHALL include a `regime_window` parameter bound [20, 200], SHALL add the invalid-combination rule `no regime gate (mean_reversion WITHOUT regime filter is a blowup source in trending markets)`, and SHALL set `regime_gate_required: True`. Templates SHALL be named `mean_reversion_zscore_regime_gated` and `mean_reversion_mm_regime_gated`, each with `regime_window` in `required_params`.

#### Scenario: regime_window bounds are present in family
- **WHEN** the `mean_reversion` family's `parameter_bounds` are inspected
- **THEN** a bound named `regime_window` exists with `min_val=20` and `max_val=200`

#### Scenario: Invalid combination rule references regime gate
- **WHEN** the `mean_reversion` family's `invalid_combinations` list is inspected
- **THEN** at least one entry references "regime" or "regime gate"

#### Scenario: regime_gate_required flag is True
- **WHEN** `get_family("mean_reversion").regime_gate_required` is inspected
- **THEN** the value is `True`

#### Scenario: Regime-gated zscore template is retrievable
- **WHEN** `get_template("mean_reversion_zscore_regime_gated")` is called on the `mean_reversion` family
- **THEN** a `FamilyTemplate` instance is returned

#### Scenario: Regime-gated mm template is retrievable
- **WHEN** `get_template("mean_reversion_mm_regime_gated")` is called on the `mean_reversion` family
- **THEN** a `FamilyTemplate` instance is returned

#### Scenario: Old template IDs are no longer present
- **WHEN** `get_template("mean_reversion_zscore")` is called on the `mean_reversion` family
- **THEN** `None` is returned

#### Scenario: regime_window is required in all templates
- **WHEN** each template's `required_params` list is inspected
- **THEN** `regime_window` is present in every template

### Requirement: candidate_validator rejects ungated mean_reversion candidates
The `candidate_validator` SHALL raise `CandidateValidationError` when `strategy_family == "mean_reversion"` and the candidate's `effective_search_space` contains no parameter whose name matches any of: `regime*`, `trend_filter*`, `htf_*`.

#### Scenario: Candidate without regime parameter raises error
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="mean_reversion"` and `effective_search_space={"zscore_window": [20], "zscore_threshold": [2.0]}`
- **THEN** `CandidateValidationError` is raised with a message referencing regime filter

#### Scenario: Candidate with regime_window parameter passes
- **WHEN** `validate_candidate(candidate)` is called with `strategy_family="mean_reversion"` and `effective_search_space={"zscore_window": [20], "regime_window": [50, 100]}`
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
