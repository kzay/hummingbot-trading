from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from controllers.backtesting.data_catalog import DataCatalog
from controllers.backtesting.data_downloader import DataDownloader
from controllers.backtesting.data_store import (
    load_candles,
    load_funding_rates,
    load_trades,
    resolve_data_path,
    save_funding_rates,
    save_trades,
)
from controllers.backtesting.types import FundingRow, TradeRow


class TestFundingDataStore:
    def test_round_trip_save_and_load(self, tmp_path: Path):
        path = tmp_path / "funding.parquet"
        rows = [
            FundingRow(timestamp_ms=1_000, rate=Decimal("0.0001")),
            FundingRow(timestamp_ms=2_000, rate=Decimal("-0.0002")),
        ]

        save_funding_rates(rows, path)
        loaded = load_funding_rates(path)

        assert loaded == rows

    def test_load_missing_funding_parquet_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Funding-rate Parquet"):
            load_funding_rates(tmp_path / "does_not_exist.parquet")

    def test_load_missing_trade_parquet_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Trade Parquet"):
            load_trades(tmp_path / "does_not_exist.parquet")

    def test_load_missing_candle_parquet_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Candle Parquet"):
            load_candles(tmp_path / "does_not_exist.parquet")


class TestDataCatalog:
    def test_find_supports_funding_resolution(self, tmp_path: Path):
        catalog = DataCatalog(tmp_path)
        catalog.register(
            exchange="bitget",
            pair="BTC-USDT",
            resolution="funding",
            start_ms=1_000,
            end_ms=5_000,
            row_count=3,
            file_path="funding.parquet",
            file_size_bytes=128,
        )

        entry = catalog.find("bitget", "BTC-USDT", "funding")

        assert entry is not None
        assert entry["resolution"] == "funding"
        assert entry["file_path"] == "funding.parquet"

    def test_find_prefers_widest_range_on_duplicates(self, tmp_path: Path):
        catalog = DataCatalog(tmp_path)
        catalog.register(
            exchange="bitget",
            pair="BTC-USDT",
            resolution="funding",
            start_ms=1_000,
            end_ms=10_000,
            row_count=10,
            file_path="wide.parquet",
            file_size_bytes=100,
        )
        catalog.register(
            exchange="bitget",
            pair="BTC-USDT",
            resolution="funding",
            start_ms=2_000,
            end_ms=4_000,
            row_count=2,
            file_path="narrow.parquet",
            file_size_bytes=50,
        )

        entry = catalog.find("bitget", "BTC-USDT", "funding")

        assert entry is not None
        assert entry["file_path"] == "wide.parquet"

    def test_find_returns_none_for_missing_key(self, tmp_path: Path):
        catalog = DataCatalog(tmp_path)
        assert catalog.find("bitget", "ETH-USDT", "1m") is None

    def test_register_prevents_exact_duplicate_file_entries(self, tmp_path: Path):
        catalog = DataCatalog(tmp_path)
        catalog.register("bitget", "BTC-USDT", "funding", 1_000, 5_000, 3, "a.parquet", 100)
        catalog.register("bitget", "BTC-USDT", "funding", 1_000, 5_000, 4, "a.parquet", 200)

        all_entries = [
            d for d in catalog.list_datasets()
            if d["resolution"] == "funding" and d["file_path"] == "a.parquet"
        ]
        assert len(all_entries) == 1
        assert all_entries[0]["row_count"] == 4

    def test_corrupt_catalog_json_starts_fresh(self, tmp_path: Path):
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text("{invalid json[", encoding="utf-8")

        catalog = DataCatalog(tmp_path)
        assert catalog.list_datasets() == []

        catalog.register("bitget", "BTC-USDT", "1m", 1_000, 5_000, 3, "c.parquet", 100)
        assert len(catalog.list_datasets()) == 1

    def test_find_before_first_funding_rate_returns_none(self, tmp_path: Path):
        catalog = DataCatalog(tmp_path)
        catalog.register("bitget", "BTC-USDT", "funding", 5_000, 10_000, 3, "f.parquet", 100)

        entry = catalog.find("bitget", "ETH-USDT", "funding")
        assert entry is None


class _FakeExchange:
    def __init__(self, batches: list[list[dict]] | None = None, supports: bool = True):
        self._batches = list(batches or [])
        self.has = {"fetchFundingRateHistory": supports}

    def fetch_funding_rate_history(self, symbol: str, since: int, limit: int):
        assert symbol == "BTC/USDT:USDT"
        return self._batches.pop(0) if self._batches else []


class TestFundingDownloader:
    def test_download_funding_rates_converts_and_sorts(self):
        downloader = DataDownloader("bitget", delay_s=0.0)
        downloader._exchange = _FakeExchange(
            batches=[
                [
                    {"timestamp": 2_000, "fundingRate": "-0.0002"},
                    {"timestamp": 1_000, "fundingRate": "0.0001"},
                ],
                [],
            ]
        )

        rows = downloader.download_funding_rates("BTC/USDT:USDT", 0, 10_000)

        assert rows == [
            FundingRow(timestamp_ms=1_000, rate=Decimal("0.0001")),
            FundingRow(timestamp_ms=2_000, rate=Decimal("-0.0002")),
        ]

    def test_download_funding_rates_unsupported_exchange_raises(self):
        downloader = DataDownloader("bitget", delay_s=0.0)
        downloader._exchange = _FakeExchange(supports=False)

        with pytest.raises(NotImplementedError):
            downloader.download_funding_rates("BTC/USDT:USDT", 0, 10_000)

    def test_download_and_register_trades_resumes_with_dedup(self, tmp_path: Path):
        downloader = DataDownloader("bitget", delay_s=0.0)
        pair = "BTC-USDT"
        out_path = resolve_data_path("bitget", pair, "trades", tmp_path)

        existing = [
            TradeRow(timestamp_ms=1_000, side="buy", price=Decimal("100"), size=Decimal("1"), trade_id="a"),
        ]
        save_trades(existing, out_path)
        DataCatalog(tmp_path).register(
            exchange="bitget",
            pair=pair,
            resolution="trades",
            start_ms=1_000,
            end_ms=1_000,
            row_count=1,
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )

        downloader.download_trades = lambda *args, **kwargs: [  # type: ignore[method-assign]
            TradeRow(timestamp_ms=1_000, side="buy", price=Decimal("100"), size=Decimal("1"), trade_id="a"),
            TradeRow(timestamp_ms=2_000, side="sell", price=Decimal("101"), size=Decimal("2"), trade_id="b"),
        ]

        rows = downloader.download_and_register_trades(
            "BTC/USDT:USDT",
            0,
            10_000,
            base_dir=tmp_path,
            pair=pair,
        )

        assert [row.trade_id for row in rows] == ["a", "b"]
        assert [row.trade_id for row in load_trades(out_path)] == ["a", "b"]
