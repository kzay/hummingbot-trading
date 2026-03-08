from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.ops_db_writer.main import _ingest_event_envelope_raw


class _EnvelopeCursor:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.sql_calls: List[str] = []
        self._checkpoint: Optional[tuple[str, int]] = None
        self._last_select_checkpoint = False

    def __enter__(self) -> "_EnvelopeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        self.sql_calls.append(sql)
        self.calls.append(params or {})
        self._last_select_checkpoint = "FROM event_envelope_ingest_checkpoint" in sql
        if "INSERT INTO event_envelope_ingest_checkpoint" in sql and isinstance(params, dict):
            source_path = str(params.get("source_path") or "")
            source_line = int(params.get("source_line") or 0)
            if source_path:
                self._checkpoint = (source_path, source_line)

    def fetchone(self):
        if self._last_select_checkpoint:
            return self._checkpoint
        return None


class _EnvelopeConn:
    def __init__(self) -> None:
        self.cur = _EnvelopeCursor()

    def cursor(self) -> _EnvelopeCursor:
        return self.cur


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row) + "\n")


def test_ingest_event_envelope_raw_maps_fields_and_uses_idempotent_conflict(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    events_path = reports_root / "event_store" / "events_20260302.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "stream": "hb.market_data.v1",
                "stream_entry_id": "1772417386177-0",
                "event_id": "evt-1",
                "event_type": "market_snapshot",
                "event_version": "v1",
                "ts_utc": "2026-03-02T02:09:46.176000+00:00",
                "producer": "hb:v2_with_controllers.py",
                "instance_name": "bot1",
                "controller_id": "epp_v2_4_bot_a",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "correlation_id": "corr-1",
                "schema_validation_status": "ok",
                "payload": {"foo": "bar"},
            },
            {
                "stream": "hb.audit.v1",
                # Missing stream_entry_id intentionally checks deterministic fallback.
                "event_id": "evt-2",
                "event_type": "audit",
                "payload": {"severity": "info"},
            },
        ],
    )

    conn = _EnvelopeConn()
    inserted = _ingest_event_envelope_raw(  # type: ignore[arg-type]
        conn,
        reports_root,
        "2026-03-02T03:00:00+00:00",
    )
    assert inserted == 2
    sql_blob = "\n".join(conn.cur.sql_calls)
    assert "ON CONFLICT (stream, stream_entry_id, ts_utc)" in sql_blob
    assert "INSERT INTO event_envelope_ingest_checkpoint" in sql_blob

    inserted_rows = [row for row in conn.cur.calls if "stream" in row]
    assert len(inserted_rows) == 2

    first = inserted_rows[0]
    assert first["stream"] == "hb.market_data.v1"
    assert first["stream_entry_id"] == "1772417386177-0"
    assert first["event_id"] == "evt-1"
    assert first["event_version"] == "v1"
    assert first["instance_name"] == "bot1"
    assert first["ts_utc"] == "2026-03-02T02:09:46.176000+00:00"
    assert json.loads(first["payload"]) == {"foo": "bar"}

    second = inserted_rows[1]
    assert second["stream"] == "hb.audit.v1"
    assert second["stream_entry_id"].startswith("event:")
    assert second["event_id"] == "evt-2"
    assert second["event_version"] == "v1"
    assert second["schema_validation_status"] == "ok"
    assert second["ts_utc"].endswith("+00:00")

    inserted_again = _ingest_event_envelope_raw(  # type: ignore[arg-type]
        conn,
        reports_root,
        "2026-03-02T03:05:00+00:00",
    )
    assert inserted_again == 0
