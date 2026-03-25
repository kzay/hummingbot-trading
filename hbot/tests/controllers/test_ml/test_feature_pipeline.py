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


class TestWilliamsRFeatures:
    def test_wr_columns_present(self, candles_1m):
        result = compute_price_features(candles_1m)
        for col in ["wr_1m_p14", "wr_1m_p50", "wr_divergence_1m_1h", "wr_extreme_1m"]:
            assert col in result.columns, f"Missing W%R column: {col}"
        # NaN columns for missing higher TFs should still be present
        for tf in ["5m", "15m", "1h", "4h"]:
            for p in [14, 50]:
                assert f"wr_{tf}_p{p}" in result.columns

    def test_wr_range(self, candles_1m):
        result = compute_price_features(candles_1m)
        valid = result["wr_1m_p14"].dropna()
        assert (valid >= 0.0).all(), "W%R must be >= 0"
        assert (valid <= 1.0).all(), "W%R must be <= 1"

    def test_wr_nan_for_missing_timeframes(self, candles_1m):
        result = compute_price_features(candles_1m, None, None, None)
        assert result["wr_5m_p14"].isna().all()
        assert result["wr_15m_p14"].isna().all()
        assert result["wr_1h_p14"].isna().all()

    def test_wr_extreme_is_binary(self, candles_1m):
        result = compute_price_features(candles_1m)
        valid = result["wr_extreme_1m"].dropna()
        assert valid.isin([0.0, 1.0]).all(), "wr_extreme_1m must be 0 or 1"

    def test_wr_warmup_nan(self, candles_1m):
        result = compute_price_features(candles_1m)
        # First 13 rows (period-1=13) of wr_1m_p14 should be NaN
        assert result["wr_1m_p14"].iloc[:13].isna().all()
        assert result["wr_1m_p14"].iloc[13:].notna().all()


class TestCrossTFConfluenceFeatures:
    """Tests for cross-TF confluence: vol_regime_agreement, wr_divergence."""

    @pytest.fixture
    def candles_5m(self, candles_1m) -> pd.DataFrame:
        df = candles_1m.copy()
        df["dt"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        df = df.set_index("dt")
        return df.resample("5min", label="left", closed="left").agg({
            "timestamp_ms": "first", "open": "first", "high": "max",
            "low": "min", "close": "last", "volume": "sum",
        }).dropna(subset=["timestamp_ms"]).reset_index(drop=True)

    def test_vol_regime_agreement_present(self, candles_1m, candles_5m):
        result = compute_price_features(candles_1m, candles_5m=candles_5m)
        assert "vol_regime_agreement" in result.columns

    def test_vol_regime_agreement_range(self, candles_1m, candles_5m):
        result = compute_price_features(candles_1m, candles_5m=candles_5m)
        valid = result["vol_regime_agreement"].dropna()
        if len(valid) > 0:
            assert (valid >= 0.0).all()
            assert (valid <= 1.0).all()

    def test_vol_regime_agreement_nan_when_no_higher_tf(self, candles_1m):
        result = compute_price_features(candles_1m)
        assert result["vol_regime_agreement"].isna().all()

    def test_wr_divergence_for_available_tfs(self, candles_1m, candles_5m):
        result = compute_price_features(candles_1m, candles_5m=candles_5m)
        assert "wr_divergence_1m_5m" in result.columns
        assert "wr_divergence_1m_1h" in result.columns

    def test_dynamic_rolling_window(self):
        import os
        original = os.environ.get("ML_ROLLING_WINDOW")
        original_tf = os.environ.get("ML_TIMEFRAMES")
        try:
            if "ML_ROLLING_WINDOW" in os.environ:
                del os.environ["ML_ROLLING_WINDOW"]
            os.environ["ML_TIMEFRAMES"] = "1m,5m,15m,1h"
            from services.ml_feature_service.pair_state import _compute_rolling_window
            assert _compute_rolling_window() == 7200

            os.environ["ML_TIMEFRAMES"] = "1m,5m,15m,1h,4h"
            assert _compute_rolling_window() == 28800

            os.environ["ML_ROLLING_WINDOW"] = "999"
            assert _compute_rolling_window() == 999
        finally:
            if original is None:
                os.environ.pop("ML_ROLLING_WINDOW", None)
            else:
                os.environ["ML_ROLLING_WINDOW"] = original
            if original_tf is None:
                os.environ.pop("ML_TIMEFRAMES", None)
            else:
                os.environ["ML_TIMEFRAMES"] = original_tf


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
