## 1. basis_carry family definition

- [x] 1.1 Add `_BASIS_CARRY` `StrategyFamily` to `family_registry.py` with `required_data=["funding", "spot"]`, `supported_adapters`, `default_complexity_budget=4`, `per_trade_risk_min_pct=0.15`, `per_trade_risk_max_pct=0.50`
- [x] 1.2 Define six `ParameterBounds` for `basis_carry`: `funding_zscore_window` [4,48], `carry_threshold` [0.01,0.10], `basis_spread_threshold` [0.001,0.02], `hold_bars` [8,96], `stop_atr` [0.3,2.0], `delta_exposure` [0.0,0.25]
- [x] 1.3 Define three invalid-combination rules: `hold_bars < 4`, `carry_threshold > 0.10`, `delta_exposure > 0.25`
- [x] 1.4 Add template `basis_carry_funding_yield` with `required_params=["funding_threshold", "hedge_ratio", "holding_period"]` and default search space
- [x] 1.5 Add template `basis_carry_delta_neutral_grid` with `required_params=["basis_threshold", "rebalance_bars"]` and default search space
- [x] 1.6 Add template `basis_carry_semi_directional` with `required_params=["funding_threshold", "basis_threshold", "hedge_ratio"]` and default search space
- [x] 1.7 Register `_BASIS_CARRY` in `FAMILY_REGISTRY` and add `"basis_carry"` to `SUPPORTED_FAMILIES`

## 2. relative_value family definition

- [x] 2.1 Add `_RELATIVE_VALUE` `StrategyFamily` to `family_registry.py` with `required_data=["multi_asset"]`, `supported_adapters`, `default_complexity_budget=5`, `per_trade_risk_min_pct=0.15`, `per_trade_risk_max_pct=0.75`
- [x] 2.2 Define five `ParameterBounds` for `relative_value`: `spread_window` [10,100], `zscore_threshold` [1.0,3.0], `hedge_ratio` [0.5,2.0], `hold_bars` [2,48], `stop_atr` [0.5,3.0]
- [x] 2.3 Define two invalid-combination rules: `zscore_threshold < 1.0`, `hold_bars < 2`
- [x] 2.4 Add template `relative_value_btc_eth_ratio` with `required_params=["entry_zscore", "exit_zscore", "zscore_lookback"]` and default search space
- [x] 2.5 Add template `relative_value_cross_venue_basis` with `required_params=["entry_zscore", "exit_zscore"]` and default search space
- [x] 2.6 Add template `relative_value_spot_perp_spread` with `required_params=["entry_zscore", "zscore_lookback", "hedge_ratio"]` and default search space
- [x] 2.7 Register `_RELATIVE_VALUE` in `FAMILY_REGISTRY` and add `"relative_value"` to `SUPPORTED_FAMILIES`

## 3. mean_reversion family hardening

- [x] 3.1 Add `ParameterBounds("regime_window", 20, 200, ...)` to `_MEAN_REVERSION.parameter_bounds`
- [x] 3.2 Add invalid-combination rule referencing regime gate to `_MEAN_REVERSION.invalid_combinations`
- [x] 3.3 Rename template `mean_reversion_zscore` → `mean_reversion_zscore_regime_gated` and add `"regime_window"` to its `required_params`
- [x] 3.4 Rename template `mean_reversion_mm` → `mean_reversion_mm_regime_gated` and add `"regime_window"` to its `required_params`

## 4. Validator enforcement

- [x] 4.1 In `candidate_validator.py`, add a check: if `strategy_family == "mean_reversion"` and no key in `effective_search_space` matches `regime*`, `trend_filter*`, or `htf_*`, raise `CandidateValidationError("mean_reversion requires a regime filter parameter")`
- [x] 4.2 In `candidate_validator.py`, add a check: if `strategy_family == "basis_carry"` and `"funding"` not in `required_data` or `"spot"` not in `required_data`, raise `CandidateValidationError`
- [x] 4.3 In `candidate_validator.py`, add a check: if `strategy_family == "relative_value"` and `"multi_asset"` not in `required_data`, raise `CandidateValidationError`

## 5. Exploration prompts update

- [x] 5.1 Add `basis_carry` and `relative_value` rows to the family/template table in `exploration_prompts.py` `SYSTEM_PROMPT`
- [x] 5.2 Add governed field documentation for both new families to `YAML_SCHEMA_REFERENCE` in `exploration_prompts.py`
- [x] 5.3 Add a note in `GENERATE_PROMPT` that `mean_reversion` candidates MUST include a `regime_ema`, `htf_*`, or `trend_filter_*` parameter

## 6. Tests

- [ ] 6.1 Add `TestBasisCarryFamily` class: test family is registered, `get_family` returns correct type, `required_data` includes `["funding", "spot"]`, neutral template exists, bounds reject out-of-range `carry_threshold`, bounds reject `delta_exposure > 0.25`
- [ ] 6.2 Add `TestRelativeValueFamily` class: test family is registered, `required_data` includes `["multi_asset"]`, ratio template exists, bounds reject `hedge_ratio < 0.5`, bounds reject `hedge_ratio > 2.0`, bounds reject `zscore_threshold < 1.0`
- [ ] 6.3 Add `TestMeanReversionRegimeGate` class: ungated candidate raises `CandidateValidationError`, candidate with `regime_ema` passes, candidate with `htf_ema` passes, candidate with `trend_filter_period` passes, non-mean_reversion family without regime param is unaffected
- [ ] 6.4 Add `TestMeanReversionTemplateRename` class: `mean_reversion_zscore_regime_filtered` template exists, `mean_reversion_zscore` (old name) returns `None`, `regime_ema` is in renamed template's `required_params`
