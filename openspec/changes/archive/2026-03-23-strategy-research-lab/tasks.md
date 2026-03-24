## 1. Fix Existing Engine Gaps

- [ ] 1.1 Fix `walkforward.py` `fee_stress_test` call site: change keyword arguments to positional matching the function signature `(base_sharpe, base_fee_drag_pct, fee_multipliers, stressed_maker_ratio, base_maker_ratio)` and unpack the returned dict correctly into the `stressed_sharpes` list
- [ ] 1.2 Wire `holm_bonferroni_test()` and `bh_fdr_test()` calls into `WalkForwardRunner.run()` after OOS Sharpe computation; populate `WalkForwardResult.holm_bonferroni_pass` and `bh_fdr_pass`
- [ ] 1.3 Improve DSR inputs: use actual pooled OOS return count for `n_returns` and compute real skewness/kurtosis from the pooled return series instead of hardcoded defaults
- [ ] 1.4 Align `ReplayHarness._create_desk()` to set `DeskConfig.default_fill_model = "latency_aware"` by default; add optional `fill_model` field to replay config YAML

## 2. Candle Lookahead Guard

- [ ] 2.1 Add `VisibleCandleRow` class to `hbot/controllers/backtesting/types.py` that wraps `CandleRow` + `step_index`/`max_step` and returns `math.nan` for `high`/`low`/`close` when `step_index < max_step`
- [ ] 2.2 Add `allow_full_candle: bool = False` field to `BacktestConfig`
- [ ] 2.3 Update `BacktestHarness._run_impl` to wrap `CandleRow` in `VisibleCandleRow` before passing to `adapter.tick()` (unless `allow_full_candle=True`)

## 3. Research Module Foundation

- [ ] 3.1 Create `hbot/controllers/research/__init__.py` with `StrategyCandidate` dataclass, `StrategyLifecycle` enum, `from_yaml()`/`to_yaml()` methods
- [ ] 3.2 Create `hbot/controllers/research/hypothesis_registry.py` with `HypothesisRegistry` class: `record_experiment()` appends manifest to JSONL, `list_experiments()` reads and filters, `get_git_sha()` helper

## 4. Robustness Scorer

- [ ] 4.1 Create `hbot/controllers/research/robustness_scorer.py` with `RobustnessScorer` class, `ComponentScore` and `ScoreBreakdown` dataclasses, configurable weights, and recommendation thresholds (reject < 0.35, revise < 0.55, pass >= 0.55)

## 5. Experiment Orchestrator

- [ ] 5.1 Create `hbot/controllers/research/experiment_orchestrator.py` with `ExperimentOrchestrator` class and `EvaluationConfig` dataclass; implement 6-step pipeline (backtest → sweep → walk-forward → score → manifest → report)

## 6. Report Generator

- [ ] 6.1 Create `hbot/controllers/research/report_generator.py` with `ReportGenerator.generate()` producing a Markdown report with: candidate summary, backtest metrics, sweep top-N, walk-forward OOS table, robustness score breakdown, and lifecycle recommendation

## 7. Strategy Lifecycle Manager

- [ ] 7.1 Create `hbot/controllers/research/lifecycle_manager.py` with `LifecycleManager` class: `can_promote()` checks gates, `transition()` validates and records state changes, persistence to `hbot/data/research/lifecycle/{name}.json`

## 8. CLI Entry Point

- [ ] 8.1 Create `hbot/controllers/research/evaluate.py` as `__main__` entry point: `--candidate`, `--dry-run`, `--skip-sweep`, `--skip-walkforward`, `--output-dir` flags; prints score breakdown and recommendation to stdout

## 9. Tests

- [ ] 9.1 Create `hbot/tests/controllers/test_research_lab.py` with tests for: `StrategyCandidate` YAML round-trip, `VisibleCandleRow` masking, `RobustnessScorer` component calculation, `HypothesisRegistry` append/query, `LifecycleManager` transitions and gate checks
- [ ] 9.2 Verify existing walk-forward and harness tests still pass after fee_stress fix, Holm-BH wiring, and `VisibleCandleRow` (run `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration`)
