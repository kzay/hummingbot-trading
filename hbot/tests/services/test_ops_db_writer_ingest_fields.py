from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List

from services.ops_db_writer.main import _ingest_fills, _ingest_minutes
from tests.services.conftest import _CaptureConn


def _write_csv(path: Path, header: List[str], row: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(header)
        writer.writerow(row)


def test_ingest_fills_maps_amount_base_fee_quote_and_raw_payload(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    fills_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv"
    _write_csv(
        fills_path,
        [
            "ts",
            "exchange",
            "trading_pair",
            "side",
            "price",
            "amount_base",
            "notional_quote",
            "fee_quote",
            "order_id",
            "state",
            "mid_ref",
            "expected_spread_pct",
            "adverse_drift_30s",
            "fee_source",
            "is_maker",
            "realized_pnl_quote",
        ],
        [
            "2026-03-01T12:00:00+00:00",
            "bitget_paper_trade",
            "BTC-USDT",
            "buy",
            "68000",
            "0.001",
            "68",
            "0.0136",
            "paper-1",
            "running",
            "67990",
            "0.002",
            "-0.0002",
            "project:/fee_profiles.json",
            "true",
            "0.10",
        ],
    )

    conn = _CaptureConn()
    inserted = _ingest_fills(conn, data_root, "2026-03-01T12:01:00+00:00")  # type: ignore[arg-type]
    assert inserted == 1
    row = conn.cur.calls[0]

    assert row["amount"] == 0.001
    assert row["amount_base"] == 0.001
    assert row["fee_paid_quote"] == 0.0136
    assert row["fee_quote"] == 0.0136
    assert row["is_maker"] is True
    assert row["exchange"] == "bitget_paper_trade"
    assert row["trading_pair"] == "BTC-USDT"
    assert row["fill_key"]
    raw_payload = json.loads(row["raw_payload"])
    assert raw_payload["order_id"] == "paper-1"
    assert raw_payload["notional_quote"] == "68"


def test_ingest_minutes_persists_extended_fields_and_raw_payload(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    minute_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_csv(
        minute_path,
        [
            "ts",
            "exchange",
            "trading_pair",
            "state",
            "regime",
            "equity_quote",
            "base_pct",
            "target_base_pct",
            "daily_loss_pct",
            "drawdown_pct",
            "cancel_per_min",
            "orders_active",
            "fills_count_today",
            "fees_paid_today_quote",
            "risk_reasons",
            "bot_mode",
            "accounting_source",
            "mid",
            "spread_pct",
            "net_edge_pct",
            "turnover_today_x",
        ],
        [
            "2026-03-01T12:00:00+00:00",
            "bitget_perpetual",
            "BTC-USDT",
            "running",
            "neutral",
            "1000",
            "0.50",
            "0.45",
            "0.00",
            "0.01",
            "1",
            "2",
            "5",
            "0.25",
            "none",
            "paper",
            "paper_desk_v2",
            "68010",
            "0.0019",
            "0.0003",
            "0.95",
        ],
    )

    conn = _CaptureConn()
    inserted = _ingest_minutes(conn, data_root, "2026-03-01T12:01:00+00:00")  # type: ignore[arg-type]
    assert inserted == 1
    row = conn.cur.calls[0]

    assert row["bot_mode"] == "paper"
    assert row["accounting_source"] == "paper_desk_v2"
    assert row["mid"] == 68010.0
    assert row["spread_pct"] == 0.0019
    assert row["net_edge_pct"] == 0.0003
    assert row["turnover_today_x"] == 0.95
    raw_payload = json.loads(row["raw_payload"])
    assert raw_payload["risk_reasons"] == "none"
