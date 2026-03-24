## Why

The backtest and walk-forward engines exist but lack the governance layer needed to prevent overfitting and ensure only robust strategies reach paper trading. Sweep ranking uses a single metric (Sharpe), walk-forward fee-stress code is broken at runtime, lookahead guards are discipline-only (full OHLCV passed on every tick), and experiment results are tracked in manual Markdown ledgers with no immutable run manifests. Without a structured research lab, every candidate strategy is one undetected bias away from promoting a curve-fitted artifact to paper.

## What Changes

- **Fix existing engine gaps**: repair `walkforward.py` `fee_stress_test` call-site TypeError, wire Holm-Bonferroni / BH FDR into `WalkForwardRunner.run()`, align replay harness fill model to `latency_aware` for parity with backtest harness.
- **Add candle lookahead guard**: introduce `VisibleCandleRow` that masks `high`/`low`/`close` until the final intra-bar step, enforcing what `book_synthesizer` already assumes but adapters can violate.
- **New research module** (`hbot/controllers/research/`): `StrategyCandidate` dataclass (hypothesis + entry/exit logic + parameter space + test suite), JSONL-backed hypothesis registry with immutable experiment manifests (config hash + git SHA + data window + seed + fill model + result path), experiment orchestrator driving backtest → sweep → walk-forward pipeline, composite robustness scorer (OOS Sharpe, degradation ratio, parameter CV, fee stress, regime stability, DSR), Markdown report generator with lifecycle recommendation.
- **Strategy lifecycle governance**: `rejected` / `revise` / `paper` / `promoted` classification with promotion gates (minimum robustness score, minimum OOS windows, fee stress pass).
- **CLI entry point**: `python -m controllers.research.evaluate --candidate path/to/candidate.yml`.

## Capabilities

### New Capabilities

- `strategy-candidate-interface`: Unified `StrategyCandidate` dataclass wrapping hypothesis, formal entry/exit logic, parameter space, and required test suite for every candidate strategy.
- `hypothesis-registry`: JSONL-backed registry for hypotheses and immutable experiment manifests linking config, git SHA, data, seed, fill model, and result paths.
- `experiment-orchestrator`: Pipeline runner that executes backtest, sweep, and walk-forward evaluation for a candidate with configurable fill model presets and stress scenarios.
- `robustness-scorer`: Composite scoring system weighting OOS Sharpe, OOS degradation ratio, parameter stability CV, fee stress margin, regime stability, and DSR — replacing single-metric sweep ranking.
- `strategy-lifecycle`: Classification engine (rejected/revise/paper/promoted) with configurable promotion gates and CLI for batch evaluation.
- `candle-lookahead-guard`: `VisibleCandleRow` wrapper enforcing that adapters cannot read future intra-bar OHLCV values, closing the gap between book_synthesizer invariants and adapter access.

### Modified Capabilities

- `walkforward-robustness`: Fix broken `fee_stress_test` wiring, wire Holm-Bonferroni / BH FDR into runner, improve DSR trial/return estimation.
- `replay-fill-parity`: Align replay harness `DeskConfig.default_fill_model` to `latency_aware` for apples-to-apples comparison with backtest harness.

## Impact

- **Code**: New module `hbot/controllers/research/` (5-6 files). Targeted fixes in `hbot/controllers/backtesting/walkforward.py` and `hbot/controllers/backtesting/replay_harness.py`. New `VisibleCandleRow` in `hbot/controllers/backtesting/types.py` and guard in `hbot/controllers/backtesting/harness.py`.
- **Data**: New `hbot/data/research/` directory for experiment manifests (JSONL), candidate definitions (YAML), and generated reports (Markdown).
- **Dependencies**: No new external dependencies. Uses existing `dataclasses`, `json`, `hashlib`, `subprocess` (for git SHA).
- **Tests**: New test file `hbot/tests/controllers/test_research_lab.py`. Existing walk-forward and harness tests may need minor updates for `VisibleCandleRow`.
- **Config**: New YAML schema for `StrategyCandidate` definitions. Existing backtest/sweep/walk-forward configs unchanged.
