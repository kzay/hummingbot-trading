# Research Pipeline Hardening — Technical Findings & Architecture Notes

## Research Quality Risks

### Risk 1: Candidate Contracts Are Too Loose (HIGH)

**Finding:** `StrategyCandidate` has no `strategy_family`, `template_id`, `search_space`, `constraints`, `required_data`, or `promotion_policy` fields. Any free-form YAML can be evaluated without a prior validity check.

**Consequence:** The LLM exploration path can produce syntactically valid candidates that are semantically unconstrained — windows inverted, stops above targets, families with no data support. These consume backtest compute and produce misleading scores.

**Fix:** Added governed fields to `StrategyCandidate` with backward-compatible loading. Pre-backtest validator (`candidate_validator.py`) rejects invalid combinations before any compute is consumed.

---

### Risk 2: Storage Root Drift (MEDIUM)

**Finding:** `services/common/research_api.py` defaults to `data/research`; all controller code defaults to `hbot/data/research`. On environments where `RESEARCH_DATA_DIR` is not explicitly set, the API reads a different directory than the controllers write.

**Consequence:** Candidates written by the exploration engine are invisible to the API. Lifecycle state written by the orchestrator is unreadable by the dashboard.

**Fix:** Changed `_RESEARCH_DIR` default to `hbot/data/research`. Documented the env var override for deployment contexts.

---

### Risk 3: LLM-First Discovery Produces Unconstrained Hypotheses (HIGH)

**Finding:** The exploration system instructs the LLM to generate free-form YAML. No template, no family anchor, no bounded parameter contract. The LLM can invent parameter names that do not exist in the adapter, propose funding strategies without funding data, or produce windows that break monotonicity assumptions.

**Consequence:** High parse-error rates, adapter mismatches, and semantically broken candidates that survive YAML parsing but fail silently in evaluation.

**Fix:** Added `family_registry.py` with 6 phase-one families and bounded search contracts. Exploration prompts updated to anchor on family/template before parameter generation.

---

### Risk 4: Candle Harness Results Treated Too Optimistically (HIGH)

**Finding:** The orchestrator runs a single backtest on the candle harness, scores it, and the lifecycle manager can promote candidates directly to `paper` based on the robustness score alone. The candle harness does not model fills, latency, or funding with replay realism.

**Consequence:** Candidates promoted to paper trading without replay-grade validation may show dramatic performance degradation due to fill model differences.

**Fix:** Introduced `validation_tier`: candle-only candidates are marked `candle_only` and blocked from auto-paper promotion. Only candidates that pass replay-grade validation (`replay_validated`) may be auto-promoted.

---

### Risk 5: No Hard Reject Gates Before Ranking (HIGH)

**Finding:** The current pipeline ranks all candidates by composite robustness score. A candidate with negative net PnL, 40% drawdown, or only 5 trades can still receive a score and be recommended if its OOS degradation ratio happens to be favorable.

**Consequence:** Broken strategies can appear in leaderboard and promotion queues.

**Fix:** Added `quality_gates.py` with hard gates: positive net PnL, max drawdown ≤ 20%, profit factor ≥ 1.15, OOS Sharpe ≥ 0.5, OOS degradation ≥ 0.6, DSR > 0, minimum trade counts by frequency tier. Gates run before ranking. Failures are persisted in the manifest.

---

### Risk 6: No Overfitting Defenses (HIGH)

**Finding:** The robustness scorer penalizes high OOS degradation ratio and high parameter CV but does not check for period concentration, trade concentration, or parameter fragility explicitly.

**Consequence:** A strategy that made 80% of its PnL in one month, or whose score collapses if a single parameter moves by one tick, can score well and reach paper trading.

**Fix:** Added explicit overfitting defenses: period concentration (no single month > 50% of PnL), trade concentration (no single trade > 15% of PnL), parameter fragility (neighbors must retain ≥ 80% of center score), complexity penalty (> 6 parameters). All defenses are persisted as named flags in the manifest.

---

### Risk 7: Paper Promotion Is a Label, Not a Workflow (HIGH)

**Finding:** `lifecycle_manager.py` can transition a candidate from `candidate` to `paper` by changing a field in a JSON file. There is no deployable paper artifact, no paper-run record, no divergence monitoring.

**Consequence:** "Paper" status is meaningless as a quality signal. Operators have no way to tell whether a paper-promoted candidate is actually running, or whether it has drifted from its validated parameters.

**Fix:** Created `paper_workflow.py` with: deployable paper artifact generation, research-owned paper run records keyed by candidate + experiment run, paper-vs-backtest divergence monitoring across 7 dimensions, and downgrade/rejection logic with persisted breach reasons.

---

## Realism Risks

### Replay vs Candle Harness Gap

The candle harness synthesizes an order book from OHLCV data and uses simplified fill models. The replay harness uses actual recorded market events for fills. The difference in realized slippage, fill quality, and adverse selection can be material — particularly for directional adapters where entry timing matters.

**Mitigation:** Staging validation so that replay-grade validation is required before paper eligibility. Storing `validation_tier` in the manifest so operators can see which candidates have been replay-tested.

### Fee Sensitivity

Walk-forward evaluation runs with fee stress multipliers of 1.0×, 1.5×, 2.0×, 3.0×. Candidates that fail at 1.5× fees are too marginal for production. The hard gate requires positive performance under the standard fee model; the overfitting defense checks parameter fragility more broadly.

### Funding Cost for Long-Hold Strategies

Candidates with `expected_trade_frequency: low` or hold periods > 8 hours must be evaluated with realistic funding costs. The `funding_dislocation` family requires funding data to be present; without it, the candidate is marked data-unavailable and blocked from evaluation.

---

## Assumptions and Unknowns

### Assumptions

1. **File-backed storage is sufficient.** The research pipeline uses YAML + JSONL + JSON files. This is appropriate for the current scale (hundreds of candidates, thousands of experiment runs). If the candidate universe grows to tens of thousands, a database migration should be considered.

2. **Phase-one families cover the practical search space.** The 6 families (`trend_continuation`, `trend_pullback`, `compression_breakout`, `mean_reversion`, `regime_conditioned_momentum`, `funding_dislocation`) cover the viable strategy space given the current data architecture. Open-interest and liquidation-driven families are deferred pending data availability.

3. **Candle harness is accurate enough for fast pruning.** The candle harness is not replay-grade, but it is faster by an order of magnitude. The two-tier validation approach assumes that candidates which fail on the candle harness would also fail on replay — i.e., that candle results are conservative. This assumption could break for strategies that depend heavily on fill timing.

4. **Divergence thresholds can start wide and tighten.** The initial paper-vs-backtest divergence bands are configurable but set conservatively. The risk is false positives (good candidates downgraded) rather than false negatives (bad candidates retained), because operators review paper-downgrade events.

### Unknowns

1. **How wide should fill-quality divergence bands be?** Fill quality in paper trading can differ from simulation by 5–25% depending on market conditions. The appropriate threshold depends on strategy type and has not been empirically calibrated yet.

2. **Should leaderboard default to paper-eligible only?** Showing all retained candidates vs. only replay-validated candidates is a UI decision. Both views have value; the leaderboard endpoint supports both via filter.

3. **When should legacy candidates be force-upgraded?** Legacy YAML files (schema_version: 1) will accumulate warnings in logs but remain functional. A migration trigger has not been defined.

---

## Architecture Strengths Preserved

1. **Engines are unchanged.** The candle harness, replay harness, sweep runner, and walk-forward runner are not modified. All governance is layered above them.

2. **File-backed research state.** All research artifacts (candidates, manifests, lifecycle, paper runs, reports) remain in `hbot/data/research`. No database dependency introduced.

3. **Backward compatibility.** Existing YAML candidates load without modification. The governed fields are all optional with sensible defaults.

4. **Append-only manifests.** The hypothesis registry remains append-only JSONL. Richer fields are added without breaking existing manifest readers.

5. **Modular governance.** Each governance layer (`candidate_validator`, `family_registry`, `quality_gates`, `paper_workflow`) is a separate module with a clear responsibility. Adding a new family or adjusting a gate threshold requires editing one file.

---

## Architecture Risks

1. **Replay data availability is uneven.** Some candidates may pass candle validation but lack replay inputs — they will be retained as research artifacts but blocked from auto-paper. This creates a class of candidates that are theoretically attractive but operationally blocked. Resolution requires expanding replay data coverage.

2. **Score complexity.** The expanded ranking now combines 9+ components. Component breakdowns are persisted, but the composite score is still a single number. Operators need to understand which components drove a high or low score. The report generator exposes all components explicitly.

3. **Paper divergence requires live monitoring.** The divergence tracking in `paper_workflow.py` compares paper outcomes to backtest expectations, but it requires that paper run results are written back to the research layer. This integration point is defined but requires the paper engine to write structured results to `hbot/data/research/paper_runs/`.

4. **Family registry is not adaptive.** The 6 phase-one families are hardcoded with fixed bounds. Adding a new family requires a code change to `family_registry.py`. A config-driven registry would be more flexible but is out of scope for this change.
