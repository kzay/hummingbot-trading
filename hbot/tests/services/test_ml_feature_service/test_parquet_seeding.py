"""Tests for ML feature service parquet seeding and hot-reload."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from controllers.backtesting.data_store import resolve_data_path, save_candles
from controllers.backtesting.types import CandleRow


def _make_candles(n: int, start_ts: int = 0) -> list[CandleRow]:
    return [
        CandleRow(
            timestamp_ms=start_ts + i * 60_000,
            open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal("100"),
            volume=Decimal("10"),
        )
        for i in range(n)
    ]


@pytest.fixture()
def historical_dir(tmp_path: Path) -> Path:
    exchange, pair = "bitget", "BTC-USDT"
    candles = _make_candles(500)
    out_path = resolve_data_path(exchange, pair, "1m", tmp_path)
    save_candles(candles, out_path)
    return tmp_path


class TestSeedFromParquet:
    def test_loads_tail_bars(self, historical_dir: Path) -> None:
        from services.ml_feature_service.main import _seed_from_parquet
        df = _seed_from_parquet("BTC-USDT", "bitget", str(historical_dir), 100)
        assert df is not None
        assert len(df) == 100
        assert df["timestamp_ms"].is_monotonic_increasing

    def test_loads_all_when_fewer_bars(self, historical_dir: Path) -> None:
        from services.ml_feature_service.main import _seed_from_parquet
        df = _seed_from_parquet("BTC-USDT", "bitget", str(historical_dir), 99999)
        assert df is not None
        assert len(df) == 500

    def test_missing_parquet_returns_none(self, tmp_path: Path) -> None:
        from services.ml_feature_service.main import _seed_from_parquet
        df = _seed_from_parquet("ETH-USDT", "bitget", str(tmp_path), 100)
        assert df is None

    def test_corrupt_parquet_returns_none(self, tmp_path: Path) -> None:
        from services.ml_feature_service.main import _seed_from_parquet
        bad_path = resolve_data_path("bitget", "BTC-USDT", "1m", tmp_path)
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_bytes(b"NOT A PARQUET FILE")
        df = _seed_from_parquet("BTC-USDT", "bitget", str(tmp_path), 100)
        assert df is None


class TestSafeHotReload:
    def test_reload_preserves_live_bars(self, historical_dir: Path) -> None:
        from services.ml_feature_service.bar_builder import Bar
        from services.ml_feature_service.main import _safe_hot_reload
        from services.ml_feature_service.pair_state import PairFeatureState

        state = PairFeatureState("BTC-USDT", "bitget")
        live_bar = Bar(
            timestamp_ms=999_999_999,
            open=50000.0, high=50100.0,
            low=49900.0, close=50050.0,
            volume=5.0, trade_count=100,
        )
        state.append_bar(live_bar)
        assert state.bar_count == 1

        _safe_hot_reload(state, str(historical_dir), 600)

        assert state.bar_count > 1
        last_ts = list(state._bars)[-1].timestamp_ms
        assert last_ts == 999_999_999

    def test_reload_with_empty_parquet_noop(self, tmp_path: Path) -> None:
        from services.ml_feature_service.main import _safe_hot_reload
        from services.ml_feature_service.pair_state import PairFeatureState

        state = PairFeatureState("ETH-USDT", "bitget")
        _safe_hot_reload(state, str(tmp_path), 100)
        assert state.bar_count == 0


class TestManifestValidation:
    def test_validation_runs_without_error(self, historical_dir: Path) -> None:
        from services.ml_feature_service.main import _validate_seeding_against_manifest
        from services.ml_feature_service.pair_state import PairFeatureState

        state = PairFeatureState("BTC-USDT", "bitget")
        df = pd.read_parquet(resolve_data_path("bitget", "BTC-USDT", "1m", historical_dir))
        state.seed_from_candles(df)

        _validate_seeding_against_manifest({"BTC-USDT": state})
