"""Integration tests for the ML research pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

try:
    import lightgbm  # noqa: F401
except (ImportError, OSError):
    pytest.skip("lightgbm not available (missing native libs)", allow_module_level=True)
pytest.importorskip("joblib", reason="joblib required for research tests")

from controllers.ml import model_registry
from controllers.ml.feature_pipeline import compute_features
from controllers.ml.label_generator import compute_labels
from controllers.ml.research import (
    REGIME_LABEL_MAP,
    _LABEL_MAPS,
    _SEARCH_SPACES,
    check_deployment_gates,
    compute_baseline,
    compute_feature_importance_summary,
    purged_walk_forward_cv,
    run_hyperparameter_tuning,
    walk_forward_cv,
    write_feature_importance_report,
)


@pytest.fixture
def synthetic_dataset() -> pd.DataFrame:
    """5000-row synthetic dataset with features and labels."""
    np.random.seed(42)
    n = 5000
    base_ts = 1_700_000_000_000
    close = 50000.0 + np.cumsum(np.random.normal(0, 50, n))
    candles = pd.DataFrame({
        "timestamp_ms": [base_ts + i * 60_000 for i in range(n)],
        "open": close + np.random.normal(0, 10, n),
        "high": close + np.abs(np.random.normal(0, 30, n)),
        "low": close - np.abs(np.random.normal(0, 30, n)),
        "close": close,
        "volume": np.abs(np.random.normal(100, 20, n)),
    })

    features = compute_features(candles)
    labels = compute_labels(candles)
    return features.merge(labels, on="timestamp_ms", how="inner")


class TestWalkForwardCV:
    def test_produces_windows(self, synthetic_dataset):
        results = walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        assert len(results) > 0

    def test_metrics_are_numeric(self, synthetic_dataset):
        results = walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        for r in results:
            assert isinstance(r["metric_value"], float)
            assert r["metric_name"] == "accuracy"

    def test_regression_model_type(self, synthetic_dataset):
        results = walk_forward_cv(synthetic_dataset, "sizing", n_windows=3)
        for r in results:
            assert r["metric_name"] == "r_squared"


class TestDeploymentGates:
    def test_gates_return_booleans(self, synthetic_dataset):
        results = walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        baseline = compute_baseline(synthetic_dataset, "regime")
        ready, gates = check_deployment_gates(results, baseline, "regime")
        assert isinstance(ready, bool)
        assert len(gates) >= 2

    def test_failing_gate_returns_false(self):
        fake_results = [
            {"metric_value": 0.3, "top_10_features": [f"f{i}" for i in range(10)]}
            for _ in range(3)
        ]
        ready, gates = check_deployment_gates(fake_results, 0.4, "regime")
        assert not ready


class TestPurgedWalkForwardCV:
    """Tests for purged_walk_forward_cv() — embargo gaps, sample purging."""

    def test_fold_structure_with_embargo(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3, embargo_bars=60, purge=False,
        )
        assert len(results) > 0
        for r in results:
            assert r["embargo_bars"] == 60
            assert r["purged_count"] == 0

    def test_purging_removes_leaking_samples(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3, embargo_bars=60, purge=True,
        )
        assert len(results) > 0
        for r in results:
            assert r["purged_count"] >= 0

        results_no_purge = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3, embargo_bars=60, purge=False,
        )
        for rp, rnp in zip(results, results_no_purge, strict=True):
            assert rp["train_rows"] <= rnp["train_rows"]

    def test_embargo_gap_correctness(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3, embargo_bars=120, purge=True,
        )
        assert len(results) > 0
        assert results[0]["embargo_bars"] == 120

    def test_default_embargo(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3,
        )
        assert len(results) > 0
        assert results[0]["embargo_bars"] == 120  # 2 * 60

    def test_insufficient_data_raises(self):
        tiny = pd.DataFrame({
            "timestamp_ms": range(50),
            "feature_a": np.random.randn(50),
            "fwd_vol_bucket_15m": np.random.randint(0, 3, 50),
        })
        with pytest.raises(ValueError, match="Insufficient data"):
            purged_walk_forward_cv(tiny, "regime", n_windows=3)

    def test_unknown_model_type_raises(self, synthetic_dataset):
        with pytest.raises(ValueError, match="Unknown model_type"):
            purged_walk_forward_cv(synthetic_dataset, "unknown_type")

    def test_per_fold_detail_fields(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3,
        )
        for r in results:
            assert "train_rows" in r
            assert "test_rows" in r
            assert "embargo_bars" in r
            assert "purged_count" in r
            assert "metric_name" in r
            assert "metric_value" in r
            assert "feature_importances" in r
            assert isinstance(r["feature_importances"], dict)

    def test_feature_importances_populated(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "regime", n_windows=3,
        )
        for r in results:
            assert len(r["feature_importances"]) > 0
            assert all(isinstance(v, (int, float)) for v in r["feature_importances"].values())

    def test_legacy_walk_forward_cv_delegates(self, synthetic_dataset):
        results = walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        assert len(results) > 0
        assert results[0]["embargo_bars"] == 0
        assert results[0]["purged_count"] == 0

    def test_regression_model(self, synthetic_dataset):
        results = purged_walk_forward_cv(
            synthetic_dataset, "sizing", n_windows=3,
        )
        for r in results:
            assert r["metric_name"] == "r_squared"


class TestHyperparameterTuning:
    @pytest.fixture(autouse=True)
    def _skip_if_no_optuna(self):
        pytest.importorskip("optuna", reason="optuna required")

    def test_returns_best_params(self, synthetic_dataset):
        result = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=5, seed=42,
        )
        assert "best_params" in result
        assert "best_score" in result
        assert isinstance(result["best_params"], dict)
        assert result["n_trials"] == 5

    def test_best_params_from_search_space(self, synthetic_dataset):
        result = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=5, seed=42,
        )
        space = _SEARCH_SPACES["regime"]
        for key in space:
            assert key in result["best_params"]
            val = result["best_params"][key]
            lo, hi = space[key]
            assert lo <= val <= hi, f"{key}: {val} not in [{lo}, {hi}]"

    def test_search_space_persisted(self, synthetic_dataset):
        result = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=3, seed=42,
        )
        assert "search_space" in result
        assert "n_estimators" in result["search_space"]

    def test_reproducibility(self, synthetic_dataset):
        r1 = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=5, seed=99,
        )
        r2 = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=5, seed=99,
        )
        assert r1["best_params"] == r2["best_params"]

    def test_unknown_model_uses_default_space(self, synthetic_dataset):
        synthetic_dataset["label_unknown"] = np.random.choice([0, 1], len(synthetic_dataset))
        result = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=3, seed=42,
        )
        assert result["n_trials"] == 3

    def test_adverse_has_distinct_space(self):
        assert _SEARCH_SPACES["adverse"]["min_child_samples"][0] == 20

    def test_direction_maximize(self, synthetic_dataset):
        result = run_hyperparameter_tuning(
            synthetic_dataset, "regime", n_windows=3, n_trials=5, seed=42,
        )
        assert result["best_score"] > 0.0


class TestFeatureImportanceTracking:
    def test_summary_keys(self, synthetic_dataset):
        results = purged_walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        summary = compute_feature_importance_summary(results)
        assert "top_features" in summary
        assert "stability" in summary
        assert "aggregate_importances" in summary

    def test_top_features_bounded(self, synthetic_dataset):
        results = purged_walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        summary = compute_feature_importance_summary(results, top_k=5)
        assert len(summary["top_features"]) <= 5

    def test_stability_scores_range(self, synthetic_dataset):
        results = purged_walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        summary = compute_feature_importance_summary(results)
        for score in summary["stability"].values():
            assert 0.0 <= score <= 1.0

    def test_aggregate_sorted_descending(self, synthetic_dataset):
        results = purged_walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        summary = compute_feature_importance_summary(results, top_k=10)
        values = list(summary["aggregate_importances"].values())
        assert values == sorted(values, reverse=True)

    def test_empty_results(self):
        summary = compute_feature_importance_summary([])
        assert summary["top_features"] == []

    def test_report_written(self, synthetic_dataset, tmp_path):
        results = purged_walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        report_path = tmp_path / "report.json"
        returned = write_feature_importance_report(results, report_path)
        assert returned == report_path
        assert report_path.exists()
        import json
        data = json.loads(report_path.read_text())
        assert len(data) == len(results)
        assert "top_features" in data[0]
        assert "all_importances" in data[0]

    def test_stability_reflects_fold_presence(self, synthetic_dataset):
        results = purged_walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        summary = compute_feature_importance_summary(results, top_k=5)
        for feat in summary["top_features"]:
            assert summary["stability"][feat] > 0.0


class TestModelRegistry:
    def test_save_and_load(self, synthetic_dataset, tmp_path):
        results = walk_forward_cv(synthetic_dataset, "regime", n_windows=3)
        model = results[-1]["model"]
        metadata = {"exchange": "test", "pair": "BTC-USDT", "model_type": "regime"}

        path = model_registry.save_model(
            model, metadata,
            base_dir=tmp_path, exchange="test", pair="BTC-USDT", model_type="regime",
        )
        assert path.exists()

        loaded = model_registry.load_model(tmp_path, "test", "BTC-USDT", "regime")
        assert loaded is not None

        meta = model_registry.load_metadata(tmp_path, "test", "BTC-USDT", "regime")
        assert meta["pair"] == "BTC-USDT"

    def test_missing_model_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            model_registry.load_model(tmp_path, "test", "BTC-USDT", "regime")


class TestUnifiedTrainingPipeline:
    def test_adverse_model_type_supported(self, synthetic_dataset):
        synthetic_dataset["adverse_label"] = np.random.choice([0, 1], len(synthetic_dataset))
        results = purged_walk_forward_cv(synthetic_dataset, "adverse", n_windows=3)
        assert len(results) > 0
        assert results[0]["metric_name"] == "accuracy"

    def test_label_maps_exist(self):
        for mt in ("regime", "direction", "adverse"):
            assert mt in _LABEL_MAPS
            assert len(_LABEL_MAPS[mt]) >= 2

    def test_regime_label_map_matches_bucket_names(self):
        assert REGIME_LABEL_MAP[0] == "neutral_low_vol"
        assert REGIME_LABEL_MAP[2] == "up"

    def test_adverse_deployment_gate_stricter(self, synthetic_dataset):
        synthetic_dataset["adverse_label"] = np.random.choice([0, 1], len(synthetic_dataset))
        results = purged_walk_forward_cv(synthetic_dataset, "adverse", n_windows=3)
        _, gates = check_deployment_gates(results, 0.5, "adverse")
        assert any("adverse" in g.lower() for g in gates)

    def test_deployment_gate_adverse_threshold(self, synthetic_dataset):
        synthetic_dataset["adverse_label"] = np.random.choice([0, 1], len(synthetic_dataset))
        results = purged_walk_forward_cv(synthetic_dataset, "adverse", n_windows=3)
        _, gates = check_deployment_gates(results, 0.5, "adverse")
        assert any("0.60" in g for g in gates)
