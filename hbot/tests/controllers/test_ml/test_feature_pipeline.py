"""Tests for the ML feature pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from controllers.ml.feature_pipeline import (
    compute_features,
    compute_microstructure_features,
    compute_price_features,
    compute_sentiment_features,
    compute_time_features,
    compute_volatility_features,
)


@pytest.fixture
def candles_1m() -> pd.DataFrame:
    np.random.seed(42)
    n = 500
    base_ts = 1_700_000_000_000
    close = 50000.0 + np.cumsum(np.random.normal(0, 50, n))
    high = close + np.abs(np.random.normal(0, 30, n))
    low = close - np.abs(np.random.normal(0, 30, n))
    opn = close + np.random.normal(0, 10, n)
    vol = np.abs(np.random.normal(100, 20, n))
    return pd.DataFrame({
        "timestamp_ms": [base_ts + i * 60_000 for i in range(n)],
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })


class TestComputeFeatures:
    def test_returns_dataframe_with_timestamp(self, candles_1m):
        result = compute_features(candles_1m)
        assert isinstance(result, pd.DataFrame)
        assert "timestamp_ms" in result.columns
        assert len(result) == len(candles_1m)

    def test_feature_count_in_range(self, candles_1m):
        result = compute_features(candles_1m)
        feature_cols = [c for c in result.columns if c != "timestamp_ms"]
        assert 30 <= len(feature_cols) <= 70

    def test_deterministic_output(self, candles_1m):
        r1 = compute_features(candles_1m)
        r2 = compute_features(candles_1m)
        pd.testing.assert_frame_equal(r1, r2)

    def test_no_strategy_imports(self):
        import controllers.ml.feature_pipeline as fp
        source = open(fp.__file__).read()
        import_lines = [
            line.strip() for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        joined = "\n".join(import_lines)
        for forbidden in ["controllers.bots", "epp_v2_4", "shared_runtime", "signal_service"]:
            assert forbidden not in joined, f"Feature pipeline imports forbidden module: {forbidden}"


class TestPriceFeatures:
    def test_columns_present(self, candles_1m):
        result = compute_price_features(candles_1m)
        expected = ["return_1m", "atr_1m", "close_in_range_1m", "body_ratio_1m",
                     "rsi_1m", "adx_1m", "bb_position_1m", "trend_alignment_1m_1h"]
        for col in expected:
            assert col in result.columns, f"Missing {col}"

    def test_nan_for_missing_timeframes(self, candles_1m):
        result = compute_price_features(candles_1m, None, None, None)
        assert result["return_5m"].isna().all()
        assert result["return_15m"].isna().all()
        assert result["return_1h"].isna().all()


class TestVolatilityFeatures:
    def test_columns_present(self, candles_1m):
        result = compute_volatility_features(candles_1m)
        expected = ["realized_vol_15m", "realized_vol_1h", "realized_vol_4h",
                     "parkinson_vol", "garman_klass_vol", "vol_of_vol",
                     "atr_pctl_24h", "range_expansion"]
        for col in expected:
            assert col in result.columns, f"Missing {col}"


class TestMicrostructureFeatures:
    def test_nan_when_no_trades(self, candles_1m):
        result = compute_microstructure_features(candles_1m, None)
        assert result["cvd"].isna().all()
        assert result["flow_imbalance"].isna().all()

    def test_with_trades(self, candles_1m):
        n_trades = 2000
        rng = np.random.default_rng(42)
        ts_lo = int(candles_1m["timestamp_ms"].iloc[0])
        ts_hi = int(candles_1m["timestamp_ms"].iloc[-1])
        trades = pd.DataFrame({
            "timestamp_ms": np.sort(rng.integers(ts_lo, ts_hi, n_trades)),
            "side": np.random.choice(["buy", "sell"], n_trades),
            "price": 50000.0 + np.random.normal(0, 50, n_trades),
            "size": np.abs(np.random.normal(0.1, 0.05, n_trades)),
        })
        result = compute_microstructure_features(candles_1m, trades)
        assert not result["trade_arrival_rate"].isna().all()


class TestSentimentFeatures:
    def test_nan_when_no_data(self, candles_1m):
        result = compute_sentiment_features(candles_1m, None, None, None, None)
        assert result["funding_rate"].isna().all()
        assert result["ls_ratio"].isna().all()
        assert result["basis"].isna().all()


class TestTimeFeatures:
    def test_cyclical_range(self, candles_1m):
        result = compute_time_features(candles_1m["timestamp_ms"])
        assert result["hour_sin"].between(-1, 1).all()
        assert result["hour_cos"].between(-1, 1).all()
        assert result["day_sin"].between(-1, 1).all()
        assert result["day_cos"].between(-1, 1).all()

    def test_minutes_since_funding(self, candles_1m):
        result = compute_time_features(candles_1m["timestamp_ms"])
        max_minutes = 8 * 60  # 8h cycle
        assert (result["minutes_since_funding"] >= 0).all()
        assert (result["minutes_since_funding"] <= max_minutes).all()
