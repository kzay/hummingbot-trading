"""Tests for live feature activation (microstructure + basis) and shadow models."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from services.ml_feature_service.pair_state import PairFeatureState


# ---------------------------------------------------------------------------
# Trade buffer tests
# ---------------------------------------------------------------------------
class TestTradeBuffer:
    def test_append_and_retrieve(self) -> None:
        state = PairFeatureState("BTC-USDT", "bitget")
        state.append_trade(50000.0, 0.1, 1000, "buy")
        state.append_trade(50010.0, 0.2, 2000, "sell")
        df = state.trades_df()
        assert df is not None
        assert len(df) == 2
        assert list(df.columns) == ["timestamp_ms", "price", "size", "side"]

    def test_empty_returns_none(self) -> None:
        state = PairFeatureState("BTC-USDT", "bitget")
        assert state.trades_df() is None

    def test_buffer_respects_maxlen(self) -> None:
        state = PairFeatureState("BTC-USDT", "bitget")
        for i in range(10000):
            state.append_trade(50000.0, 0.01, i * 100, "buy")
        from services.ml_feature_service.pair_state import TRADE_BUFFER_SIZE
        assert len(state._trades) <= TRADE_BUFFER_SIZE


# ---------------------------------------------------------------------------
# Mark/Index cache tests
# ---------------------------------------------------------------------------
class TestMarkIndexCache:
    def test_update_and_access(self) -> None:
        state = PairFeatureState("BTC-USDT", "bitget")
        mark = pd.DataFrame({"timestamp_ms": [1000], "close": [50000]})
        index = pd.DataFrame({"timestamp_ms": [1000], "close": [49900]})
        state.update_mark_index(mark, index)
        assert state._mark_candles is not None
        assert state._index_candles is not None
        assert state.mark_index_stale_s < 1.0

    def test_empty_df_not_stored(self) -> None:
        state = PairFeatureState("BTC-USDT", "bitget")
        state.update_mark_index(pd.DataFrame(), pd.DataFrame())
        assert state._mark_candles is None
        assert state._index_candles is None

    def test_none_preserves_existing(self) -> None:
        state = PairFeatureState("BTC-USDT", "bitget")
        mark = pd.DataFrame({"timestamp_ms": [1000], "close": [50000]})
        state.update_mark_index(mark, None)
        state.update_mark_index(None, None)
        assert state._mark_candles is not None
        assert state._index_candles is None


# ---------------------------------------------------------------------------
# Microstructure feature computation with trades
# ---------------------------------------------------------------------------
class TestMicrostructureLive:
    def test_features_computed_with_trades(self) -> None:
        from controllers.ml.feature_pipeline import compute_features

        n = 120
        ts = np.arange(n) * 60_000
        candles = pd.DataFrame({
            "timestamp_ms": ts,
            "open": np.full(n, 50000.0),
            "high": np.full(n, 50100.0),
            "low": np.full(n, 49900.0),
            "close": np.full(n, 50050.0),
            "volume": np.full(n, 10.0),
        })
        trades = pd.DataFrame({
            "timestamp_ms": np.repeat(ts[:10], 5),
            "price": np.random.uniform(49900, 50100, 50),
            "size": np.random.uniform(0.01, 1.0, 50),
            "side": np.random.choice(["buy", "sell"], 50),
        })
        df = compute_features(candles_1m=candles, trades=trades)
        assert "cvd" in df.columns
        assert "flow_imbalance" in df.columns
        assert "vwap_deviation" in df.columns

    def test_graceful_with_no_trades(self) -> None:
        from controllers.ml.feature_pipeline import compute_features

        n = 120
        candles = pd.DataFrame({
            "timestamp_ms": np.arange(n) * 60_000,
            "open": np.full(n, 50000.0),
            "high": np.full(n, 50100.0),
            "low": np.full(n, 49900.0),
            "close": np.full(n, 50050.0),
            "volume": np.full(n, 10.0),
        })
        df = compute_features(candles_1m=candles, trades=None)
        assert "cvd" in df.columns
        assert df["cvd"].isna().all()


# ---------------------------------------------------------------------------
# Basis feature computation with mark/index
# ---------------------------------------------------------------------------
class TestBasisLive:
    def test_basis_computed_with_mark_index(self) -> None:
        from controllers.ml.feature_pipeline import compute_features

        n = 120
        ts = np.arange(n) * 60_000
        candles = pd.DataFrame({
            "timestamp_ms": ts,
            "open": np.full(n, 50000.0),
            "high": np.full(n, 50100.0),
            "low": np.full(n, 49900.0),
            "close": np.full(n, 50050.0),
            "volume": np.full(n, 10.0),
        })
        mark = pd.DataFrame({
            "timestamp_ms": ts[-60:],
            "open": np.full(60, 50000.0),
            "high": np.full(60, 50100.0),
            "low": np.full(60, 49900.0),
            "close": np.full(60, 50060.0),
            "volume": np.full(60, 5.0),
        })
        index = pd.DataFrame({
            "timestamp_ms": ts[-60:],
            "open": np.full(60, 49990.0),
            "high": np.full(60, 50090.0),
            "low": np.full(60, 49890.0),
            "close": np.full(60, 50040.0),
            "volume": np.full(60, 5.0),
        })
        df = compute_features(candles_1m=candles, mark_candles_1m=mark, index_candles_1m=index)
        assert "basis" in df.columns
        assert "basis_momentum" in df.columns
        last = df.iloc[-1]
        assert pd.notna(last["basis"])

    def test_graceful_without_mark_index(self) -> None:
        from controllers.ml.feature_pipeline import compute_features

        n = 120
        candles = pd.DataFrame({
            "timestamp_ms": np.arange(n) * 60_000,
            "open": np.full(n, 50000.0),
            "high": np.full(n, 50100.0),
            "low": np.full(n, 49900.0),
            "close": np.full(n, 50050.0),
            "volume": np.full(n, 10.0),
        })
        df = compute_features(candles_1m=candles)
        assert "basis" in df.columns
        assert df["basis"].isna().all()


# ---------------------------------------------------------------------------
# Shadow model inference tests
# ---------------------------------------------------------------------------
class TestShadowInference:
    @staticmethod
    def _make_mock_model(pred_class: int = 1, proba: list[float] | None = None):
        model = MagicMock()
        model.predict.return_value = np.array([pred_class])
        model.predict_proba.return_value = np.array([proba or [0.3, 0.7]])
        model.classes_ = np.array([0, 1])
        return model

    def test_shadow_comparison_produced(self) -> None:
        from services.ml_feature_service.main import _run_inference

        features = pd.DataFrame({"f1": [1.0], "f2": [2.0], "timestamp_ms": [100]})
        active = {"regime": {"model": self._make_mock_model(1, [0.3, 0.7]), "metadata": {"feature_columns": ["f1", "f2"]}}}
        shadow = {"regime": {"model": self._make_mock_model(0, [0.6, 0.4]), "metadata": {"feature_columns": ["f1", "f2"]}}}

        preds, versions, comps = _run_inference(features, active, shadow)
        assert len(comps) == 1
        assert comps[0]["model_type"] == "regime"
        assert comps[0]["agreement"] is False

    def test_agreement_true_when_same(self) -> None:
        from services.ml_feature_service.main import _run_inference

        features = pd.DataFrame({"f1": [1.0], "timestamp_ms": [100]})
        m = self._make_mock_model(1, [0.3, 0.7])
        active = {"regime": {"model": m, "metadata": {"feature_columns": ["f1"]}}}
        shadow = {"regime": {"model": m, "metadata": {"feature_columns": ["f1"]}}}

        _, _, comps = _run_inference(features, active, shadow)
        assert comps[0]["agreement"] is True

    def test_no_shadow_no_comparisons(self) -> None:
        from services.ml_feature_service.main import _run_inference

        features = pd.DataFrame({"f1": [1.0], "timestamp_ms": [100]})
        active = {"regime": {"model": self._make_mock_model(), "metadata": {"feature_columns": ["f1"]}}}

        _, _, comps = _run_inference(features, active, None)
        assert comps == []

    def test_shadow_only_for_existing_active(self) -> None:
        from services.ml_feature_service.main import _run_inference

        features = pd.DataFrame({"f1": [1.0], "timestamp_ms": [100]})
        active = {}
        shadow = {"regime": {"model": self._make_mock_model(), "metadata": {"feature_columns": ["f1"]}}}

        _, _, comps = _run_inference(features, active, shadow)
        assert comps == []


# ---------------------------------------------------------------------------
# Event schema tests
# ---------------------------------------------------------------------------
class TestShadowComparisonSchema:
    def test_schema_valid(self) -> None:
        from platform_lib.contracts.event_schemas import MlShadowComparisonEvent

        event = MlShadowComparisonEvent(
            producer="test",
            exchange="bitget",
            trading_pair="BTC-USDT",
            model_type="regime",
            active_pred=1,
            shadow_pred=0,
            agreement=False,
            active_confidence=0.7,
            shadow_confidence=0.6,
            confidence_delta=-0.1,
        )
        assert event.event_type == "ml_shadow_comparison"
        d = event.model_dump()
        assert d["agreement"] is False
