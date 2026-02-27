"""Tests for hb_bridge signal consumption and HARD_STOP kill_switch publishing."""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from controllers.paper_engine_v2 import hb_bridge


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset module-level state between tests."""
    hb_bridge._signal_redis_client = None
    hb_bridge._signal_redis_init_done = False
    hb_bridge._last_signal_id = "0-0"
    hb_bridge._prev_guard_states.clear()
    yield
    hb_bridge._signal_redis_client = None
    hb_bridge._signal_redis_init_done = False
    hb_bridge._last_signal_id = "0-0"
    hb_bridge._prev_guard_states.clear()


def _make_strategy_with_controller(instance_name="bot1", guard_state="running"):
    ctrl = MagicMock()
    ctrl.config = SimpleNamespace(instance_name=instance_name, connector_name="test_conn")
    ctrl.apply_execution_intent = MagicMock(return_value=(True, "ok"))
    ctrl._ops_guard = SimpleNamespace(state=SimpleNamespace(value=guard_state))
    ctrl.id = "ctrl_1"
    strategy = MagicMock()
    strategy.controllers = {"ctrl_1": ctrl}
    strategy._paper_desk_v2_bridges = {}
    return strategy, ctrl


class TestConsumeSignals:
    def test_no_redis_host_skips_silently(self):
        strategy, _ = _make_strategy_with_controller()
        with patch.dict("os.environ", {"REDIS_HOST": ""}, clear=False):
            hb_bridge._consume_signals(strategy)

    def test_redis_unavailable_does_not_crash(self):
        strategy, _ = _make_strategy_with_controller()
        mock_redis = MagicMock()
        mock_redis.xread.side_effect = ConnectionError("Redis down")
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True
        hb_bridge._consume_signals(strategy)

    def test_inventory_rebalance_routes_to_controller(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        signal_payload = {
            "signal_name": "inventory_rebalance",
            "signal_value": 0.45,
            "instance_name": "bot1",
        }
        mock_redis.xread.return_value = [
            ("hb.signal.v1", [("1-0", {"payload": json.dumps(signal_payload)})])
        ]
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._consume_signals(strategy)

        ctrl.apply_execution_intent.assert_called_once_with({
            "action": "set_target_base_pct",
            "target_base_pct": 0.45,
        })

    def test_non_inventory_signal_ignored(self):
        strategy, ctrl = _make_strategy_with_controller()
        mock_redis = MagicMock()
        signal_payload = {
            "signal_name": "some_other_signal",
            "signal_value": 0.5,
            "instance_name": "bot1",
        }
        mock_redis.xread.return_value = [
            ("hb.signal.v1", [("1-0", {"payload": json.dumps(signal_payload)})])
        ]
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._consume_signals(strategy)

        ctrl.apply_execution_intent.assert_not_called()

    def test_unknown_instance_name_ignored(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        signal_payload = {
            "signal_name": "inventory_rebalance",
            "signal_value": 0.5,
            "instance_name": "unknown_bot",
        }
        mock_redis.xread.return_value = [
            ("hb.signal.v1", [("1-0", {"payload": json.dumps(signal_payload)})])
        ]
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._consume_signals(strategy)

        ctrl.apply_execution_intent.assert_not_called()

    def test_last_signal_id_advances(self):
        strategy, _ = _make_strategy_with_controller()
        mock_redis = MagicMock()
        signal_payload = {
            "signal_name": "inventory_rebalance",
            "signal_value": 0.3,
            "instance_name": "bot1",
        }
        mock_redis.xread.return_value = [
            ("hb.signal.v1", [
                ("10-0", {"payload": json.dumps(signal_payload)}),
                ("20-0", {"payload": json.dumps(signal_payload)}),
            ])
        ]
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._consume_signals(strategy)

        assert hb_bridge._last_signal_id == "20-0"


class TestHardStopTransition:
    def test_first_hard_stop_publishes_kill_switch(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="hard_stop")
        mock_redis = MagicMock()
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        stream_name = call_args[0][0]
        payload_raw = call_args[0][1]["payload"]
        payload = json.loads(payload_raw)
        assert stream_name == "hb.execution_intent.v1"
        assert payload["action"] == "kill_switch"

    def test_second_hard_stop_tick_does_not_republish(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="hard_stop")
        mock_redis = MagicMock()
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.reset_mock()

        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_not_called()

    def test_running_state_does_not_publish(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="running")
        mock_redis = MagicMock()
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)

        mock_redis.xadd.assert_not_called()

    def test_transition_from_running_to_hard_stop(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="running")
        mock_redis = MagicMock()
        hb_bridge._signal_redis_client = mock_redis
        hb_bridge._signal_redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_not_called()

        ctrl._ops_guard.state = SimpleNamespace(value="hard_stop")
        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_called_once()

    def test_no_redis_does_not_crash(self):
        strategy, _ = _make_strategy_with_controller(guard_state="hard_stop")
        hb_bridge._signal_redis_client = None
        hb_bridge._signal_redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)


class TestFindControllerByInstance:
    def test_finds_matching_controller(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        result = hb_bridge._find_controller_by_instance(strategy, "bot1")
        assert result is ctrl

    def test_returns_none_for_unknown(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        result = hb_bridge._find_controller_by_instance(strategy, "unknown")
        assert result is None

    def test_empty_controllers_returns_none(self):
        strategy = MagicMock()
        strategy.controllers = {}
        result = hb_bridge._find_controller_by_instance(strategy, "bot1")
        assert result is None
