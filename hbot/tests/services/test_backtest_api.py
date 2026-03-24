"""Tests for backtest_api — JobStore, validation, and preset loading."""
from __future__ import annotations

from unittest.mock import patch

from services.realtime_ui_api.backtest_api import (
    JobStore,
    _load_presets,
    _now_iso,
    _validate_overrides,
)


class TestJobStore:
    def test_insert_and_get(self, tmp_path):
        store = JobStore(tmp_path / "test.db")
        job = {
            "id": "abc123",
            "preset_id": "bot1_baseline",
            "overrides": {"initial_equity": "1000"},
            "status": "pending",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        store.insert(job)
        got = store.get("abc123")
        assert got is not None
        assert got["preset_id"] == "bot1_baseline"
        assert got["status"] == "pending"

    def test_get_missing(self, tmp_path):
        store = JobStore(tmp_path / "test.db")
        assert store.get("nonexistent") is None

    def test_update(self, tmp_path):
        store = JobStore(tmp_path / "test.db")
        store.insert({
            "id": "abc123",
            "preset_id": "test",
            "status": "pending",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        store.update("abc123", status="running", pid=12345)
        got = store.get("abc123")
        assert got["status"] == "running"
        assert got["pid"] == 12345

    def test_list_all(self, tmp_path):
        store = JobStore(tmp_path / "test.db")
        for i in range(5):
            store.insert({
                "id": f"job_{i}",
                "preset_id": "test",
                "status": "completed",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
        jobs = store.list_all(limit=3)
        assert len(jobs) == 3

    def test_running_count(self, tmp_path):
        store = JobStore(tmp_path / "test.db")
        store.insert({
            "id": "r1", "preset_id": "t", "status": "running",
            "created_at": _now_iso(), "updated_at": _now_iso(),
        })
        store.insert({
            "id": "r2", "preset_id": "t", "status": "completed",
            "created_at": _now_iso(), "updated_at": _now_iso(),
        })
        assert store.running_count() == 1


class TestValidateOverrides:
    def test_empty_is_ok(self):
        assert _validate_overrides({}) is None

    def test_allowed_keys(self):
        result = _validate_overrides({"initial_equity": "500"})
        assert result is None

    def test_disallowed_key(self):
        result = _validate_overrides({"strategy_class": "evil"})
        assert result is not None
        assert "not allowed" in result

    def test_equity_too_low(self):
        result = _validate_overrides({"initial_equity": "10"})
        assert result is not None
        assert "between" in result

    def test_equity_too_high(self):
        result = _validate_overrides({"initial_equity": "999999"})
        assert result is not None
        assert "between" in result

    def test_invalid_date_format(self):
        result = _validate_overrides({"start_date": "2025/01/01", "end_date": "2025/02/01"})
        assert result is not None
        assert "YYYY-MM-DD" in result

    def test_date_range_too_long(self):
        result = _validate_overrides({"start_date": "2024-01-01", "end_date": "2025-12-31"})
        assert result is not None
        assert "exceed" in result

    def test_end_before_start(self):
        result = _validate_overrides({"start_date": "2025-06-01", "end_date": "2025-01-01"})
        assert result is not None
        assert "after" in result


class TestPresetLoading:
    def test_loads_from_directory(self, tmp_path):
        (tmp_path / "test_preset.yml").write_text(
            "strategy_class: test.Strategy\n"
            "initial_equity: 1000\n"
            "data_source:\n"
            "  pair: BTC-USDT\n"
            "  resolution: 1m\n"
        )
        with patch("services.realtime_ui_api.backtest_api._PRESETS_DIR", tmp_path):
            presets = _load_presets()
        assert "test_preset" in presets
        assert presets["test_preset"]["pair"] == "BTC-USDT"
        assert presets["test_preset"]["initial_equity"] == 1000.0

    def test_missing_dir_returns_empty(self, tmp_path):
        with patch("services.realtime_ui_api.backtest_api._PRESETS_DIR", tmp_path / "nonexistent"):
            presets = _load_presets()
        assert presets == {}
