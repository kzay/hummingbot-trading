"""Tests for ExperimentOrchestrator pipeline wiring and metric extraction."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from controllers.research import StrategyCandidate
from controllers.research.experiment_orchestrator import (
    EvaluationConfig,
    EvaluationResult,
    ExperimentOrchestrator,
)
from controllers.research.robustness_scorer import ComponentScore, ScoreBreakdown


class TestCollectScoreMetrics:
    def test_uses_walkforward_metrics_when_available(self) -> None:
        result = EvaluationResult(candidate_name="alpha", run_id="r1")
        result.backtest_result = SimpleNamespace(sharpe_ratio=1.1)
        result.walkforward_result = SimpleNamespace(
            mean_oos_sharpe=0.9,
            oos_degradation_ratio=0.7,
            oos_threshold=0.5,
            param_cv={"spread": 0.2},
            fee_stress_sharpes=[],
            regime_oos_degradation={"trending": 0.8},
            deflated_sharpe=0.05,
        )

        metrics = ExperimentOrchestrator._collect_score_metrics(result)

        assert metrics["base_sharpe"] == 1.1
        assert metrics["mean_oos_sharpe"] == 0.9
        assert metrics["oos_degradation_ratio"] == 0.7
        assert metrics["oos_threshold"] == 0.5
        assert metrics["param_cv"] == {"spread": 0.2}
        assert metrics["fee_stress_sharpes"] is None
        assert metrics["regime_oos_degradation"] == {"trending": 0.8}
        assert metrics["deflated_sharpe"] == 0.05

    def test_falls_back_to_backtest_defaults_without_walkforward(self) -> None:
        result = EvaluationResult(candidate_name="alpha", run_id="r1")
        result.backtest_result = SimpleNamespace(sharpe_ratio=1.25)

        metrics = ExperimentOrchestrator._collect_score_metrics(result)

        assert metrics == {
            "base_sharpe": 1.25,
            "mean_oos_sharpe": 1.25,
            "oos_degradation_ratio": 1.0,
            "oos_threshold": 0.5,
            "deflated_sharpe": 0.0,
        }


class TestExperimentOrchestrator:
    def _make_candidate(self) -> StrategyCandidate:
        return StrategyCandidate(
            name="test-candidate",
            hypothesis="Test hypothesis",
            adapter_mode="market_making",
            parameter_space={"spread": [1, 2]},
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "x.y.Strategy"},
        )

    def _make_score_breakdown(self) -> ScoreBreakdown:
        return ScoreBreakdown(
            total_score=0.64,
            components={
                "oos_sharpe": ComponentScore(1.2, 0.4, 0.25, 0.1),
                "oos_degradation": ComponentScore(0.8, 0.8, 0.2, 0.16),
            },
            recommendation="pass",
        )

    @patch("controllers.backtesting.report.save_json_report")
    @patch("controllers.backtesting.harness.BacktestHarness")
    def test_evaluate_runs_pipeline_and_records_outputs(
        self,
        mock_harness_cls: MagicMock,
        mock_save_json_report: MagicMock,
        tmp_path: Path,
    ) -> None:
        config = EvaluationConfig(
            output_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
        )
        orchestrator = ExperimentOrchestrator(config)
        candidate = self._make_candidate()

        base_config = SimpleNamespace(
            data_source=SimpleNamespace(start_date="2025-01-01", end_date="2025-02-01"),
            seed=42,
            fill_model="latency_aware",
        )
        backtest_result = SimpleNamespace(sharpe_ratio=1.3)
        walkforward_result = SimpleNamespace(
            mean_oos_sharpe=1.1,
            oos_degradation_ratio=0.75,
            oos_threshold=0.5,
            param_cv={"spread": 0.1},
            fee_stress_sharpes=[0.9, 0.8],
            regime_oos_degradation={"trending": 1.0},
            deflated_sharpe=0.2,
        )

        mock_harness_cls.return_value.run.return_value = backtest_result

        orchestrator._build_backtest_config = MagicMock(return_value=base_config)
        orchestrator._run_sweep = MagicMock(return_value=[{"spread": 1}])
        orchestrator._run_walkforward = MagicMock(return_value=walkforward_result)
        orchestrator._scorer.score = MagicMock(return_value=self._make_score_breakdown())
        orchestrator._registry.record_experiment = MagicMock(return_value={"manifest": True})
        orchestrator._reporter.generate = MagicMock()

        result = orchestrator.evaluate(candidate)

        assert result.candidate_name == "test-candidate"
        assert result.backtest_result is backtest_result
        assert result.sweep_results == [{"spread": 1}]
        assert result.walkforward_result is walkforward_result
        assert result.score_breakdown.total_score == 0.64
        assert result.manifest == {"manifest": True}
        assert result.report_path.endswith("report.md")

        mock_save_json_report.assert_called_once()
        orchestrator._run_sweep.assert_called_once_with(candidate, base_config)
        orchestrator._run_walkforward.assert_called_once_with(candidate, base_config)
        orchestrator._registry.record_experiment.assert_called_once()
        orchestrator._reporter.generate.assert_called_once()

    @patch("controllers.backtesting.report.save_json_report")
    @patch("controllers.backtesting.harness.BacktestHarness")
    def test_evaluate_respects_skip_flags_and_empty_parameter_space(
        self,
        mock_harness_cls: MagicMock,
        mock_save_json_report: MagicMock,
        tmp_path: Path,
    ) -> None:
        config = EvaluationConfig(
            skip_sweep=True,
            skip_walkforward=True,
            output_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
        )
        orchestrator = ExperimentOrchestrator(config)
        candidate = self._make_candidate()
        candidate.parameter_space = {}

        base_config = SimpleNamespace(
            data_source=SimpleNamespace(start_date="", end_date=""),
            seed=7,
            fill_model="latency_aware",
        )
        backtest_result = SimpleNamespace(sharpe_ratio=0.9)

        mock_harness_cls.return_value.run.return_value = backtest_result

        orchestrator._build_backtest_config = MagicMock(return_value=base_config)
        orchestrator._run_sweep = MagicMock()
        orchestrator._run_walkforward = MagicMock()
        orchestrator._scorer.score = MagicMock(return_value=self._make_score_breakdown())
        orchestrator._registry.record_experiment = MagicMock(return_value={"manifest": True})
        orchestrator._reporter.generate = MagicMock()

        result = orchestrator.evaluate(candidate)

        assert result.sweep_results is None
        assert result.walkforward_result is None
        orchestrator._run_sweep.assert_not_called()
        orchestrator._run_walkforward.assert_not_called()
        mock_save_json_report.assert_called_once()

    def test_build_backtest_config_defaults_to_15m_and_900(self) -> None:
        orchestrator = ExperimentOrchestrator()
        candidate = self._make_candidate()

        config = orchestrator._build_backtest_config(candidate)

        assert config.data_source.resolution == "15m"
        assert config.step_interval_s == 900

    def test_build_backtest_config_respects_candidate_overrides(self) -> None:
        orchestrator = ExperimentOrchestrator()
        candidate = self._make_candidate()
        candidate.base_config = {
            "strategy_class": "x.y.Strategy",
            "data_source": {
                "exchange": "bitget",
                "pair": "BTC-USDT",
                "resolution": "1h",
                "instrument_type": "perp",
            },
            "step_interval_s": 3600,
        }

        config = orchestrator._build_backtest_config(candidate)

        assert config.data_source.resolution == "1h"
        assert config.step_interval_s == 3600
