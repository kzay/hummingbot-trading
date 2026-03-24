"""Tests for the ML label generator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from controllers.ml.label_generator import compute_labels


@pytest.fixture
def trending_candles() -> pd.DataFrame:
    """100 bars with a clear uptrend."""
    n = 100
    base = 50000.0
    close = np.array([base + i * 10 for i in range(n)])
    return pd.DataFrame({
        "timestamp_ms": [1_700_000_000_000 + i * 60_000 for i in range(n)],
        "open": close - 5,
        "high": close + 20,
        "low": close - 10,
        "close": close,
        "volume": np.full(n, 100.0),
    })


@pytest.fixture
def random_candles() -> pd.DataFrame:
    np.random.seed(42)
    n = 2000
    close = 50000.0 + np.cumsum(np.random.normal(0, 50, n))
    return pd.DataFrame({
        "timestamp_ms": [1_700_000_000_000 + i * 60_000 for i in range(n)],
        "open": close + np.random.normal(0, 10, n),
        "high": close + np.abs(np.random.normal(0, 30, n)),
        "low": close - np.abs(np.random.normal(0, 30, n)),
        "close": close,
        "volume": np.abs(np.random.normal(100, 20, n)),
    })


class TestForwardReturns:
    def test_correct_computation(self, trending_candles):
        result = compute_labels(trending_candles, horizons=[5])
        fwd_5 = result["fwd_return_5m"].values
        close = trending_candles["close"].values
        for i in range(len(close) - 5):
            expected = (close[i + 5] - close[i]) / close[i]
            assert abs(fwd_5[i] - expected) < 1e-10

    def test_trailing_nan(self, trending_candles):
        result = compute_labels(trending_candles, horizons=[5])
        assert np.isnan(result["fwd_return_5m"].values[-1])
        assert np.isnan(result["fwd_return_5m"].values[-5])
        assert not np.isnan(result["fwd_return_5m"].values[0])

    def test_sign_positive_in_uptrend(self, trending_candles):
        result = compute_labels(trending_candles, horizons=[5])
        signs = result["fwd_return_sign_5m"].values
        valid = signs[~np.isnan(signs)]
        assert (valid == 1).all()


class TestForwardVolatility:
    def test_positive_values(self, random_candles):
        result = compute_labels(random_candles, horizons=[15])
        vol = result["fwd_vol_15m"].values
        valid = vol[~np.isnan(vol)]
        assert (valid >= 0).all()


class TestMAEMFE:
    def test_mfe_large_in_uptrend_long(self, trending_candles):
        result = compute_labels(trending_candles, horizons=[15])
        mfe_long = result["fwd_mfe_long_15m"].values
        mae_long = result["fwd_mae_long_15m"].values
        valid_mfe = mfe_long[~np.isnan(mfe_long)]
        valid_mae = mae_long[~np.isnan(mae_long)]
        assert np.mean(valid_mfe) > np.mean(valid_mae)

    def test_trailing_nan(self, trending_candles):
        result = compute_labels(trending_candles, horizons=[15])
        assert np.isnan(result["fwd_mae_long_15m"].values[-1])


class TestTradability:
    def test_positive_values(self, random_candles):
        result = compute_labels(random_candles, horizons=[15])
        trad = result["tradability_long_15m"].values
        valid = trad[~np.isnan(trad)]
        assert (valid >= 0).all()

    def test_high_in_uptrend(self, trending_candles):
        result = compute_labels(trending_candles, horizons=[5])
        trad = result["tradability_long_5m"].values
        valid = trad[~np.isnan(trad)]
        assert np.mean(valid) > 1.0


class TestBuckets:
    def test_bucket_range(self, random_candles):
        result = compute_labels(random_candles, horizons=[15])
        buckets = result["fwd_return_bucket_15m"].values
        valid = buckets[~np.isnan(buckets)]
        assert valid.min() >= 0
        assert valid.max() <= 4

    def test_vol_bucket_range(self, random_candles):
        result = compute_labels(random_candles, horizons=[15])
        buckets = result["fwd_vol_bucket_15m"].values
        valid = buckets[~np.isnan(buckets)]
        assert valid.min() >= 0
        assert valid.max() <= 3


class TestNoStrategyDependency:
    def test_no_strategy_imports(self):
        import controllers.ml.label_generator as lg
        source = open(lg.__file__).read()
        import_lines = [
            line.strip() for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        joined = "\n".join(import_lines)
        for forbidden in ["controllers.bots", "regime_detector", "price_buffer", "services/"]:
            assert forbidden not in joined
