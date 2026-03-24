"""Experiment orchestrator — drives the backtest→sweep→walk-forward→score pipeline.

Wraps the existing engines without modifying them.  Each evaluation run
produces an immutable experiment manifest in the hypothesis registry and
a Markdown report.
"""
from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from controllers.research import StrategyCandidate
from controllers.research.hypothesis_registry import HypothesisRegistry
from controllers.research.report_generator import ReportGenerator
from controllers.research.robustness_scorer import RobustnessScorer, ScoreBreakdown

logger = logging.getLogger(__name__)


@dataclass
class EvaluationConfig:
    """Controls the evaluation pipeline."""

    skip_sweep: bool = False
    skip_walkforward: bool = False
    fill_model_preset: str = "latency_aware"
    fee_stress_multipliers: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0])
    output_dir: str = "hbot/data/research/reports"
    experiments_dir: str = "hbot/data/research/experiments"
    scorer_weights: dict[str, float] | None = None


@dataclass
class EvaluationResult:
    """Container for a complete evaluation pipeline result."""

    candidate_name: str
    run_id: str
    backtest_result: Any = None
    sweep_results: list[Any] | None = None
    walkforward_result: Any = None
    score_breakdown: ScoreBreakdown | None = None
    report_path: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)


class ExperimentOrchestrator:
    """Execute the 6-step evaluation pipeline for a strategy candidate."""

    def __init__(self, config: EvaluationConfig | None = None) -> None:
        self._config = config or EvaluationConfig()
        self._registry = HypothesisRegistry(self._config.experiments_dir)
        self._scorer = RobustnessScorer(self._config.scorer_weights)
        self._reporter = ReportGenerator()

    def evaluate(self, candidate: StrategyCandidate) -> EvaluationResult:
        """Run the full evaluation pipeline.

        Steps:
        1. Single backtest to verify adapter runs
        2. Parameter sweep (unless skip_sweep)
        3. Walk-forward evaluation (unless skip_walkforward)
        4. Robustness scoring
        5. Experiment manifest creation
        6. Markdown report generation
        """
        run_id = str(uuid.uuid4())[:8]
        output_dir = Path(self._config.output_dir) / candidate.name / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        result = EvaluationResult(candidate_name=candidate.name, run_id=run_id)

        from controllers.backtesting.types import BacktestConfig

        base = self._build_backtest_config(candidate)

        # Step 1: Verification backtest
        logger.info("Step 1/6: Verification backtest for %s", candidate.name)
        from controllers.backtesting.harness import BacktestHarness

        harness = BacktestHarness(base)
        result.backtest_result = harness.run()
        bt = result.backtest_result

        # Save result
        result_path = str(output_dir / "backtest_result.json")
        from controllers.backtesting.report import save_result_json
        save_result_json(bt, result_path)

        # Step 2: Sweep
        if not self._config.skip_sweep and candidate.parameter_space:
            logger.info("Step 2/6: Parameter sweep for %s", candidate.name)
            result.sweep_results = self._run_sweep(candidate, base)
        else:
            logger.info("Step 2/6: Sweep skipped")

        # Step 3: Walk-forward
        wf_result = None
        if not self._config.skip_walkforward:
            logger.info("Step 3/6: Walk-forward for %s", candidate.name)
            wf_result = self._run_walkforward(candidate, base)
            result.walkforward_result = wf_result
        else:
            logger.info("Step 3/6: Walk-forward skipped")

        # Step 4: Robustness scoring
        logger.info("Step 4/6: Robustness scoring for %s", candidate.name)
        score_metrics = self._collect_score_metrics(result)
        result.score_breakdown = self._scorer.score(score_metrics)

        # Step 5: Experiment manifest
        logger.info("Step 5/6: Recording manifest for %s", candidate.name)
        data_window = (
            base.data_source.start_date or "unknown",
            base.data_source.end_date or "unknown",
        )
        result.manifest = self._registry.record_experiment(
            candidate_name=candidate.name,
            config=candidate.base_config,
            data_window=data_window,
            seed=base.seed,
            fill_model=base.fill_model,
            result_path=result_path,
            robustness_score=result.score_breakdown.total_score,
        )

        # Step 6: Report
        logger.info("Step 6/6: Generating report for %s", candidate.name)
        report_path = str(output_dir / "report.md")
        self._reporter.generate(
            candidate=candidate,
            evaluation_result=result,
            output_path=report_path,
        )
        result.report_path = report_path

        logger.info(
            "Evaluation complete for %s: score=%.3f recommendation=%s",
            candidate.name,
            result.score_breakdown.total_score,
            result.score_breakdown.recommendation,
        )
        return result

    def _build_backtest_config(self, candidate: StrategyCandidate) -> Any:
        """Build a BacktestConfig from the candidate's base_config dict."""
        from controllers.backtesting.types import BacktestConfig, DataSourceConfig

        bc = candidate.base_config
        ds_data = bc.get("data_source", {})
        ds = DataSourceConfig(
            exchange=ds_data.get("exchange", "bitget"),
            pair=ds_data.get("pair", "BTC-USDT"),
            resolution=ds_data.get("resolution", "1m"),
            start_date=ds_data.get("start_date", ""),
            end_date=ds_data.get("end_date", ""),
            instrument_type=ds_data.get("instrument_type", "perp"),
            data_path=ds_data.get("data_path", ""),
            catalog_dir=ds_data.get("catalog_dir", "data/historical"),
        )

        from decimal import Decimal
        return BacktestConfig(
            strategy_class=bc.get("strategy_class", ""),
            strategy_config=bc.get("strategy_config", {}),
            data_source=ds,
            initial_equity=Decimal(str(bc.get("initial_equity", "500"))),
            fill_model=self._config.fill_model_preset,
            seed=bc.get("seed", 42),
            leverage=bc.get("leverage", 1),
            step_interval_s=bc.get("step_interval_s", 60),
            warmup_bars=bc.get("warmup_bars", 60),
        )

    def _run_sweep(self, candidate: StrategyCandidate, base: Any) -> list[Any]:
        """Run parameter sweep over the candidate's parameter space."""
        from controllers.backtesting.sweep import SweepConfig, SweepRunner

        sweep_config = SweepConfig(
            base_config=copy.deepcopy(base),
            param_spaces=candidate.parameter_space,
        )
        runner = SweepRunner(sweep_config)
        return runner.run()

    def _run_walkforward(self, candidate: StrategyCandidate, base: Any) -> Any:
        """Run walk-forward evaluation."""
        from controllers.backtesting.sweep import SweepConfig
        from controllers.backtesting.types import WalkForwardConfig
        from controllers.backtesting.walkforward import WalkForwardRunner

        sweep_config = SweepConfig(
            base_config=copy.deepcopy(base),
            param_spaces=candidate.parameter_space,
        )
        wf_config = WalkForwardConfig(
            sweep_config=sweep_config,
            fee_stress_multipliers=self._config.fee_stress_multipliers,
        )
        runner = WalkForwardRunner(wf_config)
        return runner.run()

    @staticmethod
    def _collect_score_metrics(result: EvaluationResult) -> dict[str, Any]:
        """Extract scorer inputs from evaluation results."""
        metrics: dict[str, Any] = {}

        bt = result.backtest_result
        if bt:
            metrics["base_sharpe"] = bt.sharpe_ratio

        wf = result.walkforward_result
        if wf:
            metrics["mean_oos_sharpe"] = wf.mean_oos_sharpe
            metrics["oos_degradation_ratio"] = wf.oos_degradation_ratio
            metrics["oos_threshold"] = wf.oos_threshold
            metrics["param_cv"] = wf.param_cv
            metrics["fee_stress_sharpes"] = wf.fee_stress_sharpes or None
            metrics["regime_oos_degradation"] = wf.regime_oos_degradation
            metrics["deflated_sharpe"] = wf.deflated_sharpe
        elif bt:
            metrics["mean_oos_sharpe"] = bt.sharpe_ratio
            metrics["oos_degradation_ratio"] = 1.0
            metrics["oos_threshold"] = 0.5
            metrics["deflated_sharpe"] = 0.0

        return metrics
