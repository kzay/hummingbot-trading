from __future__ import annotations

import json
from pathlib import Path

from services.ops_db_writer.main import _ingest_paper_exchange_open_orders
from tests.services.conftest import _CaptureConn


def test_ingest_paper_exchange_open_orders_keeps_only_open_rows(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    snapshot_path = reports_root / "verification" / "paper_exchange_state_snapshot_latest.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "ts_utc": "2026-03-06T00:00:00Z",
                "orders": {
                    "ord-open": {
                        "order_id": "ord-open",
                        "instance_name": "bot1",
                        "connector_name": "bitget_perpetual",
                        "trading_pair": "BTC-USDT",
                        "side": "buy",
                        "order_type": "limit",
                        "amount_base": 0.1,
                        "price": 70000.0,
                        "state": "open",
                        "created_ts_ms": 1772755200000,
                        "updated_ts_ms": 1772755205000,
                    },
                    "ord-filled": {
                        "order_id": "ord-filled",
                        "instance_name": "bot1",
                        "connector_name": "bitget_perpetual",
                        "trading_pair": "BTC-USDT",
                        "side": "sell",
                        "order_type": "limit",
                        "amount_base": 0.1,
                        "price": 70100.0,
                        "state": "filled",
                        "created_ts_ms": 1772755210000,
                        "updated_ts_ms": 1772755211000,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    conn = _CaptureConn()
    inserted = _ingest_paper_exchange_open_orders(conn, reports_root, "2026-03-06T00:01:00+00:00")  # type: ignore[arg-type]
    assert inserted == 1
    assert len(conn.cur.calls) == 2  # delete all + one insert
    row = conn.cur.calls[-1]
    assert row["instance_name"] == "bot1"
    assert row["order_id"] == "ord-open"
    assert row["state"] == "open"
    assert "paper_exchange_state_snapshot_latest.json" in row["source_path"]
