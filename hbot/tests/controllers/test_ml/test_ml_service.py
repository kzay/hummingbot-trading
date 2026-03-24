"""Tests for ML feature service components — bar builder, pair state."""
from __future__ import annotations

import numpy as np
import pandas as pd

from services.ml_feature_service.bar_builder import Bar, BarBuilder
from services.ml_feature_service.pair_state import PairFeatureState


class TestBarBuilder:
    def test_first_trade_no_bar(self):
        bb = BarBuilder("BTC-USDT")
        result = bb.on_trade(50000.0, 0.1, 1_700_000_000_000)
        assert result is None

    def test_bar_completes_on_minute_boundary(self):
        bb = BarBuilder("BTC-USDT")
        # Use a clean minute boundary
        base_ms = 1_700_000_000_000 - (1_700_000_000_000 % 60_000)
        bb.on_trade(50000.0, 0.1, base_ms)
        bb.on_trade(50100.0, 0.2, base_ms + 30_000)
        bb.on_trade(49900.0, 0.15, base_ms + 45_000)

        bar = bb.on_trade(50050.0, 0.1, base_ms + 60_000)
        assert bar is not None
        assert bar.timestamp_ms == base_ms
        assert bar.open == 50000.0
        assert bar.high == 50100.0
        assert bar.low == 49900.0
        assert bar.close == 49900.0
        assert bar.trade_count == 3

    def test_out_of_order_ignored(self):
        bb = BarBuilder("BTC-USDT")
        base_ms = 1_700_000_060_000
        bb.on_trade(50000.0, 0.1, base_ms)
        result = bb.on_trade(49500.0, 0.1, base_ms - 120_000)
        assert result is None

    def test_flush(self):
        bb = BarBuilder("BTC-USDT")
        bb.on_trade(50000.0, 0.1, 1_700_000_000_000)
        bar = bb.flush()
        assert bar is not None
        assert bar.trade_count == 1

    def test_multi_pair_independence(self):
        bb1 = BarBuilder("BTC-USDT")
        bb2 = BarBuilder("ETH-USDT")
        base = 1_700_000_000_000

        bb1.on_trade(50000, 0.1, base)
        bb2.on_trade(3000, 0.5, base)

        bar1 = bb1.on_trade(50100, 0.2, base + 60_000)
        bar2 = bb2.on_trade(3100, 0.3, base + 60_000)

        assert bar1 is not None
        assert bar2 is not None
        assert bar1.open == 50000
        assert bar2.open == 3000


class TestPairFeatureState:
    def test_seed_from_candles(self):
        state = PairFeatureState("BTC-USDT", "bitget")
        np.random.seed(42)
        n = 100
        df = pd.DataFrame({
            "timestamp_ms": [1_700_000_000_000 + i * 60_000 for i in range(n)],
            "open": 50000 + np.random.normal(0, 50, n),
            "high": 50100 + np.random.normal(0, 50, n),
            "low": 49900 + np.random.normal(0, 50, n),
            "close": 50050 + np.random.normal(0, 50, n),
            "volume": np.abs(np.random.normal(100, 20, n)),
        })
        count = state.seed_from_candles(df)
        assert count == 100
        assert state.is_warm
        assert state.bar_count == 100

    def test_not_warm_until_60_bars(self):
        state = PairFeatureState("BTC-USDT", "bitget")
        df = pd.DataFrame({
            "timestamp_ms": [1_700_000_000_000 + i * 60_000 for i in range(30)],
            "open": [50000] * 30,
            "high": [50100] * 30,
            "low": [49900] * 30,
            "close": [50050] * 30,
            "volume": [100] * 30,
        })
        state.seed_from_candles(df)
        assert not state.is_warm

    def test_to_candles_df(self):
        state = PairFeatureState("BTC-USDT", "bitget")
        state.append_bar(Bar(1_700_000_000_000, 50000, 50100, 49900, 50050, 100, 10))
        df = state.to_candles_df()
        assert len(df) == 1
        assert list(df.columns) == ["timestamp_ms", "open", "high", "low", "close", "volume"]

    def test_resample_5m(self):
        state = PairFeatureState("BTC-USDT", "bitget")
        # Use a clean 5m boundary
        base = 1_700_000_000_000 - (1_700_000_000_000 % 300_000)
        for i in range(10):
            state.append_bar(Bar(
                base + i * 60_000,
                50000 + i, 50100 + i, 49900 + i, 50050 + i, 100 + i, 5,
            ))
        resampled = state.resample(5)
        assert len(resampled) == 2

    def test_sentiment_cache(self):
        state = PairFeatureState("BTC-USDT", "bitget")
        assert state.sentiment_stale_s == float("inf")
        state.update_sentiment_cache(pd.DataFrame({"rate": [0.001]}))
        assert state.sentiment_stale_s < 2.0
        assert state._cached_funding is not None
