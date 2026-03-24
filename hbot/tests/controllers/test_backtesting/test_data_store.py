"""Tests for data store — Parquet round-trip, validation, path resolution."""
from __future__ import annotations

from decimal import Decimal

import pytest

pandas = pytest.importorskip("pandas", reason="pandas required for data store tests")
pytest.importorskip("pyarrow", reason="pyarrow required for data store tests")

from controllers.backtesting.data_store import (
    load_candles,
    load_candles_df,
    load_candles_window,
    load_funding_rates,
    load_funding_window,
    load_long_short_ratio,
    load_trades,
    load_trades_window,
    resolve_data_path,
    save_candles,
    save_funding_rates,
    save_long_short_ratio,
    save_trades,
    validate_candles,
)
from controllers.backtesting.types import CandleRow, FundingRow, LongShortRatioRow, TradeRow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def candles() -> list[CandleRow]:
    """5 1-minute candles."""
    base_ms = 1_700_000_000_000
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("50000") + Decimal(str(i * 100)),
            high=Decimal("50100") + Decimal(str(i * 100)),
            low=Decimal("49900") + Decimal(str(i * 100)),
            close=Decimal("50050") + Decimal(str(i * 100)),
            volume=Decimal("100") + Decimal(str(i * 10)),
        )
        for i in range(5)
    ]


@pytest.fixture
def trades() -> list[TradeRow]:
    """10 trade ticks."""
    base_ms = 1_700_000_000_000
    return [
        TradeRow(
            timestamp_ms=base_ms + i * 1_000,
            side="buy" if i % 2 == 0 else "sell",
            price=Decimal("50000") + Decimal(str(i)),
            size=Decimal("0.1"),
            trade_id=f"t{i}",
        )
        for i in range(10)
    ]


# ---------------------------------------------------------------------------
# Candle round-trip
# ---------------------------------------------------------------------------

class TestCandleRoundTrip:
    def test_save_load_preserves_data(self, candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(candles, path)
        loaded = load_candles(path)

        assert len(loaded) == len(candles)
        for orig, loaded_c in zip(candles, loaded, strict=True):
            assert orig.timestamp_ms == loaded_c.timestamp_ms
            assert orig.open == loaded_c.open
            assert orig.high == loaded_c.high
            assert orig.low == loaded_c.low
            assert orig.close == loaded_c.close
            assert orig.volume == loaded_c.volume

    def test_empty_candles(self, tmp_path):
        path = tmp_path / "empty.parquet"
        save_candles([], path)
        loaded = load_candles(path)
        assert loaded == []

    def test_file_created(self, candles, tmp_path):
        path = tmp_path / "test.parquet"
        assert not path.exists()
        save_candles(candles, path)
        assert path.exists()
        assert path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Trade round-trip
# ---------------------------------------------------------------------------

class TestTradeRoundTrip:
    def test_save_load_preserves_data(self, trades, tmp_path):
        path = tmp_path / "trades.parquet"
        save_trades(trades, path)
        loaded = load_trades(path)

        assert len(loaded) == len(trades)
        for orig, loaded_t in zip(trades, loaded, strict=True):
            assert orig.timestamp_ms == loaded_t.timestamp_ms
            assert orig.side == loaded_t.side
            assert orig.price == loaded_t.price
            assert orig.size == loaded_t.size


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateCandles:
    def test_valid_candles_no_warnings(self, candles):
        warnings = validate_candles(candles)
        assert len(warnings) == 0

    def test_empty_no_warnings(self):
        assert validate_candles([]) == []

    def test_non_monotonic_timestamps_warn(self):
        candles = [
            CandleRow(timestamp_ms=200, open=Decimal("100"), high=Decimal("101"),
                      low=Decimal("99"), close=Decimal("100"), volume=Decimal("10")),
            CandleRow(timestamp_ms=100, open=Decimal("100"), high=Decimal("101"),
                      low=Decimal("99"), close=Decimal("100"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles)
        assert any("monotonic" in w.lower() or "order" in w.lower() or "timestamp" in w.lower() for w in warnings)

    def test_ohlc_high_below_open_warns(self):
        candles = [
            CandleRow(timestamp_ms=1000, open=Decimal("105"), high=Decimal("103"),
                      low=Decimal("99"), close=Decimal("101"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles)
        assert any("ohlc inconsistency" in w.lower() and "high" in w.lower() for w in warnings)

    def test_ohlc_low_above_close_warns(self):
        candles = [
            CandleRow(timestamp_ms=1000, open=Decimal("100"), high=Decimal("105"),
                      low=Decimal("102"), close=Decimal("101"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles)
        assert any("ohlc inconsistency" in w.lower() and "low" in w.lower() for w in warnings)

    def test_ohlc_consistent_no_warning(self):
        candles = [
            CandleRow(timestamp_ms=1000, open=Decimal("100"), high=Decimal("105"),
                      low=Decimal("98"), close=Decimal("103"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles)
        assert not any("ohlc" in w.lower() for w in warnings)

    def test_gap_detection_warns(self):
        candles = [
            CandleRow(timestamp_ms=0, open=Decimal("100"), high=Decimal("101"),
                      low=Decimal("99"), close=Decimal("100"), volume=Decimal("10")),
            CandleRow(timestamp_ms=300_000, open=Decimal("100"), high=Decimal("101"),
                      low=Decimal("99"), close=Decimal("100"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles, expected_interval_ms=60_000, max_gap_multiple=3)
        assert any("gap" in w.lower() for w in warnings)

    def test_no_gap_warning_for_normal_spacing(self):
        candles = [
            CandleRow(timestamp_ms=i * 60_000, open=Decimal("100"), high=Decimal("101"),
                      low=Decimal("99"), close=Decimal("100"), volume=Decimal("10"))
            for i in range(5)
        ]
        warnings = validate_candles(candles, expected_interval_ms=60_000)
        assert not any("gap" in w.lower() for w in warnings)

    def test_spike_detection_warns(self):
        candles = [
            CandleRow(timestamp_ms=1000, open=Decimal("100"), high=Decimal("130"),
                      low=Decimal("100"), close=Decimal("125"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles, max_return_pct=20.0)
        assert any("spike" in w.lower() for w in warnings)

    def test_no_spike_for_normal_candle(self):
        candles = [
            CandleRow(timestamp_ms=1000, open=Decimal("100"), high=Decimal("101"),
                      low=Decimal("99"), close=Decimal("100.5"), volume=Decimal("10")),
        ]
        warnings = validate_candles(candles)
        assert not any("spike" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Long/short ratio round-trip
# ---------------------------------------------------------------------------

@pytest.fixture
def ls_ratio_rows() -> list[LongShortRatioRow]:
    base_ms = 1_700_000_000_000
    return [
        LongShortRatioRow(
            timestamp_ms=base_ms + i * 300_000,
            long_account_ratio=0.55 + i * 0.01,
            short_account_ratio=0.45 - i * 0.01,
            long_short_ratio=(0.55 + i * 0.01) / (0.45 - i * 0.01),
        )
        for i in range(5)
    ]


class TestLongShortRatioRoundTrip:
    def test_save_load_preserves_data(self, ls_ratio_rows, tmp_path):
        path = tmp_path / "ls_ratio.parquet"
        save_long_short_ratio(ls_ratio_rows, path)
        loaded = load_long_short_ratio(path)

        assert len(loaded) == len(ls_ratio_rows)
        for orig, loaded_r in zip(ls_ratio_rows, loaded, strict=True):
            assert orig.timestamp_ms == loaded_r.timestamp_ms
            assert abs(orig.long_account_ratio - loaded_r.long_account_ratio) < 1e-10
            assert abs(orig.short_account_ratio - loaded_r.short_account_ratio) < 1e-10
            assert abs(orig.long_short_ratio - loaded_r.long_short_ratio) < 1e-10

    def test_empty_ls_ratio(self, tmp_path):
        path = tmp_path / "empty_ls.parquet"
        save_long_short_ratio([], path)
        loaded = load_long_short_ratio(path)
        assert loaded == []

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_long_short_ratio(tmp_path / "nonexistent.parquet")


# ---------------------------------------------------------------------------
# load_candles_df — direct DataFrame loading
# ---------------------------------------------------------------------------

class TestLoadCandlesDf:
    def test_returns_float64_dataframe(self, candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(candles, path)
        df = load_candles_df(path)

        assert len(df) == len(candles)
        for col in ["open", "high", "low", "close", "volume"]:
            assert df[col].dtype.name == "float64"
        assert df["timestamp_ms"].dtype.name == "int64"

    def test_values_match_load_candles(self, candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(candles, path)
        df = load_candles_df(path)
        loaded = load_candles(path)

        for i, c in enumerate(loaded):
            assert df.iloc[i]["timestamp_ms"] == c.timestamp_ms
            assert abs(df.iloc[i]["close"] - float(c.close)) < 1e-8

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_candles_df(tmp_path / "nonexistent.parquet")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

class TestResolvePath:
    def test_creates_parent_dirs(self, tmp_path):
        path = resolve_data_path("bitget", "BTC-USDT", "1m", tmp_path)
        assert "bitget" in str(path)
        assert "BTC-USDT" in str(path)
        assert "1m" in str(path)


# ---------------------------------------------------------------------------
# Zstd compression — backward compatibility (task 1.5)
# ---------------------------------------------------------------------------

class TestZstdBackwardCompat:
    """Verify that files written with old Snappy can be read, re-saved as
    Zstd, and produce identical data."""

    def test_snappy_to_zstd_roundtrip(self, candles, tmp_path):
        import pyarrow.parquet as pq

        snappy_path = tmp_path / "legacy_snappy.parquet"
        pd_mod, _ = pandas, None
        rows = [
            {
                "timestamp_ms": c.timestamp_ms,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            }
            for c in candles
        ]
        df = pandas.DataFrame(rows)
        df.to_parquet(snappy_path, index=False, compression="snappy", engine="pyarrow")

        loaded_from_snappy = load_candles(snappy_path)
        assert len(loaded_from_snappy) == len(candles)

        zstd_path = tmp_path / "new_zstd.parquet"
        save_candles(loaded_from_snappy, zstd_path)

        meta = pq.read_metadata(zstd_path)
        assert meta.row_group(0).column(0).compression == "ZSTD"

        loaded_from_zstd = load_candles(zstd_path)
        assert len(loaded_from_zstd) == len(loaded_from_snappy)
        for a, b in zip(loaded_from_snappy, loaded_from_zstd, strict=True):
            assert a.timestamp_ms == b.timestamp_ms
            assert a.open == b.open
            assert a.close == b.close

    def test_row_group_count(self, tmp_path):
        import pyarrow.parquet as pq

        many_candles = [
            CandleRow(
                timestamp_ms=1_700_000_000_000 + i * 60_000,
                open=Decimal("50000"),
                high=Decimal("50100"),
                low=Decimal("49900"),
                close=Decimal("50050"),
                volume=Decimal("100"),
            )
            for i in range(250_000)
        ]
        path = tmp_path / "large.parquet"
        save_candles(many_candles, path)

        meta = pq.read_metadata(path)
        assert meta.num_row_groups >= 2


# ---------------------------------------------------------------------------
# Timeframe-aware validation (task 2.4)
# ---------------------------------------------------------------------------

class TestValidateCandles5m:
    def test_contiguous_5m_no_gaps(self):
        candles = [
            CandleRow(
                timestamp_ms=i * 300_000,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("10"),
            )
            for i in range(100)
        ]
        warnings = validate_candles(candles, expected_interval_ms=300_000)
        assert not any("gap" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Filtered window loaders (tasks 3.5)
# ---------------------------------------------------------------------------

@pytest.fixture
def large_candles() -> list[CandleRow]:
    """200 1-minute candles for window testing."""
    base_ms = 1_700_000_000_000
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("50000") + Decimal(str(i)),
            high=Decimal("50100") + Decimal(str(i)),
            low=Decimal("49900") + Decimal(str(i)),
            close=Decimal("50050") + Decimal(str(i)),
            volume=Decimal("100"),
        )
        for i in range(200)
    ]


@pytest.fixture
def funding_rows() -> list[FundingRow]:
    base_ms = 1_700_000_000_000
    return [
        FundingRow(
            timestamp_ms=base_ms + i * 28_800_000,
            rate=Decimal("0.0001"),
        )
        for i in range(20)
    ]


class TestFilteredCandleLoader:
    def test_window_filters_correctly(self, large_candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(large_candles, path)

        start_ms = large_candles[50].timestamp_ms
        end_ms = large_candles[99].timestamp_ms
        window = load_candles_window(path, start_ms=start_ms, end_ms=end_ms)

        assert len(window) == 50
        assert window[0].timestamp_ms == start_ms
        assert window[-1].timestamp_ms == end_ms

    def test_no_filter_returns_all(self, large_candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(large_candles, path)

        window = load_candles_window(path)
        assert len(window) == len(large_candles)

    def test_chronological_order(self, large_candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(large_candles, path)

        window = load_candles_window(path, start_ms=large_candles[10].timestamp_ms)
        ts_list = [c.timestamp_ms for c in window]
        assert ts_list == sorted(ts_list)

    def test_equals_full_load_plus_python_filter(self, large_candles, tmp_path):
        path = tmp_path / "candles.parquet"
        save_candles(large_candles, path)

        start_ms = large_candles[30].timestamp_ms
        end_ms = large_candles[80].timestamp_ms

        window = load_candles_window(path, start_ms=start_ms, end_ms=end_ms)
        full = load_candles(path)
        python_filtered = [c for c in full if start_ms <= c.timestamp_ms <= end_ms]

        assert len(window) == len(python_filtered)
        for a, b in zip(window, python_filtered, strict=True):
            assert a.timestamp_ms == b.timestamp_ms
            assert a.open == b.open


class TestFilteredTradeLoader:
    def test_window_filters_correctly(self, trades, tmp_path):
        path = tmp_path / "trades.parquet"
        save_trades(trades, path)

        start_ms = trades[3].timestamp_ms
        end_ms = trades[7].timestamp_ms
        window = load_trades_window(path, start_ms=start_ms, end_ms=end_ms)

        assert len(window) == 5
        assert all(start_ms <= t.timestamp_ms <= end_ms for t in window)

    def test_chronological_order(self, trades, tmp_path):
        path = tmp_path / "trades.parquet"
        save_trades(trades, path)

        window = load_trades_window(path)
        ts_list = [t.timestamp_ms for t in window]
        assert ts_list == sorted(ts_list)


class TestFilteredFundingLoader:
    def test_window_filters_correctly(self, funding_rows, tmp_path):
        path = tmp_path / "funding.parquet"
        save_funding_rates(funding_rows, path)

        start_ms = funding_rows[5].timestamp_ms
        end_ms = funding_rows[15].timestamp_ms
        window = load_funding_window(path, start_ms=start_ms, end_ms=end_ms)

        assert len(window) == 11
        assert all(start_ms <= f.timestamp_ms <= end_ms for f in window)

    def test_chronological_order(self, funding_rows, tmp_path):
        path = tmp_path / "funding.parquet"
        save_funding_rates(funding_rows, path)

        window = load_funding_window(path)
        ts_list = [f.timestamp_ms for f in window]
        assert ts_list == sorted(ts_list)


# ---------------------------------------------------------------------------
# Catalog range-aware selection (task 4.3)
# ---------------------------------------------------------------------------

class TestCatalogRangeAware:
    def test_prefers_covering_dataset(self, tmp_path):
        from controllers.backtesting.data_catalog import DataCatalog

        catalog = DataCatalog(tmp_path)
        catalog.register("bitget", "BTC-USDT", "1m", 1000, 5000, 100, "narrow.parquet", 1024)
        catalog.register("bitget", "BTC-USDT", "1m", 0, 10000, 200, "wide.parquet", 2048)

        result = catalog.find("bitget", "BTC-USDT", "1m", start_ms=1000, end_ms=5000)
        assert result is not None
        assert result["file_path"] == "wide.parquet"

    def test_prefers_widest_when_both_cover(self, tmp_path):
        from controllers.backtesting.data_catalog import DataCatalog

        catalog = DataCatalog(tmp_path)
        catalog.register("bitget", "BTC-USDT", "1m", 0, 8000, 150, "medium.parquet", 1500)
        catalog.register("bitget", "BTC-USDT", "1m", 0, 20000, 300, "widest.parquet", 3000)

        result = catalog.find("bitget", "BTC-USDT", "1m", start_ms=1000, end_ms=5000)
        assert result is not None
        assert result["file_path"] == "widest.parquet"

    def test_prefers_newest_among_equal(self, tmp_path):
        from controllers.backtesting.data_catalog import DataCatalog

        catalog = DataCatalog(tmp_path)
        catalog.register("bitget", "BTC-USDT", "1m", 0, 10000, 200, "old.parquet", 2048)
        import time
        time.sleep(0.01)
        catalog.register("bitget", "BTC-USDT", "1m", 0, 10000, 200, "new.parquet", 2048)

        result = catalog.find("bitget", "BTC-USDT", "1m", start_ms=1000, end_ms=5000)
        assert result is not None
        assert result["file_path"] == "new.parquet"

    def test_no_range_prefers_widest(self, tmp_path):
        from controllers.backtesting.data_catalog import DataCatalog

        catalog = DataCatalog(tmp_path)
        catalog.register("bitget", "BTC-USDT", "1m", 1000, 5000, 80, "narrow.parquet", 1024)
        catalog.register("bitget", "BTC-USDT", "1m", 0, 10000, 200, "wide.parquet", 2048)

        result = catalog.find("bitget", "BTC-USDT", "1m")
        assert result is not None
        assert result["file_path"] == "wide.parquet"


# ---------------------------------------------------------------------------
# Migration idempotency (task 6.6)
# ---------------------------------------------------------------------------

class TestMigrationIdempotent:
    def test_migrate_preserves_content(self, candles, tmp_path):
        import pyarrow.parquet as pq
        from scripts.migrate_parquet_zstd import migrate_file

        path = tmp_path / "candles.parquet"
        rows = [
            {
                "timestamp_ms": c.timestamp_ms,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            }
            for c in candles
        ]
        df = pandas.DataFrame(rows)
        df.to_parquet(path, index=False, compression="snappy", engine="pyarrow")

        original = pq.read_table(path)
        migrate_file(path)
        migrated = pq.read_table(path)

        assert original.equals(migrated)
        meta = pq.read_metadata(path)
        assert meta.row_group(0).column(0).compression == "ZSTD"

    def test_idempotent_second_run(self, candles, tmp_path):
        from scripts.migrate_parquet_zstd import migrate_file

        path = tmp_path / "candles.parquet"
        save_candles(candles, path)

        migrate_file(path)
        first_loaded = load_candles(path)

        migrate_file(path)
        second_loaded = load_candles(path)

        assert len(first_loaded) == len(second_loaded)
        for a, b in zip(first_loaded, second_loaded, strict=True):
            assert a.timestamp_ms == b.timestamp_ms
            assert a.open == b.open
