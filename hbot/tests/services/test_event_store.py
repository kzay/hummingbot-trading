"""Tests for event_store — JSONL write integrity, append behavior, invalid events."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

from services.event_store.main import (
    _append_events,
    _coerce_ts_utc,
    _normalize,
    _read_stats,
    _write_stats,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_payload(event_type: str = "market_snapshot", instance: str = "bot1") -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "producer": "test",
        "instance_name": instance,
        "controller_id": "epp_v2_4",
        "connector_name": "bitget",
        "trading_pair": "BTC-USDT",
    }


# ── Stream → JSONL write integrity ──────────────────────────────────

class TestJsonlWriteIntegrity:
    def test_single_event_round_trip(self, tmp_path):
        event_file = tmp_path / "events.jsonl"
        payload = _make_payload()
        normalized = _normalize(payload, stream="hb.market_data.v1", entry_id="1-0", producer="test")
        _append_events(event_file, [normalized])

        lines = event_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        restored = json.loads(lines[0])
        assert restored["event_type"] == "market_snapshot"
        assert restored["stream"] == "hb.market_data.v1"
        assert restored["stream_entry_id"] == "1-0"
        assert "payload" in restored

    def test_multiple_events_each_on_own_line(self, tmp_path):
        event_file = tmp_path / "events.jsonl"
        events = [
            _normalize(_make_payload("market_snapshot"), "hb.market_data.v1", f"{i}-0", "test")
            for i in range(5)
        ]
        _append_events(event_file, events)
        lines = event_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            obj = json.loads(line)
            assert obj["schema_validation_status"] == "ok"

    def test_normalize_envelope_shape(self):
        payload = _make_payload()
        normalized = _normalize(payload, stream="hb.signal.v1", entry_id="42-0", producer="svc")
        required_keys = {
            "event_id", "event_type", "event_version", "ts_utc", "producer",
            "instance_name", "controller_id", "connector_name", "trading_pair",
            "correlation_id", "stream", "stream_entry_id", "payload",
            "ingest_ts_utc", "schema_validation_status",
        }
        assert required_keys.issubset(set(normalized.keys()))


# ── File rotation / append behavior ──────────────────────────────────

class TestAppendBehavior:
    def test_append_creates_file_if_missing(self, tmp_path):
        event_file = tmp_path / "new_file.jsonl"
        assert not event_file.exists()
        _append_events(event_file, [_normalize(_make_payload(), "s", "1-0", "p")])
        assert event_file.exists()
        assert len(event_file.read_text(encoding="utf-8").strip().split("\n")) == 1

    def test_append_preserves_existing_content(self, tmp_path):
        event_file = tmp_path / "events.jsonl"
        batch1 = [_normalize(_make_payload(), "s", "1-0", "p")]
        batch2 = [_normalize(_make_payload(), "s", "2-0", "p")]
        _append_events(event_file, batch1)
        _append_events(event_file, batch2)
        lines = event_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_empty_batch_does_not_write(self, tmp_path):
        event_file = tmp_path / "events.jsonl"
        _append_events(event_file, [])
        assert not event_file.exists()

    @patch("services.event_store.main.time.sleep")
    @patch.dict(os.environ, {"EVENT_STORE_APPEND_RETRIES": "2"}, clear=False)
    def test_append_returns_false_after_retries(self, _mock_sleep, tmp_path):
        event_file = tmp_path / "events.jsonl"
        payload = _normalize(_make_payload(), "s", "1-0", "p")
        with patch("pathlib.Path.open", side_effect=OSError("disk full")):
            ok = _append_events(event_file, [payload])
        assert ok is False

    def test_stats_accumulate_across_batches(self, tmp_path):
        stats_file = tmp_path / "stats.json"
        batch1 = [_normalize(_make_payload(), "hb.market_data.v1", "1-0", "p")]
        batch2 = [
            _normalize(_make_payload(), "hb.signal.v1", "2-0", "p"),
            _normalize(_make_payload(), "hb.signal.v1", "3-0", "p"),
        ]
        _write_stats(stats_file, batch1)
        _write_stats(stats_file, batch2)
        stats = _read_stats(stats_file)
        assert stats["total_events"] == 3
        assert stats["events_by_stream"]["hb.market_data.v1"] == 1
        assert stats["events_by_stream"]["hb.signal.v1"] == 2


# ── Invalid event handling ───────────────────────────────────────────

class TestInvalidEvents:
    def test_coerce_ts_utc_from_milliseconds(self):
        out = _coerce_ts_utc(1700000000000)
        assert out.endswith("+00:00")
        assert "T" in out

    def test_coerce_ts_utc_from_seconds_epoch(self):
        out = _coerce_ts_utc(1700000000)
        assert out.endswith("+00:00")
        assert int(out[0:4]) >= 2000

    def test_coerce_ts_utc_from_iso(self):
        out = _coerce_ts_utc("2026-03-01T12:00:00Z")
        assert out.startswith("2026-03-01T12:00:00")

    def test_normalize_missing_fields_uses_defaults(self):
        normalized = _normalize(payload={}, stream="hb.audit.v1", entry_id="1-0", producer="test")
        assert normalized["event_type"] == "audit"
        assert normalized["producer"] == "test"
        assert normalized["instance_name"] == ""

    def test_normalize_preserves_raw_payload(self):
        raw = {"weird_key": 123, "nested": {"deep": True}}
        normalized = _normalize(raw, stream="hb.market_data.v1", entry_id="1-0", producer="p")
        assert normalized["payload"] == raw

    def test_normalize_preserves_version_and_validation_status(self):
        payload = _make_payload()
        payload["event_version"] = "v2"
        payload["schema_validation_status"] = "legacy_backfill"
        normalized = _normalize(payload, stream="hb.audit.v1", entry_id="1-0", producer="p")
        assert normalized["event_version"] == "v2"
        assert normalized["schema_validation_status"] == "legacy_backfill"

    def test_missing_correlation_tracked_in_stats(self, tmp_path):
        stats_file = tmp_path / "stats.json"
        event_no_corr = _normalize({}, stream="s", entry_id="1-0", producer="p")
        # _normalize assigns event_id as correlation_id when missing, so strip it
        event_no_corr["correlation_id"] = ""
        _write_stats(stats_file, [event_no_corr])
        stats = _read_stats(stats_file)
        assert stats["missing_correlation_count"] == 1

    def test_read_stats_corrupt_file_returns_defaults(self, tmp_path):
        stats_file = tmp_path / "stats.json"
        stats_file.write_text("NOT JSON", encoding="utf-8")
        stats = _read_stats(stats_file)
        assert stats["total_events"] == 0

    def test_read_stats_missing_file_returns_defaults(self, tmp_path):
        stats = _read_stats(tmp_path / "missing.json")
        assert stats == {"total_events": 0, "events_by_stream": {}, "missing_correlation_count": 0, "last_update_utc": ""}

    @patch("services.event_store.main.time.sleep")
    @patch.dict(os.environ, {"EVENT_STORE_STATS_RETRIES": "2"}, clear=False)
    def test_write_stats_returns_false_after_retries(self, _mock_sleep, tmp_path):
        stats_file = tmp_path / "stats.json"
        batch = [_normalize(_make_payload(), "s", "1-0", "p")]
        with patch("services.event_store.main.os.replace", side_effect=OSError("read-only fs")):
            ok = _write_stats(stats_file, batch)
        assert ok is False
