## ADDED Requirements

### Requirement: Pipeline execution

The system SHALL provide `ExperimentOrchestrator.evaluate(candidate: StrategyCandidate)` that executes the following pipeline in order: (1) single backtest with base config to verify the adapter runs without error, (2) parameter sweep using `SweepRunner` over the candidate's parameter space, (3) walk-forward evaluation using `WalkForwardRunner` with the sweep's best parameters as seed, (4) robustness scoring via `RobustnessScorer`, (5) experiment manifest creation in the registry, (6) Markdown report generation.

#### Scenario: Full pipeline success
- **WHEN** `evaluate(candidate)` is called with a valid candidate
- **THEN** all six steps execute in order, and an `EvaluationResult` is returned containing the `BacktestResult`, `SweepResult`, `WalkForwardResult`, robustness score, and report path

#### Scenario: Backtest failure stops pipeline
- **WHEN** step (1) raises an exception (e.g., adapter not found)
- **THEN** the pipeline stops, no manifest is written, and the exception is re-raised

### Requirement: Configurable pipeline

The system SHALL accept an optional `EvaluationConfig` dataclass controlling: `skip_sweep` (bool, default False), `skip_walkforward` (bool, default False), `fill_model_preset` (str, default "latency_aware"), `fee_stress_multipliers` (list of float, default [1.0, 1.5, 2.0, 3.0]), `output_dir` (str, default "hbot/data/research/reports").

#### Scenario: Skip walk-forward
- **WHEN** `evaluate(candidate, config=EvaluationConfig(skip_walkforward=True))` is called
- **THEN** steps (3) and (4) are skipped; robustness score is computed from available data only (sweep metrics)

### Requirement: Result persistence

The system SHALL save the full `BacktestResult` JSON to `{output_dir}/{candidate_name}/{run_id}.json` and the equity curve CSV alongside it.

#### Scenario: Result files created
- **WHEN** evaluation completes successfully
- **THEN** a JSON result file and a CSV equity file exist at the expected paths
