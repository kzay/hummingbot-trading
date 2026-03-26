## Why

The workspace already has a real strategy research stack, a capable backtest engine, a replay harness, and a mature paper engine. The problem is not missing components. The problem is that the components are only partially governed as a production research pipeline.

Today the research loop is still too easy to overfit:

- candidate definitions are thin and weakly validated
- discovery is LLM-first instead of template-first
- storage roots and API expectations drift from controller defaults
- experiment manifests do not persist the fields the API and operators need
- candle-harness results can be treated too optimistically
- lifecycle promotion to `paper` is mostly a label, not an operational paper-validation workflow

That leaves the desk exposed to the usual failure mode: a strategy that looks strong in backtest, passes a narrow metric, and reaches paper trading without enough realism, reproducibility, or explainable gating.

This change upgrades the existing research lab into a governed, production-grade strategy research pipeline without rewriting the current engines.

## What Changes

- Harden the candidate contract so research artifacts are explicit about strategy family, search space, constraints, required data, market conditions, evaluation rules, and promotion policy while remaining backward-compatible with legacy YAML
- Unify research storage on `hbot/data/research` across controllers and API readers
- Make template-first discovery the default with bounded parameter contracts for phase-one strategy families:
  - trend continuation
  - trend pullback
  - compression breakout
  - mean reversion
  - regime-conditioned momentum
  - funding dislocation only when funding data is present
- Introduce staged validation:
  - fast verification on the current candle harness
  - replay-grade validation for candidates that pass the first gate and have the required data
- Add hard reject gates before composite ranking, explicit overfitting defenses, richer manifests, and desk-grade reporting
- Turn paper promotion into an operational workflow with deployable paper artifacts, paper-run tracking, and divergence analysis against backtest expectations
- Extend the research API and reporting surface to expose validation tier, gate outcomes, ranking signals, paper status, and leaderboard data

## Capabilities

### Added Capabilities

- `research-candidate-governance`: governed candidate schema, backward-compatible loading, pre-backtest validation, and required-data checks
- `research-template-discovery`: template-first family registry with bounded search spaces and invalid-combination rejection
- `research-validation-pipeline`: staged validation, hard gates, stress reruns, overfitting defenses, richer manifests, and composite ranking
- `paper-validation-gate`: operational paper promotion artifacts, paper-run tracking, and divergence-based downgrade/reject logic

### Modified Capabilities

- `research-api`: unified storage root, richer candidate detail, leaderboard support, and central candidate registry visibility for exploration output

## Impact

- **Controllers**: `controllers/research/*` will be widened, not replaced
- **Backtesting**: existing candle and replay harnesses remain the validation engines; the research orchestrator gains staged use of both
- **Paper trading**: existing paper engine remains the execution simulator; research adds promotion artifacts and review state around it
- **Data**: all research state remains file-backed under `hbot/data/research`, but manifests and paper artifacts become richer
- **UI/API**: existing research worker and dashboard integrations remain the delivery surface; they gain more metadata instead of being replaced
- **Docs and task files**: implementation of this change will refresh `tasks/todo.md` and `tasks/lessons.md` with the repo-specific audit and action plan

## Out of Scope

- Greenfield replacement of the research, backtest, replay, or paper engines
- Phase-one open-interest or liquidation-driven discovery as first-class search families
- Automatic live trading promotion
- New ML strategy-generation systems

## Related context

This change builds directly on the earlier strategy research lab work and closes the gap between existing research artifacts and a true desk-grade promotion pipeline.
