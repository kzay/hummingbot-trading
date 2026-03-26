## Why

The phase-one family registry covers directional trend and momentum strategies well but has two structural gaps: it has no family for delta-neutral / carry trades (basis and funding yield), and no family for multi-leg spread / relative-value trades. Additionally, the existing `mean_reversion` family carries no regime-conditioning requirement, making it systematically dangerous in trending markets — a blowup source that the pipeline currently cannot detect or reject.

## What Changes

- Add `basis_carry` strategy family: delta-neutral and semi-directional trades on the perpetual futures basis and persistent funding carry — mechanically distinct from the existing `funding_dislocation` directional family
- Add `relative_value` strategy family: multi-leg spread and ratio trading across correlated assets (BTC/ETH ratio, cross-venue basis, spot/perp spread excluding funding yield)
- Harden `mean_reversion` family: add regime filter as a hard enforcement constraint at both the family definition and pre-backtest validator levels; rename templates to make the requirement explicit
- Update exploration prompts and YAML schema reference to document both new families
- Add targeted test coverage for all three changes

## Capabilities

### New Capabilities

- `basis-carry-family`: `StrategyFamily` definition with bounded parameter contracts, 3 templates, required data `["funding", "spot"]`, and delta-neutrality enforcement rules
- `relative-value-family`: `StrategyFamily` definition with bounded parameter contracts, 3 templates, required data `["multi_asset"]`, and hedge-ratio validity enforcement

### Modified Capabilities

- `mean-reversion-family`: existing `mean_reversion` family hardened with regime gate — adds required parameter bounds for `regime_window`, renames templates to signal the requirement, and adds an invalid-combination rule; `candidate_validator.py` enforces rejection of ungated candidates

## Impact

- `hbot/controllers/research/family_registry.py` — 2 new family definitions, modification of `_MEAN_REVERSION`, registry and `SUPPORTED_FAMILIES` updated
- `hbot/controllers/research/candidate_validator.py` — new validation rule for `mean_reversion` family
- `hbot/controllers/research/exploration_prompts.py` — template-first discovery table and YAML schema reference extended
- `hbot/tests/controllers/test_research/test_research_pipeline_hardening.py` — new test classes for both families and the regime-gate enforcement
