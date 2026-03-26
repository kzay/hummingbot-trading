# Research Pipeline Hardening — Work Plan

## Audit Summary

| Area | Status | Notes |
|------|--------|-------|
| Candidate contract | Weak | Missing family, template, search_space, constraints, promotion policy |
| Storage roots | Drifted | API uses `data/research`; controllers use `hbot/data/research` |
| Discovery workflow | LLM-first | No template anchoring, no family registry, unconstrained search |
| Experiment manifests | Thin | Missing gate results, validation tier, stress results, paper fields |
| Validation pipeline | Single-pass | No staged tiers; candle results treated too optimistically |
| Paper promotion | Label-only | No deployable artifacts, no paper-run tracking, no divergence monitoring |
| API surface | Partial | Missing strategy_family, validation_tier, gate_results, leaderboard |
| Overfitting defenses | Absent | No period/trade concentration checks, no fragility signals |

---

## Phase 1 (Incremental) — Candidate Contract and Storage

### 1.1 — Unify Storage Root
- [x] Fix `_RESEARCH_DIR` default in `services/common/research_api.py` → `hbot/data/research`
- [x] Confirm all controller defaults (`exploration_session.py`, `experiment_orchestrator.py`) already use `hbot/data/research`

### 1.2 — Extend StrategyCandidate (Additive)
- [x] Add governed fields: `schema_version`, `strategy_family`, `template_id`, `search_space`, `constraints`, `required_data`, `market_conditions`, `expected_trade_frequency`, `evaluation_rules`, `promotion_policy`, `complexity_budget`
- [x] Preserve backward compatibility in `from_yaml` / `to_yaml`
- [x] Mark legacy YAML with `schema_version: 1` on load; governed YAML uses `schema_version: 2`

### 1.3 — Normalize Search Space
- [x] Add `effective_search_space` property: prefers `search_space`, falls back to `parameter_space`
- [x] Update orchestrator sweep/walk-forward to use `effective_search_space`

### 1.4 — Persist Richer Manifests
- [x] Extend `HypothesisRegistry.record_experiment()` with: `recommendation`, `score_breakdown`, `gate_results`, `validation_tier`, `stress_results`, `artifact_paths`, `paper_run_id`, `paper_status`, `paper_vs_backtest`, `candidate_hash`, `strategy_family`, `template_id`

---

## Phase 2 (Incremental) — Template-First Discovery

### 2.1 — Family/Template Registry
- [x] Create `controllers/research/family_registry.py` with 6 phase-one families: `trend_continuation`, `trend_pullback`, `compression_breakout`, `mean_reversion`, `regime_conditioned_momentum`, `funding_dislocation`
- [x] Define bounded search contracts per family
- [x] Add invalid-combination detection

### 2.2 — Pre-Backtest Candidate Validator
- [x] Create `controllers/research/candidate_validator.py`
- [x] Validate: adapter consistency, supported family, required-data availability, invalid parameter combos, complexity budget, family-specific risk budgets

### 2.3 — Template-Backed Exploration
- [x] Update `exploration_prompts.py` to include family/template context
- [x] Update `exploration_session.py` to write canonical artifacts to central candidates registry

---

## Phase 3 (Incremental) — Validation and Ranking

### 3.1 — Staged Validation Tiers
- [x] Add `validation_tier` tracking to `ExperimentOrchestrator`: `candle_only` vs `replay_validated`
- [x] Block candle-only candidates from auto-paper promotion

### 3.2 — Hard Reject Gates
- [x] Create `controllers/research/quality_gates.py`
- [x] Implement default gates: net PnL, drawdown, profit factor, OOS Sharpe, OOS degradation, DSR, trade-count floor by frequency

### 3.3 — Overfitting Defenses
- [x] Period concentration check (single month ≤ 50% of total PnL)
- [x] Trade concentration check (single trade ≤ 15% of total PnL)
- [x] Parameter fragility check (neighbors retain ≥ 80% of center score)
- [x] Complexity penalty (> 6 tunable parameters)

### 3.4 — Expanded Ranking
- [x] Extend `RobustnessScorer` with: return, drawdown, profit factor, OOS stability, regime stability, stress resilience, trade-count adequacy, simplicity, paper alignment

---

## Phase 4 (Structural) — Paper Validation Workflow

### 4.1 — Paper Artifact Generation
- [x] Create `controllers/research/paper_workflow.py`
- [x] Generate deployable paper artifacts for paper-eligible candidates
- [x] Include: pinned parameters, expected conditions, risk budget, backtest bands

### 4.2 — Paper Run Records
- [x] Track paper runs as research-owned records keyed by candidate + experiment run

### 4.3 — Divergence Monitoring
- [x] Compare paper behavior to backtest expectations across: timing, fills, slippage, trade count, PnL, regime exposure, operational failures

### 4.4 — Downgrade / Reject Logic
- [x] Downgrade or reject candidates breaching configured divergence bands
- [x] Record specific breach dimension in rejection reason

---

## Phase 5 (Structural) — API, Reporting, and Tests

### 5.1 — API Updates
- [x] Fix storage root in research API
- [x] Extend candidate list/detail with governed fields
- [x] Add `/api/research/leaderboard` endpoint
- [x] Exploration sessions write canonical candidates to central registry

### 5.2 — Richer Reports
- [x] Update `ReportGenerator` to include: family, required data, validation tier, gates, stress results, replay eligibility, paper status

### 5.3 — Tests
- [x] Unit tests: legacy loading, governed validation, invalid-combo rejection, complexity penalties, manifest serialization
- [x] Orchestrator tests: staged validation, gate enforcement, replay eligibility, paper-artifact creation
- [x] Lifecycle tests: promotion gating, divergence-based downgrade logic
- [x] API regression tests: richer candidate detail, leaderboard response

---

## Progress Log

| Date | Change | Impact |
|------|--------|--------|
| 2026-03-26 | Initial research-pipeline audit complete | Identified contract gaps, storage drift, missing governance layer |
| 2026-03-26 | Unified storage root to hbot/data/research | Eliminates API/controller path drift |
| 2026-03-26 | Extended StrategyCandidate with governed fields | Additive, backward-compatible; schema_version distinguishes legacy from governed |
| 2026-03-26 | Added effective_search_space normalization | Orchestrator uses unified search definition |
| 2026-03-26 | Created family_registry.py | 6 phase-one families with bounded search contracts |
| 2026-03-26 | Created candidate_validator.py | Pre-backtest validation: adapter, family, data, combos, budget |
| 2026-03-26 | Extended HypothesisRegistry manifests | Gate results, validation tier, stress, paper fields persisted |
| 2026-03-26 | Created quality_gates.py | Hard reject gates + overfitting defenses |
| 2026-03-26 | Added staged validation tiers to orchestrator | candle_only vs replay_validated; candle-only blocked from auto-paper |
| 2026-03-26 | Created paper_workflow.py | Deployable paper artifacts, paper-run records, divergence tracking, downgrade logic |
| 2026-03-26 | Updated research API | Unified root, richer payloads, leaderboard endpoint |
| 2026-03-26 | Updated ReportGenerator | Includes family, gates, stress, paper status in reports |
| 2026-03-26 | Updated exploration prompts/session | Template-first discovery; sessions write to central candidates registry |
| 2026-03-26 | Added test suite | Unit, orchestrator, lifecycle, and API regression tests |
