from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.ops_db_writer.main import _ingest_market_quote_layers


class _QuoteCursor:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.sql_calls: List[str] = []
        self._last_select_checkpoint = False

    def __enter__(self) -> "_QuoteCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        self.sql_calls.append(sql)
        self.calls.append(params or {})
        self._last_select_checkpoint = "FROM market_quote_ingest_checkpoint" in sql

    def fetchone(self):
        if self._last_select_checkpoint:
            return None
        return None


class _QuoteConn:
    def __init__(self) -> None:
        self.cur = _QuoteCursor()

    def cursor(self) -> _QuoteCursor:
        return self.cur


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row) + "\n")


def test_ingest_market_quote_layers_writes_raw_bar_and_checkpoint(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    events_path = reports_root / "event_store" / "events_20260305.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "stream": "hb.market_quote.v1",
                "stream_entry_id": "1772417386177-0",
                "event_id": "quote-1",
                "event_type": "market_quote",
                "ts_utc": "2026-03-05T12:00:00+00:00",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "payload": {
                    "best_bid": 100.0,
                    "best_ask": 100.2,
                    "mid_price": 100.1,
                    "market_sequence": 11,
                },
            },
            {
                "stream": "hb.market_quote.v1",
                "stream_entry_id": "1772417416177-0",
                "event_id": "quote-2",
                "event_type": "market_quote",
                "ts_utc": "2026-03-05T12:00:30+00:00",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "payload": {
                    "best_bid": 101.0,
                    "best_ask": 101.2,
                    "mid_price": 101.1,
                    "market_sequence": 12,
                },
            },
        ],
    )

    conn = _QuoteConn()
    result = _ingest_market_quote_layers(conn, reports_root, "2026-03-05T12:01:00+00:00")  # type: ignore[arg-type]

    assert result["raw_inserted"] == 2
    assert result["bar_upserts"] == 1
    assert result["quote_events_scanned"] == 2
    assert str(result["checkpoint_source_path"]).endswith("events_20260305.jsonl")
    assert result["checkpoint_source_line"] == 2

    sql_blob = "\n".join(conn.cur.sql_calls)
    assert "INSERT INTO market_quote_raw" in sql_blob
    assert "INSERT INTO market_quote_bar_minute" in sql_blob
    assert "INSERT INTO market_quote_ingest_checkpoint" in sql_blob
