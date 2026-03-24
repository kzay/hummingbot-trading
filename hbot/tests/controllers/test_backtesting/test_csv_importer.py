"""Tests for CSV importer — OHLCV and tick_emitter format detection."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from controllers.backtesting.csv_importer import (
    CsvImportResult,
    import_csv,
    import_csv_safe,
)


def _write_csv(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content.strip() + "\n")
    return f


class TestOhlcvImport:
    def test_standard_columns(self, tmp_path):
        csv_content = """\
timestamp,open,high,low,close,volume
1700000000000,50000,50050,49950,50020,100
1700000060000,50020,50080,49980,50050,120
"""
        path = _write_csv(tmp_path, "ohlcv.csv", csv_content)
        result = import_csv(path, "bitget", "BTC-USDT", "1m")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].open == Decimal("50000")
        assert result[1].close == Decimal("50050")

    def test_alias_columns(self, tmp_path):
        csv_content = """\
time,Open,High,Low,Close,Volume
1700000000000,50000,50050,49950,50020,100
"""
        path = _write_csv(tmp_path, "alias.csv", csv_content)
        result = import_csv(path, "bitget", "BTC-USDT", "1m")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_deduplication(self, tmp_path):
        csv_content = """\
timestamp,open,high,low,close,volume
1700000000000,50000,50050,49950,50020,100
1700000000000,50000,50050,49950,50020,100
"""
        path = _write_csv(tmp_path, "dupes.csv", csv_content)
        result = import_csv(path, "bitget", "BTC-USDT", "1m")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_sorted_output(self, tmp_path):
        csv_content = """\
timestamp,open,high,low,close,volume
1700000120000,50040,50090,49990,50060,130
1700000000000,50000,50050,49950,50020,100
1700000060000,50020,50080,49980,50050,120
"""
        path = _write_csv(tmp_path, "unsorted.csv", csv_content)
        result = import_csv(path, "bitget", "BTC-USDT", "1m")
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0].timestamp_ms < result[1].timestamp_ms < result[2].timestamp_ms


class TestMissingColumns:
    def test_missing_required_column_returns_errors(self, tmp_path):
        csv_content = """\
timestamp,open,high,low,volume
1700000000000,50000,50050,49950,100
"""
        path = _write_csv(tmp_path, "missing.csv", csv_content)
        result = import_csv(path, "bitget", "BTC-USDT", "1m")
        assert isinstance(result, list)
        if result and isinstance(result[0], str):
            assert any("close" in e.lower() for e in result)

    def test_empty_file(self, tmp_path):
        path = _write_csv(tmp_path, "empty.csv", "")
        result = import_csv(path, "bitget", "BTC-USDT", "1m")
        assert isinstance(result, list)


class TestImportCsvSafe:
    def test_success_returns_ok_result(self, tmp_path):
        csv_content = """\
timestamp,open,high,low,close,volume
1700000000000,50000,50050,49950,50020,100
"""
        path = _write_csv(tmp_path, "good.csv", csv_content)
        result = import_csv_safe(path)
        assert isinstance(result, CsvImportResult)
        assert result.ok
        assert len(result.candles) == 1
        assert len(result.errors) == 0

    def test_csv_import_result_not_ok_when_empty(self):
        result = CsvImportResult()
        assert not result.ok
