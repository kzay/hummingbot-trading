"""Tests for event_store — JSONL write integrity, append behavior, invalid events."""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from services.event_store.main import (
    _accept_envelope,
    _append_events,
    _batch_lag_metrics,
    _coerce_ts_utc,
    _normalize,
    _read_stats,
    _resolve_root,
    _trim_known_streams,
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


class _FakeConn:
    def close(self) -> None:
        return None


class _FakeStreamClient:
    def __init__(self) -> None:
        self.enabled = True
        self._emitted = False
        self.acked = []
        self.ack_many_calls = []
        self.group_calls = []
        self.read_group_multi_calls = []

    def create_group(self, _stream: str, _group: str, *, start_id: str = "$") -> None:
        self.group_calls.append((_stream, _group, start_id))
        return None

    def read_group(self, stream: str, group: str, consumer: str, count: int, block_ms: int):
        if stream == "hb.market_data.v1" and not self._emitted:
            self._emitted = True
            return [("1-0", {"event_id": "evt-1", "event_type": "market_snapshot", "timestamp_ms": 1700000000000})]
        return []

    def read_group_multi(self, streams: list[str], group: str, consumer: str, count: int, block_ms: int):
        self.read_group_multi_calls.append((list(streams), group, consumer, count, block_ms))
        if "hb.market_data.v1" in streams and not self._emitted:
            self._emitted = True
            return [("hb.market_data.v1", "1-0", {"event_id": "evt-1", "event_type": "market_snapshot", "timestamp_ms": 1700000000000})]
        return []

    def claim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int = 30_000,
        count: int = 100,
        start_id: str = "0-0",
    ):
        return []

    def read_pending(self, stream: str, group: str, consumer: str, count: int, block_ms: int):
        return []

    def ack(self, stream: str, group: str, entry_id: str) -> None:
        self.acked.append((stream, group, entry_id))

    def ack_many(self, stream: str, group: str, entry_ids: list[str]) -> None:
        self.ack_many_calls.append((stream, group, list(entry_ids)))
        for entry_id in entry_ids:
            self.acked.append((stream, group, entry_id))

    def read_latest(self, _stream: str):
        return None


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

    def test_write_stats_empty_batch_refreshes_timestamp(self, tmp_path):
        stats_file = tmp_path / "stats.json"
        ok = _write_stats(stats_file, [])
        assert ok is True
        stats = _read_stats(stats_file)
        assert stats["total_events"] == 0
        assert stats["events_by_stream"] == {}
        assert stats["missing_correlation_count"] == 0
        assert str(stats["ts_utc"]).strip() != ""
        assert stats["ts_utc"] == stats["last_update_utc"]
        assert stats["ingest_duration_ms_recent"] == []
        assert stats["ingest_duration_ms_last"] == 0.0
        assert stats["last_batch_size"] == 0
        assert stats["accepted_events_last"] == 0
        assert stats["eligible_ack_entries_last"] == 0
        assert stats["oldest_event_lag_ms_last"] == 0.0
        assert stats["last_batch_stream_counts"] == {}

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
        _write_stats(
            stats_file,
            batch2,
            batch_duration_ms=12.5,
            cycle_metrics={
                "accepted_events_last": 2,
                "dropped_events_last": 1,
                "pending_entries_read_last": 3,
                "claimed_entries_read_last": 4,
                "new_entries_read_last": 5,
                "eligible_ack_entries_last": 2,
                "oldest_event_lag_ms_last": 250.0,
                "latest_event_lag_ms_last": 10.0,
                "last_batch_stream_counts": {"hb.signal.v1": 2},
            },
        )
        stats = _read_stats(stats_file)
        assert stats["total_events"] == 3
        assert stats["events_by_stream"]["hb.market_data.v1"] == 1
        assert stats["events_by_stream"]["hb.signal.v1"] == 2
        assert stats["last_batch_size"] == 2
        assert stats["ingest_duration_ms_last"] == 12.5
        assert stats["ingest_duration_ms_recent"][-1] == 12.5
        assert stats["accepted_events_last"] == 2
        assert stats["dropped_events_last"] == 1
        assert stats["pending_entries_read_last"] == 3
        assert stats["claimed_entries_read_last"] == 4
        assert stats["new_entries_read_last"] == 5
        assert stats["eligible_ack_entries_last"] == 2
        assert stats["oldest_event_lag_ms_last"] == 250.0
        assert stats["latest_event_lag_ms_last"] == 10.0
        assert stats["oldest_event_lag_ms_recent"][-1] == 250.0
        assert stats["last_batch_stream_counts"] == {"hb.signal.v1": 2}


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

    def test_resolve_root_prefers_hb_root_env(self, monkeypatch):
        monkeypatch.setenv("HB_ROOT", "/tmp/hbot-test-root")
        assert str(_resolve_root()).replace("\\", "/").endswith("/tmp/hbot-test-root")

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

    def test_accept_envelope_rejects_bot_fill_missing_identity_fields(self):
        envelope = _normalize(
            {
                "event_type": "bot_fill",
                "event_id": "evt-1",
                "order_id": "ord-1",
                "connector_name": "bitget",
                "trading_pair": "BTC-USDT",
                "instance_name": "",
            },
            stream="hb.bot_telemetry.v1",
            entry_id="1-0",
            producer="p",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is False
        assert reason == "bot_fill_missing_instance_name"

    def test_accept_envelope_accepts_bot_fill_with_identity_fields(self):
        envelope = _normalize(
            {
                "event_type": "bot_fill",
                "event_id": "evt-2",
                "instance_name": "bot1",
                "controller_id": "ctrl-1",
                "connector_name": "bitget",
                "trading_pair": "BTC-USDT",
                "order_id": "ord-2",
            },
            stream="hb.bot_telemetry.v1",
            entry_id="2-0",
            producer="p",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is True
        assert reason == ""

    def test_accept_envelope_rejects_paper_exchange_event_without_instance_scope(self):
        envelope = _normalize(
            {
                "event_type": "paper_exchange_event",
                "event_id": "evt-pe-1",
                "instance_name": "",
                "connector_name": "bitget",
                "trading_pair": "BTC-USDT",
            },
            stream="hb.paper_exchange.event.v1",
            entry_id="3-0",
            producer="paper_exchange_service",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is False
        assert reason == "paper_exchange_event_missing_instance_name"

    def test_accept_envelope_accepts_paper_exchange_event_with_instance_scope(self):
        envelope = _normalize(
            {
                "event_type": "paper_exchange_event",
                "event_id": "evt-pe-2",
                "instance_name": "bot1",
                "connector_name": "bitget",
                "trading_pair": "BTC-USDT",
            },
            stream="hb.paper_exchange.event.v1",
            entry_id="4-0",
            producer="paper_exchange_service",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is True
        assert reason == ""

    def test_accept_envelope_rejects_execution_intent_without_controller_scope(self):
        envelope = _normalize(
            {
                "event_type": "execution_intent",
                "event_id": "evt-intent-1",
                "instance_name": "bot1",
                "controller_id": "",
                "action": "resume",
            },
            stream="hb.execution_intent.v1",
            entry_id="5-0",
            producer="coordination_service",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is False
        assert reason == "execution_intent_missing_controller_id"

    def test_accept_envelope_rejects_strategy_signal_without_instance_scope(self):
        envelope = _normalize(
            {
                "event_type": "strategy_signal",
                "event_id": "evt-signal-1",
                "instance_name": "",
                "signal_name": "inventory_rebalance",
                "signal_value": 0.1,
            },
            stream="hb.signal.v1",
            entry_id="6-0",
            producer="signal_service",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is False
        assert reason == "strategy_signal_missing_instance_name"

    def test_accept_envelope_rejects_audit_without_instance_scope(self):
        envelope = _normalize(
            {
                "event_type": "audit",
                "event_id": "evt-audit-1",
                "instance_name": "",
                "category": "risk_decision",
                "message": "missing identity scope",
            },
            stream="hb.audit.v1",
            entry_id="7-0",
            producer="risk_service",
        )
        accepted, reason = _accept_envelope(envelope)
        assert accepted is False
        assert reason == "audit_missing_instance_name"

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
        assert stats["total_events"] == 0
        assert stats["events_by_stream"] == {}
        assert stats["missing_correlation_count"] == 0
        assert stats["last_update_utc"] == ""
        assert stats["ts_utc"] == ""
        assert stats["ingest_duration_ms_recent"] == []
        assert stats["ingest_duration_ms_last"] == 0.0
        assert stats["last_batch_size"] == 0
        assert stats["accepted_events_last"] == 0
        assert stats["dropped_events_last"] == 0
        assert stats["pending_entries_read_last"] == 0
        assert stats["claimed_entries_read_last"] == 0
        assert stats["new_entries_read_last"] == 0
        assert stats["eligible_ack_entries_last"] == 0
        assert stats["oldest_event_lag_ms_last"] == 0.0
        assert stats["latest_event_lag_ms_last"] == 0.0
        assert stats["oldest_event_lag_ms_recent"] == []
        assert stats["last_batch_stream_counts"] == {}

    @patch("services.event_store.main.time.sleep")
    @patch.dict(os.environ, {"EVENT_STORE_STATS_RETRIES": "2"}, clear=False)
    def test_write_stats_returns_false_after_retries(self, _mock_sleep, tmp_path):
        stats_file = tmp_path / "stats.json"
        batch = [_normalize(_make_payload(), "s", "1-0", "p")]
        with patch("services.event_store.main.os.replace", side_effect=OSError("read-only fs")):
            ok = _write_stats(stats_file, batch)
        assert ok is False


def test_run_once_leaves_entries_unacked_when_db_mirror_write_fails(monkeypatch, tmp_path):
    from services.event_store import main as event_store_main

    fake_client = _FakeStreamClient()
    monkeypatch.setattr(event_store_main, "RedisStreamClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(event_store_main, "_store_path", lambda _root: tmp_path / "events.jsonl")
    monkeypatch.setattr(event_store_main, "_stats_path", lambda _root: tmp_path / "stats.json")
    monkeypatch.setattr(event_store_main, "_append_events", lambda _path, _batch: True)
    monkeypatch.setattr(event_store_main, "_write_stats", lambda _path, _batch, batch_duration_ms=None, cycle_metrics=None: True)
    monkeypatch.setattr(event_store_main, "_connect_db", lambda: _FakeConn())
    monkeypatch.setattr(event_store_main, "_ensure_db_schema", lambda _conn: None)
    monkeypatch.setattr(event_store_main, "_append_events_db", lambda _conn, _batch: False)
    monkeypatch.setenv("EXT_SIGNAL_RISK_ENABLED", "true")
    monkeypatch.setenv("EVENT_STORE_DB_MIRROR_ENABLED", "true")
    monkeypatch.setenv("EVENT_STORE_DB_MIRROR_REQUIRED", "false")
    monkeypatch.setenv("EVENT_STORE_BOOTSTRAP_SNAPSHOT_ENABLED", "false")
    event_store_main.run(once=True)
    assert fake_client.acked == []


def test_run_once_creates_groups_from_backlog_start_id(monkeypatch, tmp_path):
    from services.event_store import main as event_store_main

    fake_client = _FakeStreamClient()
    monkeypatch.setattr(event_store_main, "RedisStreamClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(event_store_main, "_store_path", lambda _root: tmp_path / "events.jsonl")
    monkeypatch.setattr(event_store_main, "_stats_path", lambda _root: tmp_path / "stats.json")
    monkeypatch.setattr(event_store_main, "_append_events", lambda _path, _batch: True)
    monkeypatch.setattr(event_store_main, "_write_stats", lambda _path, _batch, batch_duration_ms=None, cycle_metrics=None: True)
    monkeypatch.setenv("EXT_SIGNAL_RISK_ENABLED", "true")
    monkeypatch.setenv("EVENT_STORE_DB_MIRROR_ENABLED", "false")
    monkeypatch.setenv("EVENT_STORE_BOOTSTRAP_SNAPSHOT_ENABLED", "false")
    monkeypatch.setenv("EVENT_STORE_GROUP_START_ID", "0")

    event_store_main.run(once=True)

    assert fake_client.group_calls
    assert all(start_id == "0" for _stream, _group, start_id in fake_client.group_calls)


def test_run_once_acks_entries_only_after_db_mirror_success(monkeypatch, tmp_path):
    from services.event_store import main as event_store_main

    fake_client = _FakeStreamClient()
    monkeypatch.setattr(event_store_main, "RedisStreamClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(event_store_main, "_store_path", lambda _root: tmp_path / "events.jsonl")
    monkeypatch.setattr(event_store_main, "_stats_path", lambda _root: tmp_path / "stats.json")
    monkeypatch.setattr(event_store_main, "_append_events", lambda _path, _batch: True)
    monkeypatch.setattr(event_store_main, "_write_stats", lambda _path, _batch, batch_duration_ms=None, cycle_metrics=None: True)
    monkeypatch.setattr(event_store_main, "_connect_db", lambda: _FakeConn())
    monkeypatch.setattr(event_store_main, "_ensure_db_schema", lambda _conn: None)
    monkeypatch.setattr(event_store_main, "_append_events_db", lambda _conn, _batch: True)
    monkeypatch.setenv("EXT_SIGNAL_RISK_ENABLED", "true")
    monkeypatch.setenv("EVENT_STORE_DB_MIRROR_ENABLED", "true")
    monkeypatch.setenv("EVENT_STORE_DB_MIRROR_REQUIRED", "false")
    monkeypatch.setenv("EVENT_STORE_BOOTSTRAP_SNAPSHOT_ENABLED", "false")
    event_store_main.run(once=True)
    assert fake_client.acked == [("hb.market_data.v1", "hb_event_store_v1", "1-0")]
    assert fake_client.ack_many_calls == [("hb.market_data.v1", "hb_event_store_v1", ["1-0"])]
    assert len(fake_client.read_group_multi_calls) == 1


def test_run_once_claims_and_acks_stale_pending_entries(monkeypatch, tmp_path):
    from services.event_store import main as event_store_main

    class _PendingOnlyClient(_FakeStreamClient):
        def __init__(self) -> None:
            super().__init__()
            self._pending_emitted = False

        def read_group_multi(self, streams: list[str], group: str, consumer: str, count: int, block_ms: int):
            return []

        def claim_pending(
            self,
            stream: str,
            group: str,
            consumer: str,
            *,
            min_idle_ms: int = 30_000,
            count: int = 100,
            start_id: str = "0-0",
        ):
            if stream == "hb.market_data.v1" and not self._pending_emitted:
                self._pending_emitted = True
                return [("9-0", {"event_id": "evt-pending", "event_type": "market_snapshot", "timestamp_ms": 1700000000100})]
            return []

    fake_client = _PendingOnlyClient()
    monkeypatch.setattr(event_store_main, "RedisStreamClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(event_store_main, "_store_path", lambda _root: tmp_path / "events.jsonl")
    monkeypatch.setattr(event_store_main, "_stats_path", lambda _root: tmp_path / "stats.json")
    monkeypatch.setattr(event_store_main, "_append_events", lambda _path, _batch: True)
    monkeypatch.setattr(event_store_main, "_write_stats", lambda _path, _batch, batch_duration_ms=None, cycle_metrics=None: True)
    monkeypatch.setenv("EXT_SIGNAL_RISK_ENABLED", "true")
    monkeypatch.setenv("EVENT_STORE_DB_MIRROR_ENABLED", "false")
    monkeypatch.setenv("EVENT_STORE_BOOTSTRAP_SNAPSHOT_ENABLED", "false")
    event_store_main.run(once=True)
    assert fake_client.acked == [("hb.market_data.v1", "hb_event_store_v1", "9-0")]
    assert fake_client.ack_many_calls == [("hb.market_data.v1", "hb_event_store_v1", ["9-0"])]


def test_batch_lag_metrics_reports_oldest_and_latest_event_age() -> None:
    batch = [
        {"ts_utc": "2026-03-09T12:00:00+00:00"},
        {"ts_utc": "2026-03-09T12:00:01+00:00"},
    ]
    metrics = _batch_lag_metrics(
        batch,
        now_utc=datetime(2026, 3, 9, 12, 0, 3, tzinfo=UTC),
    )
    assert metrics["oldest_event_lag_ms_last"] == 3000.0
    assert metrics["latest_event_lag_ms_last"] == 2000.0


def test_trim_known_streams_returns_aggregate_counts() -> None:
    class _TrimClient:
        def __init__(self) -> None:
            self.calls = []

        def xtrim(self, stream: str, maxlen: int, approximate: bool = True):
            self.calls.append((stream, maxlen, approximate))
            if stream == "hb.fail.v1":
                return None
            return 3

    client = _TrimClient()
    summary = _trim_known_streams(
        client,  # type: ignore[arg-type]
        {
            "hb.market_data.v1": 1000,
            "hb.signal.v1": 500,
            "hb.fail.v1": 200,
        },
    )
    assert summary == {
        "streams_checked": 3,
        "trim_calls": 2,
        "entries_trimmed": 6,
        "errors": 1,
    }
    assert ("hb.market_data.v1", 1000, True) in client.calls


def test_trim_known_streams_logs_nonfatal_trim_failures() -> None:
    class _TrimClient:
        def xtrim(self, stream: str, maxlen: int, approximate: bool = True):
            raise RuntimeError(f"trim failure for {stream}")

    with patch("services.event_store.main.logger.warning") as warning_mock:
        summary = _trim_known_streams(
            _TrimClient(),  # type: ignore[arg-type]
            {"hb.market_data.v1": 1000},
        )

    assert summary["errors"] == 1
    warning_mock.assert_called_once()
