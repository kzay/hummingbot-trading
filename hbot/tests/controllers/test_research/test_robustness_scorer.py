"""Tests for RobustnessScorer — composite scoring with overfitting penalties."""
from __future__ import annotations

import pytest

from controllers.research.robustness_scorer import RobustnessScorer, ScoreBreakdown


class TestRobustnessScorer:
    def test_perfect_score_gives_pass(self):
        scorer = RobustnessScorer()
        metrics = {
            "mean_oos_sharpe": 2.5,
            "oos_degradation_ratio": 0.9,
            "oos_threshold": 0.5,
            "param_cv": {"spread": 0.05, "vol_window": 0.08},
            "fee_stress_sharpes": [1.8, 1.5, 1.2],
            "base_sharpe": 2.0,
            "regime_oos_degradation": {"trending": 2.3, "ranging": 1.8},
            "deflated_sharpe": 0.5,
        }
        bd = scorer.score(metrics)
        assert bd.recommendation == "pass"
        assert bd.total_score >= 0.55
        assert len(bd.components) == 6

    def test_zero_metrics_gives_reject(self):
        scorer = RobustnessScorer()
        metrics = {
            "mean_oos_sharpe": 0.0,
            "oos_degradation_ratio": 0.0,
            "oos_threshold": 0.5,
            "param_cv": {},
            "fee_stress_sharpes": [0.0],
            "base_sharpe": 0.0,
            "regime_oos_degradation": {},
            "deflated_sharpe": -0.5,
        }
        bd = scorer.score(metrics)
        assert bd.recommendation == "reject"
        assert bd.total_score < 0.35

    def test_mediocre_score_gives_revise(self):
        scorer = RobustnessScorer()
        metrics = {
            "mean_oos_sharpe": 1.0,
            "oos_degradation_ratio": 0.4,
            "oos_threshold": 0.5,
            "param_cv": {"spread": 0.4},
            "fee_stress_sharpes": [0.5],
            "base_sharpe": 1.2,
            "regime_oos_degradation": {"trending": 0.8},
            "deflated_sharpe": 0.01,
        }
        bd = scorer.score(metrics)
        assert bd.recommendation in ("revise", "pass")
        assert 0.0 <= bd.total_score <= 1.0

    def test_custom_weights_normalise(self):
        scorer = RobustnessScorer({"oos_sharpe": 5, "dsr_pass": 5})
        metrics = {
            "mean_oos_sharpe": 2.0,
            "deflated_sharpe": 0.3,
        }
        bd = scorer.score(metrics)
        assert 0.0 <= bd.total_score <= 1.0

    def test_score_clamped_to_unit_interval(self):
        scorer = RobustnessScorer()
        metrics = {
            "mean_oos_sharpe": 10.0,
            "oos_degradation_ratio": 2.0,
            "oos_threshold": 0.5,
            "param_cv": {},
            "fee_stress_sharpes": [8.0],
            "base_sharpe": 1.0,
            "regime_oos_degradation": {},
            "deflated_sharpe": 5.0,
        }
        bd = scorer.score(metrics)
        assert bd.total_score <= 1.0
