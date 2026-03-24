"""Integration tests for the ML research pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm", reason="lightgbm required for research tests")
pytest.importorskip("joblib", reason="joblib required for research tests")

from controllers.ml import model_registry
from controllers.ml.feature_pipeline import compute_features
from controllers.ml.label_generator import compute_labels
from controllers.ml.research import (
    check_deployment_gates,
    compute_baseline,
    walk_forward_cv,
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
