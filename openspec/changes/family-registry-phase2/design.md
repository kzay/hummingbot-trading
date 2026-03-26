## Context

The research pipeline uses a flat `FAMILY_REGISTRY` dict in `family_registry.py` where each entry is a `StrategyFamily` dataclass with parameter bounds, templates, supported adapters, and invalid-combination rules. The `candidate_validator.py` module enforces these contracts pre-backtest, raising `CandidateValidationError` on hard failures.

Current state:
- 6 registered families: `trend_continuation`, `trend_pullback`, `compression_breakout`, `mean_reversion`, `regime_conditioned_momentum`, `funding_dislocation`
- `mean_reversion` has no regime filter enforcement — any candidate with `strategy_family: mean_reversion` will pass validation regardless of whether it has a regime gate parameter
- No family covers delta-neutral carry or basis convergence (structurally different from `funding_dislocation` directional entries)
- No family covers multi-leg spread or ratio trades

## Goals / Non-Goals

**Goals:**
- Add `basis_carry` family with 3 templates and delta-neutrality bounds enforcement
- Add `relative_value` family with 3 templates and hedge-ratio bounds enforcement
- Harden `mean_reversion` to reject ungated candidates in `candidate_validator.py`
- Keep all changes additive and backward-compatible with existing candidates
- Update exploration prompts so the LLM explorer generates valid governed candidates for both new families
- Test coverage for all three changes

**Non-Goals:**
- Implementing the actual carry or spread trading adapters (families define the research contract, not the execution logic)
- Adding multi-asset data pipeline or live data feeds
- Changing the robustness scorer weights for the new families
- Adding `session_event_window` family (deferred to phase 3)

## Decisions

### D1: `basis_carry` as a separate family from `funding_dislocation`

**Decision:** New family, not an extension of `funding_dislocation`.

**Rationale:** The two families have different mechanics. `funding_dislocation` takes a directional position when funding spikes abnormally — it has market exposure and relies on mean-reversion of the spike. `basis_carry` either runs delta-neutral (no market exposure, collects yield) or trades the spot/perp spread directly. They require different parameter contracts, different data (`spot` price feed required for basis tracking), different risk sizing (carry runs larger notional at lower per-trade risk), and different invalid-combination rules (delta exposure cap vs. funding threshold). Merging them would dilute the contract for both.

**Alternative considered:** Add `carry_mode: bool` flag to `funding_dislocation`. Rejected because it would require conditional bounds logic and split the template contracts.

### D2: `relative_value` requires `["multi_asset"]` as a required data flag

**Decision:** Use a string sentinel `"multi_asset"` in `required_data` rather than enumerating specific asset pairs.

**Rationale:** The validator currently checks `required_data` membership against what the candidate declares as available data. Asset pair specifics (BTC/ETH vs ETH/SOL) are candidate-level parameters, not family-level requirements. The family only needs to assert "this strategy requires more than one asset's price feed." The specific pair is part of the candidate's search space.

**Alternative considered:** Enum of valid pairs. Rejected — would hardcode market assumptions into the family contract and require constant updates.

### D3: `mean_reversion` regime gate enforced in `candidate_validator.py`, not in `StrategyFamily.check_bounds()`

**Decision:** The regime-gate check lives in the validator as a family-specific rule, not as a generic `ParameterBounds` check.

**Rationale:** `check_bounds()` operates on numeric ranges of individual parameters. The regime gate check is a *presence* check — does any parameter matching `regime*`, `trend_filter*`, or `htf_*` exist in the search space? This is structural, not numeric. Adding it to `check_bounds()` would require changing the `ParameterBounds` contract. The validator is the right place for structural candidate requirements.

**Alternative considered:** Adding a `required_params_pattern` field to `StrategyFamily`. Reasonable but over-engineers the dataclass for a single family's constraint.

### D4: Template renaming for `mean_reversion` is explicit, not silent

**Decision:** Rename `mean_reversion_zscore` → `mean_reversion_zscore_regime_filtered` and `mean_reversion_mm` → `mean_reversion_mm_regime_filtered`. Add `regime_ema` to `required_params` in both.

**Rationale:** The LLM explorer uses template IDs to select the correct template. If the template name doesn't signal the regime requirement, the LLM may generate candidates without a regime parameter and pass template selection but fail validation. Making the requirement visible in the template ID prevents this. Existing candidates referencing the old template IDs will fail validation — but since no production candidates use `mean_reversion` family in the governed pipeline yet, this is a clean break.

## Risks / Trade-offs

**[Risk] `multi_asset` data not available in current backtest harness** → Mitigation: The validator only checks that the candidate *declares* the correct required data. `relative_value` candidates will be created and stored but will fail at backtest execution if the harness can't supply multi-asset feeds. This is acceptable for phase 2 — families define the research contract; harness support is a separate concern.

**[Risk] Delta-neutrality bounds on `basis_carry` are enforced by parameter name pattern matching only** → Mitigation: `check_bounds()` matches bound names by substring. As long as candidate parameters use `delta_exposure` as a key name, the bound will be enforced. Document this in the family description and in exploration prompts.

**[Risk] LLM explorer generates `relative_value` candidates without a second asset defined** → Mitigation: Update `exploration_prompts.py` to explicitly require a `pair` or `secondary_asset` parameter in all `relative_value` templates, and add it to `required_params`.

**[Risk] Mean reversion template rename breaks any existing candidates using old template IDs** → Mitigation: No existing governed candidates use `mean_reversion` family — the family was added in phase 1 before any governed candidates were created. Legacy (v1) candidates without `strategy_family` are unaffected.

## Migration Plan

1. Update `family_registry.py` — all changes are additive except `_MEAN_REVERSION` modification and template rename
2. Update `candidate_validator.py` — new rule only triggers for `strategy_family == "mean_reversion"`, no effect on other families
3. Update `exploration_prompts.py` — prompt-only change, no runtime impact
4. Add tests — no production impact
5. No data migration required — manifest schema is unchanged, family metadata is stored in candidates only

Rollback: revert `family_registry.py` and `candidate_validator.py`. No state is persisted that depends on the new families.

## Open Questions

- Should `relative_value` require the secondary asset ticker to be declared in `required_data` (e.g., `["multi_asset", "ETH-USDT"]`) or is the generic sentinel sufficient? Current design uses generic sentinel; if the backtest harness needs the specific ticker to load data, this may need to change.
- Should `basis_carry` delta-exposure cap (0.25) be a hard gate in `quality_gates.py` or only a bounds violation in the family contract? Currently only in bounds — consider promoting to a hard gate if carry strategies start getting promoted to paper.
