"""Tests for DeskStateStore."""
from pathlib import Path
from decimal import Decimal
import pytest

from controllers.paper_engine_v2.state_store import DeskStateStore


class TestDeskStateStore:
    def test_save_and_load_file(self, tmp_path):
        store = DeskStateStore(file_path=str(tmp_path / "state.json"))
        data = {"balances": {"USDT": "1000"}, "positions": {}}
        store.save(data, now_ts=0.0, force=True)
        loaded = store.load()
        assert loaded is not None
        assert loaded["balances"]["USDT"] == "1000"

    def test_load_returns_none_when_empty(self, tmp_path):
        store = DeskStateStore(file_path=str(tmp_path / "nonexistent.json"))
        assert store.load() is None

    def test_save_throttle(self, tmp_path):
        store = DeskStateStore(file_path=str(tmp_path / "state.json"))
        store.save({"v": "1"}, now_ts=1000.0, force=True)  # non-zero ts
        store.save({"v": "2"}, now_ts=1010.0)  # within 30s throttle
        loaded = store.load()
        assert loaded["v"] == "1"  # second save was throttled

    def test_force_save_ignores_throttle(self, tmp_path):
        store = DeskStateStore(file_path=str(tmp_path / "state.json"))
        store.save({"v": "1"}, now_ts=0.0, force=True)
        store.save({"v": "2"}, now_ts=1.0, force=True)
        loaded = store.load()
        assert loaded["v"] == "2"

    def test_ts_utc_added(self, tmp_path):
        store = DeskStateStore(file_path=str(tmp_path / "state.json"))
        store.save({"x": "1"}, now_ts=0.0, force=True)
        loaded = store.load()
        assert "ts_utc" in loaded
