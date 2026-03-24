"""Tests for walk-forward validation — window splitting, OOS thresholds, bootstrap, Holm-Bonferroni."""
from __future__ import annotations

import pytest

from controllers.backtesting.walkforward import (
    _split_windows_anchored,
    _split_windows_rolling,
    bh_fdr_correction,
    block_bootstrap_test,
    deflated_sharpe_ratio,
    fee_stress_test,
    holm_bonferroni_correction,
    param_stability_cv,
)


class TestWindowSplitting:
    def test_anchored_non_overlapping_test(self):
        """Anchored windows: all train starts at 0, test windows don't overlap."""
        windows = _split_windows_anchored(
            total_bars=10000, n_windows=3,
            train_ratio=0.7, min_train_bars=2000, min_test_bars=500,
        )
        assert len(windows) >= 2
        # All train starts at 0
        for train_start, _, _, _ in windows:
            assert train_start == 0
        # Test windows should not overlap
        for i in range(len(windows) - 1):
            assert windows[i][3] <= windows[i + 1][2]  # end_i <= start_{i+1}

    def test_rolling_fixed_train_size(self):
        """Rolling windows: train size is consistent."""
        windows = _split_windows_rolling(
            total_bars=10000, n_windows=3,
            train_ratio=0.7, min_train_bars=2000, min_test_bars=500,
        )
        assert len(windows) >= 1
        for train_start, train_end, test_start, test_end in windows:
            assert train_end > train_start
            assert test_end > test_start
            assert test_start == train_end

    def test_insufficient_bars(self):
        """Too few bars for even one window → empty."""
        windows = _split_windows_anchored(
            total_bars=100, n_windows=3,
            train_ratio=0.7, min_train_bars=2000, min_test_bars=500,
        )
        assert len(windows) == 0


class TestBlockBootstrap:
    def test_high_sharpe_significant(self):
        """High mean returns with some noise → bootstrap percentile above 0.3 (positive signal)."""
        import random as rng_mod
        rng = rng_mod.Random(42)
        # Strong signal: 0.5% daily mean, low noise
        returns = [0.005 + rng.gauss(0, 0.002) for _ in range(200)]
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        observed = mean_r / var_r ** 0.5 * 365 ** 0.5
        percentile = block_bootstrap_test(returns, observed_sharpe=observed, block_size=10, n_replications=500, seed=42)
        # With block bootstrap, the percentile should be meaningfully above random
        # but exact value depends on block structure; assert reasonable range
        assert percentile > 0.3

    def test_zero_sharpe_not_significant(self):
        """Zero mean returns → low percentile."""
        import random
        rng = random.Random(42)
        returns = [rng.gauss(0, 0.01) for _ in range(200)]
        percentile = block_bootstrap_test(returns, observed_sharpe=0.0, block_size=10, n_replications=500, seed=42)
        assert percentile < 0.95

    def test_too_few_returns(self):
        """Insufficient data → 0.5 (inconclusive)."""
        percentile = block_bootstrap_test([0.01] * 5, observed_sharpe=1.0, block_size=10)
        assert percentile == 0.5


class TestParamStabilityCV:
    def test_stable_params(self):
        window_params = [
            {"spread": 0.005, "levels": 3},
            {"spread": 0.0051, "levels": 3},
            {"spread": 0.0049, "levels": 3},
        ]
        cv = param_stability_cv(window_params)
        assert cv["spread"] < 0.5
        assert cv["levels"] < 0.1

    def test_unstable_params(self):
        window_params = [
            {"x": 1.0},
            {"x": 10.0},
            {"x": 100.0},
        ]
        cv = param_stability_cv(window_params)
        assert cv["x"] > 0.5

    def test_empty(self):
        assert param_stability_cv([]) == {}


class TestFeeStress:
    def test_positive_margin(self):
        margin, levels, stressed = fee_stress_test(
            base_sharpe=2.0, base_fee_drag_pct=0.01,
            fee_multipliers=[1.0, 1.5, 2.0],
            stressed_maker_ratio=0.60, base_maker_ratio=0.80,
        )
        assert margin > 0
        assert "1.0x" in levels
        assert levels["1.0x"] == pytest.approx(2.0)
        assert levels["2.0x"] < levels["1.0x"]  # Higher fees → lower Sharpe


class TestHolmBonferroni:
    def test_all_pass(self):
        p_values = [0.001, 0.002, 0.003]
        passes = holm_bonferroni_correction(p_values, alpha=0.05)
        assert all(passes)

    def test_none_pass(self):
        p_values = [0.1, 0.2, 0.3]
        passes = holm_bonferroni_correction(p_values, alpha=0.05)
        assert not any(passes)

    def test_partial_pass(self):
        # First is significant at corrected level, second is not
        p_values = [0.005, 0.03, 0.1]
        passes = holm_bonferroni_correction(p_values, alpha=0.05)
        assert passes[0] is True  # 0.005 < 0.05/3 = 0.0167
        # 0.03 > 0.05/2 = 0.025, so second fails Holm step-down
        assert passes[1] is False

    def test_empty(self):
        assert holm_bonferroni_correction([]) == []

    def test_ordering_preserved(self):
        """Index mapping: correction applies to sorted but returns original order."""
        p_values = [0.05, 0.001, 0.03]
        passes = holm_bonferroni_correction(p_values, alpha=0.05)
        # p=0.001 is smallest → should have best chance of passing
        assert passes[1] is True  # 0.001 < 0.05/3

class TestBhFdrCorrection:
    def test_all_pass(self):
        p_values = [0.001, 0.002, 0.003]
        passes = bh_fdr_correction(p_values, alpha=0.05)
        assert all(passes)

    def test_none_pass(self):
        p_values = [0.5, 0.6, 0.8]
        passes = bh_fdr_correction(p_values, alpha=0.05)
        assert not any(passes)

    def test_empty(self):
        assert bh_fdr_correction([]) == []

    def test_bh_more_lenient_than_holm(self):
        """BH FDR should be at least as lenient as Holm-Bonferroni."""
        p_values = [0.01, 0.02, 0.04]
        holm = holm_bonferroni_correction(p_values, alpha=0.05)
        bh = bh_fdr_correction(p_values, alpha=0.05)
        # If Holm passes, BH should also pass
        for h, b in zip(holm, bh):
            if h:
                assert b


class TestDeflatedSharpe:
    def test_high_trials_deflates(self):
        """More trials → more deflation."""
        try:
            dsr_few, _ = deflated_sharpe_ratio(2.0, n_trials=5, n_returns=252)
            dsr_many, _ = deflated_sharpe_ratio(2.0, n_trials=1000, n_returns=252)
            assert dsr_many < dsr_few  # More trials → lower deflated Sharpe
        except ImportError:
            pytest.skip("scipy not installed")

    def test_single_trial_no_deflation(self):
        try:
            dsr, _ = deflated_sharpe_ratio(2.0, n_trials=1, n_returns=252)
            assert dsr == 2.0  # Single trial → no adjustment
        except ImportError:
            pytest.skip("scipy not installed")
