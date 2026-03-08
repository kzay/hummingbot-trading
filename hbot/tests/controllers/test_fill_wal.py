"""Tests for the fill WAL in shared controller logging."""
import json
from pathlib import Path

from controllers.runtime.logging import CsvSplitLogger


def test_fill_wal_replay_on_startup(tmp_path: Path):
    wal_path = tmp_path / "epp_v24" / "test_a" / "fills.wal"
    wal_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": "2026-01-01T00:00:00Z", "bot_variant": "a", "exchange": "test",
         "trading_pair": "BTC-USDT", "side": "buy", "price": "50000",
         "amount_base": "0.001", "notional_quote": "50", "fee_quote": "0.05",
         "order_id": "o1", "state": "running", "mid_ref": "50000",
         "expected_spread_pct": "0.003", "adverse_drift_30s": "0",
         "fee_source": "manual", "is_maker": "True", "realized_pnl_quote": "0"},
    ]
    with wal_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    logger = CsvSplitLogger(str(tmp_path), "test", "a")
    csv_path = tmp_path / "epp_v24" / "test_a" / "fills.csv"
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert "o1" in content

    assert wal_path.read_text(encoding="utf-8").strip() == ""


def test_fill_wal_write_and_flush(tmp_path: Path):
    logger = CsvSplitLogger(str(tmp_path), "test", "a")
    logger.log_fill({
        "bot_variant": "a", "exchange": "test", "trading_pair": "BTC-USDT",
        "side": "sell", "price": "51000", "amount_base": "0.002",
        "notional_quote": "102", "fee_quote": "0.10", "order_id": "o2",
        "state": "running", "mid_ref": "51000", "expected_spread_pct": "0.004",
        "adverse_drift_30s": "0", "fee_source": "auto:bitget",
        "is_maker": "True", "realized_pnl_quote": "0.5",
    })

    csv_path = tmp_path / "epp_v24" / "test_a" / "fills.csv"
    content = csv_path.read_text(encoding="utf-8")
    assert "o2" in content

    wal_path = tmp_path / "epp_v24" / "test_a" / "fills.wal"
    assert wal_path.read_text(encoding="utf-8").strip() == ""


def test_minute_log_includes_spread_cap_fields(tmp_path: Path):
    logger = CsvSplitLogger(str(tmp_path), "test", "a")
    logger.log_minute(
        {
            "bot_variant": "a",
            "bot_mode": "paper",
            "accounting_source": "paper_desk_v2",
            "exchange": "test",
            "trading_pair": "BTC-USDT",
            "state": "running",
            "regime": "neutral",
            "mid": "100",
            "equity_quote": "1000",
            "base_pct": "0.5",
            "target_base_pct": "0.5",
            "spread_pct": "0.002",
            "spread_floor_pct": "0.001",
            "spread_competitiveness_cap_active": "True",
            "spread_competitiveness_cap_side_pct": "0.0005",
        }
    )
    logger.flush_all()

    csv_path = tmp_path / "epp_v24" / "test_a" / "minute.csv"
    content = csv_path.read_text(encoding="utf-8")
    assert "spread_competitiveness_cap_active" in content
    assert "spread_competitiveness_cap_side_pct" in content
    assert "0.0005" in content
