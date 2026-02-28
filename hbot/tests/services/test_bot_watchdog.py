"""Tests for bot_watchdog — circuit breaker state machine, persistence, staleness."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import services.bot_watchdog.main as watchdog_mod
from services.bot_watchdog.main import (
    _check_circuit_breaker,
    _clear_stale_since,
    _failure_fingerprint,
    _fingerprint_suppressed,
    _get_stale_since,
    _load_state,
    _record_restart,
    _record_fingerprint,
    _restart_backoff_active,
    _save_state,
    _set_stale_since,
)


# ── Circuit breaker state machine ────────────────────────────────────

class TestCircuitBreaker:
    def test_initial_state_breaker_closed(self):
        state = {}
        breaker_open, count = _check_circuit_breaker("bot1", state)
        assert not breaker_open
        assert count == 0

    def test_increment_on_restart(self):
        state = {}
        _record_restart("bot1", state)
        _, count = _check_circuit_breaker("bot1", state)
        assert count == 1

    def test_multiple_restarts_tracked(self):
        state = {}
        for _ in range(3):
            _record_restart("bot1", state)
        _, count = _check_circuit_breaker("bot1", state)
        assert count == 3

    @patch.object(watchdog_mod, "MAX_RESTARTS", 3)
    @patch.object(watchdog_mod, "WINDOW_S", 3600)
    def test_max_restarts_opens_breaker(self):
        state = {}
        for _ in range(3):
            _record_restart("bot1", state)
        breaker_open, count = _check_circuit_breaker("bot1", state)
        assert breaker_open
        assert count == 3

    @patch.object(watchdog_mod, "MAX_RESTARTS", 3)
    @patch.object(watchdog_mod, "WINDOW_S", 3600)
    def test_below_max_breaker_stays_closed(self):
        state = {}
        for _ in range(2):
            _record_restart("bot1", state)
        breaker_open, _ = _check_circuit_breaker("bot1", state)
        assert not breaker_open

    def test_reset_on_window_expiry(self):
        state = {}
        old_time = time.time() - 7200  # 2 hours ago, well outside default 1h window
        state["bot1_restarts"] = [old_time, old_time + 1, old_time + 2]
        breaker_open, count = _check_circuit_breaker("bot1", state)
        assert not breaker_open
        assert count == 0

    def test_restart_backoff_inactive_without_prior_restart(self):
        active, remaining = _restart_backoff_active("bot1", {})
        assert not active
        assert remaining == 0

    @patch.object(watchdog_mod, "RESTART_BACKOFF_S", [60, 120, 300])
    def test_restart_backoff_active_after_restart(self):
        state = {}
        _record_restart("bot1", state)
        active, remaining = _restart_backoff_active("bot1", state)
        assert active
        assert remaining > 0

    @patch.object(watchdog_mod, "RESTART_BACKOFF_S", [1, 1, 1])
    def test_restart_backoff_expires(self):
        state = {"bot1_restarts": [time.time() - 10], "bot1_last_restart_ts": time.time() - 10}
        active, remaining = _restart_backoff_active("bot1", state)
        assert not active
        assert remaining == 0


# ── Cooldown / stale-since tracking ──────────────────────────────────

class TestStaleSince:
    def test_initial_stale_since_is_zero(self):
        state = {}
        assert _get_stale_since("bot1", state) == 0

    def test_set_and_get(self):
        state = {}
        ts = time.time()
        _set_stale_since("bot1", state, ts)
        assert _get_stale_since("bot1", state) == ts

    def test_clear_resets_to_zero(self):
        state = {}
        _set_stale_since("bot1", state, time.time())
        _clear_stale_since("bot1", state)
        assert _get_stale_since("bot1", state) == 0

    def test_clear_absent_key_is_noop(self):
        state = {}
        _clear_stale_since("bot1", state)
        assert _get_stale_since("bot1", state) == 0


class TestFailureFingerprint:
    def test_fingerprint_format(self):
        fp = _failure_fingerprint("minute_csv_stale_400s", "running")
        assert fp == "minute_csv_stale_400s|running"

    @patch.object(watchdog_mod, "FINGERPRINT_COOLDOWN_S", 60)
    def test_fingerprint_suppression_window(self):
        state = {}
        fp = _failure_fingerprint("reason_a", "running")
        _record_fingerprint("bot1", fp, state)
        suppressed, remaining = _fingerprint_suppressed("bot1", fp, state)
        assert suppressed
        assert remaining > 0

    @patch.object(watchdog_mod, "FINGERPRINT_COOLDOWN_S", 1)
    def test_fingerprint_suppression_expires(self):
        state = {"bot1_fingerprints": {"reason|running": time.time() - 10}}
        suppressed, remaining = _fingerprint_suppressed("bot1", "reason|running", state)
        assert not suppressed
        assert remaining == 0


# ── State file persistence ──────────────────────────────────────────

class TestStatePersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        state_file = tmp_path / "state.json"
        with patch.object(watchdog_mod, "STATE_FILE", state_file):
            state = {"bot1_restarts": [1.0, 2.0], "bot1_stale_since": 100.0}
            _save_state(state)
            loaded = _load_state()
            assert loaded["bot1_restarts"] == [1.0, 2.0]
            assert loaded["bot1_stale_since"] == 100.0

    def test_load_missing_file_returns_empty(self, tmp_path):
        state_file = tmp_path / "missing.json"
        with patch.object(watchdog_mod, "STATE_FILE", state_file):
            assert _load_state() == {}

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("NOT JSON!!!", encoding="utf-8")
        with patch.object(watchdog_mod, "STATE_FILE", state_file):
            assert _load_state() == {}


# ── Bot staleness detection ──────────────────────────────────────────

class TestBotStaleness:
    @patch.object(watchdog_mod, "DATA_ROOT")
    @patch.object(watchdog_mod, "STALE_THRESHOLD_S", 300)
    def test_no_minute_csv_is_stale(self, mock_data_root, tmp_path):
        mock_data_root.__truediv__ = lambda self, x: tmp_path / x
        # bot1/logs doesn't exist → stale
        from services.bot_watchdog.main import _bot_is_stale
        stale, age, reason = _bot_is_stale("bot1")
        assert stale
        assert reason == "no_minute_or_heartbeat_found"

    @patch.object(watchdog_mod, "STALE_THRESHOLD_S", 300)
    def test_fresh_minute_csv_is_not_stale(self, tmp_path):
        logs_dir = tmp_path / "bot1" / "logs" / "epp_v24" / "BTC-USDT"
        logs_dir.mkdir(parents=True)
        minute_csv = logs_dir / "minute.csv"
        minute_csv.write_text("header\ndata", encoding="utf-8")

        with patch.object(watchdog_mod, "DATA_ROOT", tmp_path):
            from services.bot_watchdog.main import _bot_is_stale
            stale, age, reason = _bot_is_stale("bot1")
            assert not stale
            assert reason in {"ok", "heartbeat_missing_minute_ok"}

    @patch.object(watchdog_mod, "STALE_THRESHOLD_S", 300)
    @patch.object(watchdog_mod, "MINUTE_STALE_HEARTBEAT_FRESH_GRACE_S", 900)
    def test_minute_stale_but_fresh_heartbeat_uses_grace(self, tmp_path):
        logs_dir = tmp_path / "bot1" / "logs"
        minute_dir = logs_dir / "epp_v24" / "BTC-USDT"
        heartbeat_dir = logs_dir / "heartbeat"
        minute_dir.mkdir(parents=True)
        heartbeat_dir.mkdir(parents=True)
        minute_csv = minute_dir / "minute.csv"
        hb_json = heartbeat_dir / "strategy_heartbeat.json"
        minute_csv.write_text("header\ndata", encoding="utf-8")
        hb_json.write_text('{"status":"ok"}', encoding="utf-8")
        now = time.time()
        # Minute stale at 500s (>300) while heartbeat is fresh (5s)
        os.utime(minute_csv, (now - 500, now - 500))
        os.utime(hb_json, (now - 5, now - 5))

        with patch.object(watchdog_mod, "DATA_ROOT", tmp_path):
            from services.bot_watchdog.main import _bot_is_stale
            stale, _, reason = _bot_is_stale("bot1")
            assert not stale
            assert reason.startswith("minute_stale_heartbeat_fresh_grace_")

    @patch.object(watchdog_mod, "STALE_THRESHOLD_S", 300)
    @patch.object(watchdog_mod, "MINUTE_STALE_HEARTBEAT_FRESH_GRACE_S", 900)
    def test_minute_stale_over_grace_is_stale(self, tmp_path):
        logs_dir = tmp_path / "bot1" / "logs"
        minute_dir = logs_dir / "epp_v24" / "BTC-USDT"
        heartbeat_dir = logs_dir / "heartbeat"
        minute_dir.mkdir(parents=True)
        heartbeat_dir.mkdir(parents=True)
        minute_csv = minute_dir / "minute.csv"
        hb_json = heartbeat_dir / "strategy_heartbeat.json"
        minute_csv.write_text("header\ndata", encoding="utf-8")
        hb_json.write_text('{"status":"ok"}', encoding="utf-8")
        now = time.time()
        # Minute stale past grace: 1300s (>300+900); heartbeat still fresh
        os.utime(minute_csv, (now - 1300, now - 1300))
        os.utime(hb_json, (now - 5, now - 5))

        with patch.object(watchdog_mod, "DATA_ROOT", tmp_path):
            from services.bot_watchdog.main import _bot_is_stale
            stale, _, reason = _bot_is_stale("bot1")
            assert stale
            assert reason.startswith("minute_csv_stale_")
