from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.ops_db_writer.main import _ingest_market_depth_layers


class _DepthCursor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.sql_calls: list[str] = []
        self._last_select_checkpoint = False
        self._fetchall_result: list[tuple] = []
        self.sampled_rows: dict[tuple, dict[str, Any]] = {}

    def __enter__(self) -> _DepthCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.sql_calls.append(sql)
        self.calls.append(params or {})
        self._last_select_checkpoint = "FROM market_depth_ingest_checkpoint" in sql
        if "INSERT INTO market_depth_sampled" in sql and params is not None:
            key = (str(params.get("stream_entry_id") or ""), str(params.get("ts_utc") or ""))
            self.sampled_rows[key] = dict(params)
            self._fetchall_result = []
        elif "FROM market_depth_sampled" in sql and "SELECT spread_bps, mid_price" in sql:
            bucket_start = str((params or {}).get("bucket_start_utc") or "")
            bucket_end = str((params or {}).get("bucket_end_utc") or "")
            instance_name = str((params or {}).get("instance_name") or "")
            controller_id = str((params or {}).get("controller_id") or "")
            connector_name = str((params or {}).get("connector_name") or "")
            trading_pair = str((params or {}).get("trading_pair") or "")
            rows = [
                row for row in self.sampled_rows.values()
                if bucket_start <= str(row.get("ts_utc") or "") < bucket_end
                and str(row.get("instance_name") or "") == instance_name
                and str(row.get("controller_id") or "") == controller_id
                and str(row.get("connector_name") or "") == connector_name
                and str(row.get("trading_pair") or "") == trading_pair
            ]
            rows.sort(key=lambda row: (str(row.get("ts_utc") or ""), str(row.get("stream_entry_id") or "")))
            self._fetchall_result = [
                (
                    row.get("spread_bps"),
                    row.get("mid_price"),
                    row.get("bid_depth_total"),
                    row.get("ask_depth_total"),
                    row.get("depth_imbalance"),
                    row.get("source_path"),
                )
                for row in rows
            ]
        else:
            self._fetchall_result = []

    def fetchone(self):
        if self._last_select_checkpoint:
            return None
        return None

    def fetchall(self):
        return list(self._fetchall_result)


class _DepthConn:
    def __init__(self) -> None:
        self.cur = _DepthCursor()

    def cursor(self) -> _DepthCursor:
        return self.cur


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row) + "\n")


def test_ingest_market_depth_layers_writes_raw_sampled_rollup_and_checkpoint(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    events_path = reports_root / "event_store" / "events_20260305.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": "1772417386177-0",
                "event_id": "depth-1",
                "event_type": "market_depth_snapshot",
                "ts_utc": "2026-03-05T12:00:00+00:00",
                "instance_name": "bot1",
                "controller_id": "ctrl-1",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "payload": {
                    "depth_levels": 2,
                    "bids": [{"price": 100.0, "size": 1.0}, {"price": 99.9, "size": 2.0}],
                    "asks": [{"price": 100.1, "size": 1.5}, {"price": 100.2, "size": 1.0}],
                    "market_sequence": 9,
                },
            }
        ],
    )
    monkeypatch.setenv("OPS_DB_L2_SAMPLE_EVERY_N", "1")
    monkeypatch.setenv("OPS_DB_L2_SAMPLE_MIN_INTERVAL_MS", "0")
    monkeypatch.setenv("OPS_DB_L2_SAMPLE_LEVELS", "2")

    conn = _DepthConn()
    result = _ingest_market_depth_layers(conn, reports_root, "2026-03-05T12:01:00+00:00")  # type: ignore[arg-type]

    assert result["raw_inserted"] == 1
    assert result["sampled_inserted"] == 1
    assert result["rollup_upserts"] == 1
    assert result["depth_events_scanned"] == 1
    assert str(result["checkpoint_source_path"]).endswith("events_20260305.jsonl")
    assert result["checkpoint_source_line"] == 1

    sql_blob = "\n".join(conn.cur.sql_calls)
    assert "INSERT INTO market_depth_raw" in sql_blob
    assert "INSERT INTO market_depth_sampled" in sql_blob
    assert "INSERT INTO market_depth_rollup_minute" in sql_blob
    assert "INSERT INTO market_depth_ingest_checkpoint" in sql_blob


def test_ingest_market_depth_layers_rollup_remains_exact_after_replay(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    events_path = reports_root / "event_store" / "events_20260305.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": "1772417386177-0",
                "event_id": "depth-1",
                "event_type": "market_depth_snapshot",
                "ts_utc": "2026-03-05T12:00:00+00:00",
                "instance_name": "bot1",
                "controller_id": "ctrl-1",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "payload": {
                    "depth_levels": 2,
                    "bids": [{"price": 100.0, "size": 1.0}],
                    "asks": [{"price": 100.1, "size": 1.5}],
                    "market_sequence": 9,
                },
            }
        ],
    )
    monkeypatch.setenv("OPS_DB_L2_SAMPLE_EVERY_N", "1")
    monkeypatch.setenv("OPS_DB_L2_SAMPLE_MIN_INTERVAL_MS", "0")
    monkeypatch.setenv("OPS_DB_L2_SAMPLE_LEVELS", "2")

    conn = _DepthConn()
    _ingest_market_depth_layers(conn, reports_root, "2026-03-05T12:01:00+00:00")  # type: ignore[arg-type]
    _ingest_market_depth_layers(conn, reports_root, "2026-03-05T12:02:00+00:00")  # type: ignore[arg-type]

    rollup_params = [
        params for sql, params in zip(conn.cur.sql_calls, conn.cur.calls, strict=True)
        if "INSERT INTO market_depth_rollup_minute" in sql
    ]
    assert len(rollup_params) == 2
    assert rollup_params[0]["event_count"] == 1
    assert rollup_params[1]["event_count"] == 1
