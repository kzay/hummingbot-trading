## 1. Audit and documentation refresh

- [x] 1.1 Replace the stale regime-focused content in `tasks/todo.md` with a research-engine audit, prioritized work plan, and incremental-vs-structural breakdown
- [x] 1.2 Replace the stale regime-focused content in `tasks/lessons.md` with technical findings, research-quality risks, realism risks, overfitting risks, assumptions, and unknowns

## 2. Candidate contract and storage hardening

- [x] 2.1 Unify all research readers and writers on `hbot/data/research`
- [x] 2.2 Extend `StrategyCandidate` with governed additive fields while preserving legacy YAML compatibility
- [x] 2.3 Normalize `parameter_space` and `search_space` into one effective search definition
- [x] 2.4 Add pre-backtest candidate validation for adapter consistency, required-data availability, invalid combinations, and family-specific risk budgets
- [x] 2.5 Persist richer experiment manifests including recommendation, score breakdown, gate results, validation tier, stress results, artifact paths, paper identifiers, and reproducibility metadata

## 3. Template-first discovery

- [x] 3.1 Add a family/template registry for trend continuation, trend pullback, compression breakout, mean reversion, regime-conditioned momentum, and funding dislocation
- [x] 3.2 Define bounded default search contracts per family
- [x] 3.3 Reject unsupported or nonsensical candidate combinations before any backtest starts
- [x] 3.4 Update exploration prompts and parsing so generated candidates are template-backed rather than free-form
- [x] 3.5 Make exploration sessions write canonical candidate artifacts into the central candidates registry as well as session-local output

## 4. Validation, ranking, and manifests

- [x] 4.1 Split evaluation into candle verification and replay-grade validation tiers
- [x] 4.2 Prevent candle-only candidates from auto-promoting to paper
- [x] 4.3 Add hard reject gates for net PnL, drawdown, profit factor, OOS Sharpe, OOS degradation, DSR, and trade-count adequacy
- [x] 4.4 Add explicit overfitting defenses for period concentration, trade concentration, parameter fragility, and complexity
- [x] 4.5 Replace proxy-only stress handling where practical with stressed reruns for fees, fills, and latency
- [x] 4.6 Expand ranking to combine return, drawdown, profit factor, OOS stability, regime stability, stress resilience, trade-count adequacy, simplicity, and paper alignment when available

## 5. Paper validation workflow

- [x] 5.1 Generate deployable paper artifacts for paper-eligible candidates
- [x] 5.2 Create a research-owned paper run record keyed by candidate and experiment run
- [x] 5.3 Track paper-vs-backtest divergence on timing, fills, slippage, trade count, PnL, regime exposure, and operational failures
- [x] 5.4 Add downgrade and rejection logic based on divergence thresholds

## 6. API, reporting, and UI surface

- [x] 6.1 Update the research API to use the unified research root and adapter registry as the source of truth
- [x] 6.2 Extend candidate list/detail payloads with strategy family, validation tier, gate results, paper status, and richer recommendation data
- [x] 6.3 Add a read-only leaderboard endpoint or payload view for ranked candidates
- [x] 6.4 Regenerate markdown reports to include family, required data, validation tier, gates, stress results, replay eligibility, and paper status

## 7. Tests and verification

- [x] 7.1 Add unit tests for legacy candidate loading, governed candidate validation, invalid-combination rejection, complexity penalties, and manifest serialization
- [x] 7.2 Add orchestrator tests for staged validation, gate enforcement, replay eligibility, and paper-artifact creation
- [x] 7.3 Add lifecycle and paper-validation tests for promotion gating and divergence-based downgrade logic
- [x] 7.4 Add API regression tests for richer candidate detail and leaderboard responses
- [ ] 7.5 Re-run the research, backtesting, and paper-engine test suites once a usable Python environment is available
