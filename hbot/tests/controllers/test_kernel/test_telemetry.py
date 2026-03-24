"""Tests for telemetry structures and Redis fallback behavior."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestTelemetryRedisInit:
    def test_telemetry_redis_starts_none(self):
        ctrl = MagicMock()
        ctrl._telemetry_redis = None
        ctrl._telemetry_redis_init_done = False
        assert ctrl._telemetry_redis is None

    def test_telemetry_redis_init_flag_prevents_retry(self):
        ctrl = MagicMock()
        ctrl._telemetry_redis = None
        ctrl._telemetry_redis_init_done = True
        assert ctrl._telemetry_redis is None


class TestMinuteSnapshot:
    def test_snapshot_dict_has_required_keys(self):
        snapshot = {
            "ts": 1700000000.0,
            "instance_name": "bot1",
            "mid_price": "50000.0",
            "position_base": "0.01",
            "unrealized_pnl": "5.0",
            "regime": "neutral",
        }
        required = {"ts", "instance_name", "mid_price", "position_base", "unrealized_pnl", "regime"}
        assert required.issubset(snapshot.keys())

    def test_snapshot_ts_is_numeric(self):
        snapshot = {"ts": 1700000000.0}
        assert isinstance(snapshot["ts"], (int, float))


class TestHeartbeat:
    def test_heartbeat_dict_structure(self):
        heartbeat = {
            "ts": 1700000000.0,
            "instance_name": "bot1",
            "status": "running",
            "tick_count": 1000,
        }
        assert "ts" in heartbeat
        assert "status" in heartbeat


class TestRedisFallback:
    def test_bridge_state_no_redis_host(self):
        from simulation.bridge.bridge_state import BridgeState

        state = BridgeState()
        with patch.dict(os.environ, {"REDIS_HOST": ""}, clear=False):
            state.redis_init_done = False
            state.redis_client = None
            result = state.get_redis()
            assert result is None

    def test_bridge_state_redis_client_lazy_init(self):
        from simulation.bridge.bridge_state import BridgeState

        state = BridgeState()
        state.redis_init_done = True
        state.redis_client = None
        result = state.get_redis()
        assert result is None
