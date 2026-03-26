## Context

The repository already contains:

- a research lab under `controllers/research/`
- a candle-harness backtest engine
- a replay harness with richer trade and funding realism
- a simulation and paper-exchange stack
- a research worker API and dashboard integrations

What is missing is governance across those pieces. Candidate contracts are too loose, exploration is too free-form, manifests are too thin, and lifecycle promotion does not yet guarantee that a candidate has survived replay-grade validation or produced a deployable paper artifact.

## Goals / Non-Goals

**Goals**

- Preserve the current engines and extend them incrementally
- Make research artifacts explicit, explainable, and reproducible
- Shift from LLM-first discovery to template-first governed discovery
- Prevent candle-only validation from auto-promoting to paper
- Add hard gates and overfitting defenses before ranking
- Create an operational paper-validation workflow with divergence tracking
- Keep the API and UI additive, not rewritten

**Non-Goals**

- Replacing the backtest or paper engines
- Building a live auto-promotion path
- Supporting open-interest and liquidation strategies in phase one without first-class data support
- Introducing a database-backed research registry

## Decisions

### D1. File-backed research storage remains the system of record

**Decision**: Keep research state file-backed under `hbot/data/research`.

**Why**: The existing controllers and worker already rely on file-backed artifacts. The immediate risk is drift, not storage technology. Unifying all readers and writers on the same root provides the needed operational consistency without introducing a database migration.

### D2. Candidate schema expands additively

**Decision**: Extend the candidate interface with additive fields rather than replacing the legacy YAML contract.

New governed fields include:

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

**Why**: Existing candidates, tests, and exploration flows already expect the current schema. Backward-compatible widening avoids breaking the current lab while allowing the new governance layer to become authoritative.

### D3. `parameter_space` remains a compatibility alias

**Decision**: Treat `parameter_space` as the legacy alias and `search_space` as the governed representation.

**Why**: The current orchestrator and tests already consume `parameter_space`. During implementation, the loader should normalize both names into one effective search definition so existing files remain valid.

### D4. Discovery becomes template-first

**Decision**: Candidate generation must anchor to a strategy family and template before evaluation.

Phase-one families:

- `trend_continuation`
- `trend_pullback`
- `compression_breakout`
- `mean_reversion`
- `regime_conditioned_momentum`
- `funding_dislocation` only when funding data is present

**Why**: The current LLM-first generation path can produce candidates that are syntactically valid but conceptually unconstrained. Template-first discovery limits the search to hypotheses the desk can reason about and the current data architecture can support.

### D5. Validation is tiered, not single-pass

**Decision**: Validation proceeds in two tiers:

1. fast verification on the candle harness
2. replay-grade validation for candidates that pass first-pass gates and have the required data

**Why**: The candle harness is useful for early pruning, but it is not sufficient as a paper-promotion gate. Replay-grade validation must be the minimum threshold for auto-paper eligibility.

### D6. Hard gates run before composite ranking

**Decision**: Ranking never rescues a candidate that fails minimum desk-quality gates.

Default hard gates:

- positive net PnL after fees
- max drawdown `<= 20%`
- profit factor `>= 1.15`
- mean OOS Sharpe `>= 0.5`
- OOS degradation ratio `>= 0.6`
- deflated Sharpe `> 0`
- trade-count floor by expected frequency:
  - low frequency: `>= 20`
  - medium frequency: `>= 40`
  - high frequency: `>= 80`

**Why**: A composite score is useful for ranking survivors, not for excusing basic research failures.

### D7. Overfitting defenses are first-class artifacts

**Decision**: Overfitting checks must be persisted and visible, not hidden inside a final score.

Phase-one defenses:

- no single month contributes more than `50%` of total PnL
- no single trade contributes more than `15%` of total PnL
- neighboring parameter settings retain at least `80%` of the center candidate's median robust score
- candidates with more than `6` tunable parameters incur a simplicity penalty

**Why**: The desk must be able to explain why a candidate is fragile, not just see that it scored lower.

### D8. Paper promotion becomes an operational workflow

**Decision**: Promotion to `paper` requires a generated paper artifact, a research-owned paper run record, and divergence monitoring against validated expectations.

**Why**: Changing lifecycle state without deployable configuration and post-promotion monitoring is bookkeeping, not validation.

### D9. Live promotion remains manual

**Decision**: This change stops at research retention, rejection, and paper-validation outcomes.

**Why**: The missing problem is governed research-to-paper promotion, not unattended live deployment.

## Risks / Trade-offs

- **Legacy candidate drift**: backward-compatible loading can preserve sloppy old definitions longer than ideal. Mitigation: mark legacy files with `schema_version: 1` and surface warnings until they are upgraded.
- **Replay data availability**: some candidates may pass first-pass validation but lack replay inputs. Mitigation: retain them as research artifacts while explicitly marking them ineligible for auto-paper.
- **Score complexity**: more ranking inputs can become opaque. Mitigation: persist component breakdowns and gate results separately from the final score.
- **Paper divergence thresholds**: if thresholds are too tight, good candidates may be downgraded unfairly; too loose, weak candidates slip through. Mitigation: keep thresholds configurable and record the exact breach reason.

## Migration Plan

1. Unify storage roots and manifest structure first
2. Expand the candidate contract with backward-compatible loading
3. Add template registry and pre-backtest validation
4. Introduce staged validation and hard gates
5. Add paper artifact generation and paper-run tracking
6. Expose the richer metadata through API, reports, and leaderboard views
7. Refresh `tasks/todo.md` and `tasks/lessons.md` during implementation to reflect the new governed workflow

## Open Questions

1. Should leaderboard ranking surface only paper-eligible candidates by default, or all retained candidates with filters?
2. Should replay-grade validation become mandatory for all families, or only for those with compatible data paths?
3. How wide should default divergence bands be for fill quality and trade-frequency mismatch in the first rollout?
