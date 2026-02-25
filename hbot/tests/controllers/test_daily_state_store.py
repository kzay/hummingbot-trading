"""Tests for controllers.daily_state_store — dual-backend persistence."""
import json
from pathlib import Path

from controllers.daily_state_store import DailyStateStore


def test_save_and_load_file_only(tmp_path: Path):
    file_path = str(tmp_path / "state.json")
    store = DailyStateStore(file_path=file_path, redis_key="test:key")
    data = {"day_key": "2026-02-24", "equity_open": "100", "position_base": "0.5"}
    store.save(data, now_ts=1_000_000.0, force=True)
    loaded = store.load()
    assert loaded is not None
    assert loaded["position_base"] == "0.5"
    assert loaded["day_key"] == "2026-02-24"


def test_load_returns_none_when_empty(tmp_path: Path):
    file_path = str(tmp_path / "nonexistent.json")
    store = DailyStateStore(file_path=file_path, redis_key="test:key")
    assert store.load() is None


def test_save_throttle(tmp_path: Path):
    file_path = str(tmp_path / "state.json")
    store = DailyStateStore(file_path=file_path, redis_key="test:key", save_throttle_s=30.0)
    store.save({"v": 1}, now_ts=1000.0, force=True)
    store.save({"v": 2}, now_ts=1010.0)
    loaded = store.load()
    assert loaded["v"] == 1

    store.save({"v": 3}, now_ts=1031.0)
    loaded = store.load()
    assert loaded["v"] == 3


def test_save_force_ignores_throttle(tmp_path: Path):
    file_path = str(tmp_path / "state.json")
    store = DailyStateStore(file_path=file_path, redis_key="test:key", save_throttle_s=30.0)
    store.save({"v": 1}, now_ts=1000.0, force=True)
    store.save({"v": 2}, now_ts=1001.0, force=True)
    loaded = store.load()
    assert loaded["v"] == 2


def test_ts_utc_added_to_saved_data(tmp_path: Path):
    file_path = str(tmp_path / "state.json")
    store = DailyStateStore(file_path=file_path, redis_key="test:key")
    store.save({"x": 1}, now_ts=1000.0, force=True)
    loaded = store.load()
    assert "ts_utc" in loaded
