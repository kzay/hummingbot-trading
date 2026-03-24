## ADDED Requirements

### Requirement: Fix fee_stress_test call site

The `WalkForwardRunner.run()` method SHALL call `fee_stress_test()` with the correct positional arguments matching its signature: `(base_sharpe, base_fee_drag_pct, fee_multipliers, stressed_maker_ratio, base_maker_ratio)`. The returned `sharpe_at_levels` dict SHALL be unpacked correctly when building the `stressed_sharpes` list.

#### Scenario: Fee stress runs without TypeError
- **WHEN** `WalkForwardRunner.run()` executes the fee stress block
- **THEN** no `TypeError` is raised and `result.fee_stress_sharpes` contains a float per multiplier

### Requirement: Wire Holm-Bonferroni and BH FDR

`WalkForwardRunner.run()` SHALL call the existing `holm_bonferroni_test()` and `bh_fdr_test()` functions after computing OOS Sharpe values. The results SHALL populate `WalkForwardResult.holm_bonferroni_pass` and `WalkForwardResult.bh_fdr_pass`.

#### Scenario: Multiple hypothesis correction applied
- **WHEN** walk-forward produces OOS Sharpe values across N windows
- **THEN** `result.holm_bonferroni_pass` is a boolean reflecting whether the best result survives correction
- **THEN** `result.bh_fdr_pass` is a boolean reflecting the BH FDR test

### Requirement: Improved DSR inputs

The DSR computation SHALL use the actual number of return observations from pooled OOS equity curves (not `len(oos_sharpes) * 30`) and SHALL estimate skewness and kurtosis from the pooled return series (not hardcoded 0 and 3).

#### Scenario: DSR with real statistics
- **WHEN** OOS equity curves contain 500 daily returns
- **THEN** `n_returns` passed to `deflated_sharpe_ratio()` is 500, and skew/kurtosis are computed from those returns
