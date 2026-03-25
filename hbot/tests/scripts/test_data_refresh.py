"""Smoke tests for scripts/ops/data_refresh.py."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from controllers.backtesting.types import CandleRow


def _make_candle(ts: int, price: float = 100.0) -> CandleRow:
    return CandleRow(
        timestamp_ms=ts,
        open=Decimal(str(price)),
        high=Decimal(str(price + 1)),
        low=Decimal(str(price - 1)),
        close=Decimal(str(price)),
        volume=Decimal("10"),
    )


class TestMaterializeHigherTimeframes:
    def test_materializes_5m_from_1m(self, tmp_path: Path) -> None:
        import pandas as pd
        from controllers.backtesting.data_store import resolve_data_path, save_candles

        exchange, pair = "bitget", "BTC-USDT"
        candles = [_make_candle(i * 60_000, price=100 + i * 0.01) for i in range(100)]
        out = resolve_data_path(exchange, pair, "1m", tmp_path)
        save_candles(candles, out)

        from scripts.ops.data_refresh import materialize_higher_timeframes

        results = materialize_higher_timeframes(tmp_path, exchange, pair, ["5m"])
        assert len(results) == 1
        assert results[0]["resolution"] == "5m"
        assert results[0]["row_count"] > 0

        out_5m = resolve_data_path(exchange, pair, "5m", tmp_path)
        assert out_5m.exists()

    def test_dry_run_skips_write(self, tmp_path: Path) -> None:
        import pandas as pd
        from controllers.backtesting.data_store import resolve_data_path, save_candles

        exchange, pair = "bitget", "BTC-USDT"
        candles = [_make_candle(i * 60_000) for i in range(100)]
        out = resolve_data_path(exchange, pair, "1m", tmp_path)
        save_candles(candles, out)

        from scripts.ops.data_refresh import materialize_higher_timeframes

        results = materialize_higher_timeframes(tmp_path, exchange, pair, ["5m"], dry_run=True)
        assert results[0].get("dry_run") is True

        out_5m = resolve_data_path(exchange, pair, "5m", tmp_path)
        assert not out_5m.exists()


class TestDetectAndRepairGaps:
    def test_no_gaps_returns_zero(self, tmp_path: Path) -> None:
        from controllers.backtesting.data_store import resolve_data_path, save_candles

        exchange, pair = "bitget", "BTC-USDT"
        candles = [_make_candle(i * 60_000) for i in range(50)]
        out = resolve_data_path(exchange, pair, "1m", tmp_path)
        save_candles(candles, out)

        mock_dl = MagicMock()
        mock_dl._exchange_id = exchange

        from scripts.ops.data_refresh import _detect_and_repair_gaps

        found, repaired = _detect_and_repair_gaps(
            mock_dl, "BTC/USDT:USDT", pair, "1m", tmp_path,
        )
        assert found == 0
        assert repaired == 0

    def test_detects_gaps(self, tmp_path: Path) -> None:
        from controllers.backtesting.data_store import resolve_data_path, save_candles

        exchange, pair = "bitget", "BTC-USDT"
        timestamps = [0, 60_000, 120_000, 500_000, 560_000]
        candles = [_make_candle(ts) for ts in timestamps]
        out = resolve_data_path(exchange, pair, "1m", tmp_path)
        save_candles(candles, out)

        mock_dl = MagicMock()
        mock_dl._exchange_id = exchange

        from scripts.ops.data_refresh import _detect_and_repair_gaps

        found, repaired = _detect_and_repair_gaps(
            mock_dl, "BTC/USDT:USDT", pair, "1m", tmp_path, dry_run=True,
        )
        assert found == 1
        assert repaired == 0
