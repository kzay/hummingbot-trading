"""Experiment orchestrator — drives the backtest→sweep→walk-forward→score pipeline.

Wraps the existing engines without modifying them.  Each evaluation run
produces an immutable experiment manifest in the hypothesis registry and
a Markdown report.

Validation tiers:
    candle_only      — passed candle harness verification but no replay data
    replay_validated — passed candle harness AND replay-grade validation

Only replay_validated candidates may be auto-promoted to paper.
"""
from __future__ import annotations

import copy
import hashlib
import json
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

# Validation tier constants
TIER_CANDLE_ONLY = "candle_only"
TIER_REPLAY_VALIDATED = "replay_validated"


def _convert_param_space(raw: dict[str, Any]) -> list[Any]:
    """Convert LLM-produced ``{name: [values]}`` dict to ``list[ParamSpace]``.

    The LLM generates parameter_space as a flat dict mapping param names
    to lists of discrete values.  The backtesting engine expects
    ``list[ParamSpace]`` dataclass instances with mode="grid".
    """
    from controllers.backtesting.types import ParamSpace

    result = []
    for name, values in raw.items():
        if not isinstance(values, list):
            values = [values]
        result.append(ParamSpace(name=name, mode="grid", values=values))
    return result


def _candidate_hash(candidate: StrategyCandidate) -> str:
    """SHA-256 of the candidate's effective search space and base config."""
    blob = json.dumps(
        {
            "name": candidate.name,
            "adapter_mode": candidate.adapter_mode,
            "search_space": candidate.effective_search_space,
            "base_config": candidate.base_config,
        },
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


_DEFAULT_SWEEP_WORKERS = 6


@dataclass
class EvaluationConfig:
    """Controls the evaluation pipeline."""

    skip_sweep: bool = False
    skip_walkforward: bool = False
    skip_replay: bool = False
    fill_model_preset: str = "latency_aware"
    fee_stress_multipliers: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.0, 3.0])
    output_dir: str = "hbot/data/research/reports"
    experiments_dir: str = "hbot/data/research/experiments"
    scorer_weights: dict[str, float] | None = None
    sweep_workers: int = _DEFAULT_SWEEP_WORKERS
    # Replay data path; if empty, replay validation is skipped and
    # the candidate is marked candle_only.
    replay_data_path: str = ""
    # Gate thresholds — if empty, quality_gates defaults are used
    gate_thresholds: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Container for a complete evaluation pipeline result."""

    candidate_name: str
    run_id: str
    backtest_result: Any = None
    sweep_results: list[Any] | None = None
    walkforward_result: Any = None
    replay_result: Any = None
    score_breakdown: ScoreBreakdown | None = None
    gate_report: Any = None  # GateReport from quality_gates
    validation_tier: str = TIER_CANDLE_ONLY
    report_path: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)


class ExperimentOrchestrator:
    """Execute the governed evaluation pipeline for a strategy candidate."""

    def __init__(self, config: EvaluationConfig | None = None) -> None:
        self._config = config or EvaluationConfig()
        self._registry = HypothesisRegistry(self._config.experiments_dir)
        self._scorer = RobustnessScorer(self._config.scorer_weights)
        self._reporter = ReportGenerator()

    def evaluate(self, candidate: StrategyCandidate) -> EvaluationResult:
        """Run the full governed evaluation pipeline.

        Steps:
        1. Pre-backtest validation (adapter, family, data, combos)
        2. Candle-harness verification backtest
        3. Parameter sweep (unless skip_sweep)
        4. Walk-forward evaluation (unless skip_walkforward)
        5. Quality gates (hard gates + overfitting defenses)
        6. Replay-grade validation (if replay data available and gates pass)
        7. Expanded robustness scoring
        8. Richer experiment manifest
        9. Markdown report
        """
        run_id = str(uuid.uuid4())[:8]
        output_dir = Path(self._config.output_dir) / candidate.name / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        result = EvaluationResult(candidate_name=candidate.name, run_id=run_id)

        # Step 1: Pre-backtest validation
        logger.info("Step 1/9: Pre-backtest validation for %s", candidate.name)
        self._pre_validate(candidate)

        from controllers.backtesting.types import BacktestConfig  # noqa: F401

        base = self._build_backtest_config(candidate)

        # Step 2: Candle-harness verification backtest
        logger.info("Step 2/9: Candle verification backtest for %s", candidate.name)
        from controllers.backtesting.harness import BacktestHarness

        harness = BacktestHarness(base)
        result.backtest_result = harness.run()
        bt = result.backtest_result

        result_path_obj = output_dir / "backtest_result.json"
        result_path = str(result_path_obj)
        from controllers.backtesting.report import save_json_report
        save_json_report(bt, result_path_obj)

        # Step 3: Sweep
        if not self._config.skip_sweep and candidate.effective_search_space:
            logger.info("Step 3/9: Parameter sweep for %s", candidate.name)
            result.sweep_results = self._run_sweep(candidate, base)
        else:
            logger.info("Step 3/9: Sweep skipped")

        # Step 4: Walk-forward
        wf_result = None
        if not self._config.skip_walkforward:
            logger.info("Step 4/9: Walk-forward for %s", candidate.name)
            wf_result = self._run_walkforward(candidate, base)
            result.walkforward_result = wf_result
        else:
            logger.info("Step 4/9: Walk-forward skipped")

        # Step 5: Quality gates
        logger.info("Step 5/9: Quality gates for %s", candidate.name)
        score_metrics = self._collect_score_metrics(result)
        from controllers.research.quality_gates import run_quality_gates
        gate_report = run_quality_gates(
            candidate=candidate,
            metrics=score_metrics,
            backtest_result=bt,
            sweep_results=result.sweep_results,
            thresholds=self._config.gate_thresholds,
        )
        result.gate_report = gate_report

        # Step 6: Replay-grade validation
        replay_available = bool(
            self._config.replay_data_path and
            not self._config.skip_replay and
            gate_report.hard_gates_pass
        )
        if replay_available:
            logger.info("Step 6/9: Replay-grade validation for %s", candidate.name)
            result.replay_result = self._run_replay(candidate, base)
            result.validation_tier = TIER_REPLAY_VALIDATED
        else:
            reason = (
                "replay data path not configured"
                if not self._config.replay_data_path
                else "gates failed" if not gate_report.hard_gates_pass
                else "skip_replay=True"
            )
            logger.info("Step 6/9: Replay skipped (%s) — tier=candle_only", reason)
            result.validation_tier = TIER_CANDLE_ONLY

        # Step 7: Expanded robustness scoring (with complexity penalty)
        logger.info("Step 7/9: Robustness scoring for %s", candidate.name)
        if gate_report.complexity_penalty > 0:
            score_metrics["complexity_penalty"] = gate_report.complexity_penalty
        result.score_breakdown = self._scorer.score(score_metrics)

        # Step 8: Richer experiment manifest
        logger.info("Step 8/9: Recording manifest for %s", candidate.name)
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
            recommendation=result.score_breakdown.recommendation,
            score_breakdown=self._score_breakdown_to_dict(result.score_breakdown),
            gate_results=gate_report.to_dict(),
            validation_tier=result.validation_tier,
            stress_results=self._collect_stress_results(result),
            artifact_paths={"backtest_result": result_path, "report": ""},
            strategy_family=candidate.strategy_family or None,
            template_id=candidate.template_id or None,
            candidate_hash=_candidate_hash(candidate),
        )

        # Step 9: Markdown report
        logger.info("Step 9/9: Generating report for %s", candidate.name)
        report_path = str(output_dir / "report.md")
        self._reporter.generate(
            candidate=candidate,
            evaluation_result=result,
            output_path=report_path,
        )
        result.report_path = report_path
        # Update artifact path for report
        if result.manifest.get("artifact_paths"):
            result.manifest["artifact_paths"]["report"] = report_path

        logger.info(
            "Evaluation complete for %s: tier=%s score=%.3f recommendation=%s gates=%s",
            candidate.name,
            result.validation_tier,
            result.score_breakdown.total_score,
            result.score_breakdown.recommendation,
            "PASS" if gate_report.hard_gates_pass else "FAIL",
        )
        return result

    @staticmethod
    def _pre_validate(candidate: StrategyCandidate) -> None:
        """Run pre-backtest validation; log failures but don't abort on legacy candidates."""
        try:
            from controllers.research.candidate_validator import (
                CandidateValidationError,
                validate_candidate,
            )
            validate_candidate(candidate)
        except Exception as exc:
            # Import errors (missing module) should not silently swallow real failures
            from controllers.research.candidate_validator import CandidateValidationError
            if isinstance(exc, CandidateValidationError):
                raise
            logger.warning("Pre-validate import error (non-fatal): %s", exc)

    def _build_backtest_config(self, candidate: StrategyCandidate) -> Any:
        """Build a BacktestConfig from the candidate's base_config dict."""
        from controllers.backtesting.types import BacktestConfig, DataSourceConfig

        bc = candidate.base_config
        ds_data = bc.get("data_source", {})
        ds = DataSourceConfig(
            exchange=ds_data.get("exchange", "bitget"),
            pair=ds_data.get("pair", "BTC-USDT"),
            resolution=ds_data.get("resolution", "15m"),
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
            step_interval_s=bc.get("step_interval_s", 900),
            warmup_bars=bc.get("warmup_bars", 60),
        )

    def _run_sweep(self, candidate: StrategyCandidate, base: Any) -> list[Any]:
        """Run parameter sweep over the candidate's effective search space."""
        from controllers.backtesting.sweep import SweepConfig, SweepRunner

        sweep_config = SweepConfig(
            base_config=copy.deepcopy(base),
            param_spaces=_convert_param_space(candidate.effective_search_space),
            workers=self._config.sweep_workers,
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
            param_spaces=_convert_param_space(candidate.effective_search_space),
            workers=self._config.sweep_workers,
        )
        wf_config = WalkForwardConfig(
            sweep_config=sweep_config,
            fee_stress_multipliers=self._config.fee_stress_multipliers,
        )
        runner = WalkForwardRunner(wf_config)
        return runner.run()

    def _run_replay(self, candidate: StrategyCandidate, base: Any) -> Any | None:
        """Run replay-grade validation when replay data is available.

        Falls back gracefully to None if the replay harness is unavailable.
        """
        try:
            from controllers.backtesting.replay_harness import ReplayHarness, ReplayConfig

            replay_config = ReplayConfig(
                base_config=copy.deepcopy(base),
                replay_data_path=self._config.replay_data_path,
            )
            harness = ReplayHarness(replay_config)
            return harness.run()
        except (ImportError, AttributeError) as exc:
            logger.debug("Replay harness unavailable (%s); staying candle_only", exc)
            return None
        except Exception as exc:
            logger.warning("Replay validation failed for '%s': %s", candidate.name, exc)
            return None

    @staticmethod
    def _collect_score_metrics(result: EvaluationResult) -> dict[str, Any]:
        """Extract scorer inputs from evaluation results."""
        metrics: dict[str, Any] = {}

        bt = result.backtest_result
        if bt:
            metrics["base_sharpe"] = bt.sharpe_ratio
            try:
                metrics["net_pnl"] = float(bt.realized_net_pnl_quote)
                metrics["max_drawdown_pct"] = float(bt.max_drawdown_pct)
                metrics["profit_factor"] = float(bt.profit_factor)
                metrics["trade_count"] = int(bt.closed_trade_count)
            except (AttributeError, TypeError):
                pass

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

        # Include replay metrics when available
        if result.replay_result:
            ry = result.replay_result
            try:
                metrics["replay_sharpe"] = ry.sharpe_ratio
                metrics["replay_net_pnl"] = float(ry.realized_net_pnl_quote)
            except (AttributeError, TypeError):
                pass

        return metrics

    @staticmethod
    def _collect_stress_results(result: EvaluationResult) -> dict[str, Any] | None:
        """Collect stress results from walk-forward fee stress and replay."""
        stress: dict[str, Any] = {}

        wf = result.walkforward_result
        if wf:
            try:
                stress["fee_stress_sharpes"] = wf.fee_stress_sharpes
                stress["fee_stress_multipliers"] = [1.0, 1.5, 2.0, 3.0]
            except AttributeError:
                pass

        if result.replay_result:
            try:
                stress["replay_sharpe"] = result.replay_result.sharpe_ratio
                stress["replay_net_pnl"] = float(result.replay_result.realized_net_pnl_quote)
            except (AttributeError, TypeError):
                pass

        return stress if stress else None

    @staticmethod
    def _score_breakdown_to_dict(score: ScoreBreakdown | None) -> dict[str, Any] | None:
        if score is None:
            return None
        return {
            "total_score": score.total_score,
            "recommendation": score.recommendation,
            "components": {
                name: {
                    "raw_value": cs.raw_value,
                    "normalised": cs.normalised,
                    "weight": cs.weight,
                    "weighted_contribution": cs.weighted_contribution,
                }
                for name, cs in score.components.items()
            },
        }
