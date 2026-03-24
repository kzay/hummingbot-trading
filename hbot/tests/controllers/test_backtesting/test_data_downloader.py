"""Tests for DataDownloader — mark/index/LS-ratio methods with mocked ccxt."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

pandas = pytest.importorskip("pandas", reason="pandas required")
pytest.importorskip("pyarrow", reason="pyarrow required")

from controllers.backtesting.data_downloader import DataDownloader
from controllers.backtesting.data_store import (
    load_candles,
    load_long_short_ratio,
    resolve_data_path,
)

BASE_MS = 1_700_000_000_000


def _make_ohlcv_batch(start_ms: int, count: int = 5, step_ms: int = 60_000) -> list[list]:
    return [
        [start_ms + i * step_ms, 50000 + i, 50100 + i, 49900 + i, 50050 + i, 100 + i]
        for i in range(count)
    ]


def _make_ls_ratio_batch(start_ms: int, count: int = 3, step_ms: int = 300_000) -> list[dict]:
    return [
        {
            "timestamp": start_ms + i * step_ms,
            "longShortRatio": 1.2 + i * 0.1,
            "longAccount": 0.55 + i * 0.01,
            "shortAccount": 0.45 - i * 0.01,
        }
        for i in range(count)
    ]


@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.has = {
        "fetchTrades": True,
        "fetchFundingRateHistory": True,
        "fetchLongShortRatioHistory": True,
    }
    exchange.markets = {}
    return exchange


@pytest.fixture
def downloader(mock_exchange):
    dl = DataDownloader("bitget")
    dl._exchange = mock_exchange
    dl._ohlcv_max_limit = 200
    return dl


class TestDownloadMarkCandles:
    def test_returns_candle_rows(self, downloader, mock_exchange):
        batch = _make_ohlcv_batch(BASE_MS, count=3)
        mock_exchange.fetch_ohlcv.side_effect = [batch, []]

        result = downloader.download_mark_candles(
            "BTC/USDT:USDT", "1m", BASE_MS, BASE_MS + 300_000,
        )
        assert len(result) == 3
        assert result[0].timestamp_ms == BASE_MS
        mock_exchange.fetch_ohlcv.assert_called()
        call_kwargs = mock_exchange.fetch_ohlcv.call_args
        assert call_kwargs[1].get("params") == {"price": "mark"} or \
               (len(call_kwargs[0]) > 4 and call_kwargs[0][4] == {"price": "mark"})

    def test_volume_zero_accepted(self, downloader, mock_exchange):
        batch = [[BASE_MS, 50000, 50100, 49900, 50050, 0]]
        mock_exchange.fetch_ohlcv.side_effect = [batch, []]

        result = downloader.download_mark_candles(
            "BTC/USDT:USDT", "1m", BASE_MS, BASE_MS + 60_000,
        )
        assert len(result) == 1
        assert result[0].volume == Decimal("0")


class TestDownloadIndexCandles:
    def test_returns_candle_rows(self, downloader, mock_exchange):
        batch = _make_ohlcv_batch(BASE_MS, count=2)
        mock_exchange.fetch_ohlcv.side_effect = [batch, []]

        result = downloader.download_index_candles(
            "BTC/USDT:USDT", "1m", BASE_MS, BASE_MS + 300_000,
        )
        assert len(result) == 2


class TestDownloadLongShortRatio:
    def test_returns_ls_ratio_rows(self, downloader, mock_exchange):
        batch = _make_ls_ratio_batch(BASE_MS, count=3)
        mock_exchange.fetch_long_short_ratio_history.side_effect = [batch, []]

        result = downloader.download_long_short_ratio(
            "BTC/USDT:USDT", "5m", BASE_MS, BASE_MS + 1_000_000,
        )
        assert len(result) == 3
        assert result[0].timestamp_ms == BASE_MS
        assert abs(result[0].long_account_ratio - 0.55) < 1e-6
        assert abs(result[0].long_short_ratio - 1.2) < 1e-6

    def test_raises_when_not_supported(self, downloader, mock_exchange):
        mock_exchange.has["fetchLongShortRatioHistory"] = False
        with pytest.raises(NotImplementedError, match="does not support"):
            downloader.download_long_short_ratio(
                "BTC/USDT:USDT", "5m", BASE_MS, BASE_MS + 1_000_000,
            )


class TestRegisterMethods:
    def test_register_mark_candles(self, downloader, mock_exchange, tmp_path):
        batch = _make_ohlcv_batch(BASE_MS, count=3)
        mock_exchange.fetch_ohlcv.side_effect = [batch, []]

        rows = downloader.download_and_register_mark_candles(
            "BTC/USDT:USDT", "1m", BASE_MS, BASE_MS + 300_000,
            base_dir=tmp_path, pair="BTC-USDT",
        )
        assert len(rows) == 3
        out_path = resolve_data_path("bitget", "BTC-USDT", "mark_1m", tmp_path)
        assert out_path.exists()
        loaded = load_candles(out_path)
        assert len(loaded) == 3

    def test_register_ls_ratio(self, downloader, mock_exchange, tmp_path):
        batch = _make_ls_ratio_batch(BASE_MS, count=4)
        mock_exchange.fetch_long_short_ratio_history.side_effect = [batch, []]

        rows = downloader.download_and_register_long_short_ratio(
            "BTC/USDT:USDT", "5m", BASE_MS, BASE_MS + 2_000_000,
            base_dir=tmp_path, pair="BTC-USDT",
        )
        assert len(rows) == 4
        out_path = resolve_data_path("bitget", "BTC-USDT", "ls_ratio", tmp_path)
        assert out_path.exists()
        loaded = load_long_short_ratio(out_path)
        assert len(loaded) == 4

    def test_catalog_registration(self, downloader, mock_exchange, tmp_path):
        from controllers.backtesting.data_catalog import DataCatalog

        batch = _make_ohlcv_batch(BASE_MS, count=2)
        mock_exchange.fetch_ohlcv.side_effect = [batch, []]

        downloader.download_and_register_index_candles(
            "BTC/USDT:USDT", "5m", BASE_MS, BASE_MS + 600_000,
            base_dir=tmp_path, pair="BTC-USDT",
        )
        catalog = DataCatalog(base_dir=tmp_path)
        entry = catalog.find("bitget", "BTC-USDT", "index_5m")
        assert entry is not None
        assert entry["row_count"] == 2
