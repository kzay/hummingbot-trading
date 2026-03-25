"""Tests for DataCatalog integrity verification methods."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from controllers.backtesting.data_catalog import DataCatalog, _file_sha256
from controllers.backtesting.data_store import save_candles
from controllers.backtesting.types import CandleRow


def _make_candle(ts: int) -> CandleRow:
    return CandleRow(
        timestamp_ms=ts, open=Decimal("100"), high=Decimal("101"),
        low=Decimal("99"), close=Decimal("100"), volume=Decimal("10"),
    )


@pytest.fixture()
def catalog_dir(tmp_path: Path) -> Path:
    """Create a minimal catalog directory with a real parquet file."""
    pq_dir = tmp_path / "bitget" / "BTC-USDT" / "1m"
    pq_dir.mkdir(parents=True)
    pq_file = pq_dir / "data.parquet"
    save_candles([_make_candle(i * 60_000) for i in range(5)], pq_file)
    return tmp_path


def _register_fake(catalog: DataCatalog, catalog_dir: Path) -> None:
    pq = catalog_dir / "bitget" / "BTC-USDT" / "1m" / "data.parquet"
    catalog.register(
        exchange="bitget",
        pair="BTC-USDT",
        resolution="1m",
        start_ms=0,
        end_ms=240_000,
        row_count=5,
        file_path=str(pq),
        file_size_bytes=pq.stat().st_size,
    )


# -- verify_entry -----------------------------------------------------------

class TestVerifyEntry:
    def test_all_checks_pass(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        entry = cat.list_datasets()[0]
        warnings = cat.verify_entry(entry)
        assert warnings == []

    def test_file_missing(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        entry = {
            "file_path": str(catalog_dir / "no" / "such" / "file.parquet"),
            "file_size_bytes": 10,
            "sha256": "abc",
            "row_count": 0,
            "exchange": "x",
            "pair": "y",
            "resolution": "z",
        }
        warnings = cat.verify_entry(entry)
        assert any("missing" in w.lower() for w in warnings)

    def test_size_mismatch(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        entry = cat.list_datasets()[0]
        entry["file_size_bytes"] = 999_999
        warnings = cat.verify_entry(entry)
        assert any("size" in w.lower() for w in warnings)

    def test_hash_mismatch(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        entry = cat.list_datasets()[0]
        entry["sha256"] = "0" * 64
        warnings = cat.verify_entry(entry)
        assert any("sha-256" in w.lower() for w in warnings)

    def test_missing_sha256_skips_hash(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        entry = cat.list_datasets()[0]
        entry.pop("sha256", None)
        warnings = cat.verify_entry(entry)
        assert warnings == [] or not any("sha" in w.lower() for w in warnings)


# -- verify_all --------------------------------------------------------------

class TestVerifyAll:
    def test_all_valid(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        result = cat.verify_all()
        for w_list in result.values():
            assert w_list == []

    def test_detects_failures(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        entry = cat.list_datasets()[0]
        entry["sha256"] = "bad"
        cat._datasets = [entry]
        result = cat.verify_all()
        assert any(len(ws) > 0 for ws in result.values())


# -- reconcile_disk -----------------------------------------------------------

class TestReconcileDisk:
    def test_clean_state(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        rec = cat.reconcile_disk()
        assert rec["orphans"] == []
        assert rec["stale"] == []

    def test_orphan_detected(self, catalog_dir: Path) -> None:
        orphan_dir = catalog_dir / "bitget" / "ETH-USDT" / "5m"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "data.parquet").write_bytes(b"ORPHAN")
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        rec = cat.reconcile_disk()
        assert len(rec["orphans"]) == 1

    def test_stale_detected(self, catalog_dir: Path) -> None:
        cat = DataCatalog(catalog_dir)
        _register_fake(cat, catalog_dir)
        pq = catalog_dir / "bitget" / "BTC-USDT" / "1m" / "data.parquet"
        pq.unlink()
        rec = cat.reconcile_disk()
        assert len(rec["stale"]) == 1


# -- sha256 helper -----------------------------------------------------------

class TestFileSha256:
    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        h1 = _file_sha256(f)
        h2 = _file_sha256(f)
        assert h1 == h2
        assert len(h1) == 64
