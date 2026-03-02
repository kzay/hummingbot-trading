"""Tests for hb_bridge signal consumption and HARD_STOP kill_switch publishing."""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from controllers.paper_engine_v2 import hb_bridge
from controllers.paper_engine_v2.types import InstrumentId, OrderCanceled, OrderFilled, OrderRejected


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset all bridge state between tests."""
    hb_bridge._bridge_state.reset()
    yield
    hb_bridge._bridge_state.reset()


def _make_strategy_with_controller(instance_name="bot1", guard_state="running"):
    ctrl = MagicMock()
    ctrl.config = SimpleNamespace(instance_name=instance_name, connector_name="test_conn", trading_pair="BTC-USDT")
    ctrl.apply_execution_intent = MagicMock(return_value=(True, "ok"))
    ops_guard = SimpleNamespace(state=SimpleNamespace(value=guard_state))

    def _force_hard_stop(reason: str):
        ops_guard.state = SimpleNamespace(value="hard_stop")
        ops_guard.reason = reason
        return ops_guard.state

    ops_guard.force_hard_stop = MagicMock(side_effect=_force_hard_stop)
    ctrl._ops_guard = ops_guard
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
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
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
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

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
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

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
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

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
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        hb_bridge._consume_signals(strategy)

        assert hb_bridge._bridge_state.last_signal_id == "20-0"


class TestHardStopTransition:
    def test_first_hard_stop_publishes_kill_switch(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="hard_stop")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

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
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.reset_mock()

        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_not_called()

    def test_running_state_does_not_publish(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="running")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)

        mock_redis.xadd.assert_not_called()

    def test_transition_from_running_to_hard_stop(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="running")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_not_called()

        ctrl._ops_guard.state = SimpleNamespace(value="hard_stop")
        hb_bridge._check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_called_once()

    def test_no_redis_does_not_crash(self):
        strategy, _ = _make_strategy_with_controller(guard_state="hard_stop")
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True

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


class TestPaperExchangeShadowAdapter:
    def test_publish_command_skips_when_mode_disabled(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE": "disabled"}, clear=False):
            entry_id = hb_bridge._publish_paper_exchange_command(
                strategy,
                connector_name="test_conn",
                trading_pair="BTC-USDT",
                command="sync_state",
            )
        assert entry_id is None
        mock_redis.xadd.assert_not_called()

    def test_publish_command_emits_in_shadow_mode(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "123-0"
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE": "shadow"}, clear=False):
            entry_id = hb_bridge._publish_paper_exchange_command(
                strategy,
                connector_name="test_conn",
                trading_pair="BTC-USDT",
                command="submit_order",
                order_id="order-1",
                side="buy",
                order_type="limit",
                amount_base=Decimal("0.01"),
                price=Decimal("100000"),
            )
        assert entry_id == "123-0"
        mock_redis.xadd.assert_called_once()
        stream_name = mock_redis.xadd.call_args[0][0]
        payload_raw = mock_redis.xadd.call_args[0][1]["payload"]
        payload = json.loads(payload_raw)
        assert stream_name == "hb.paper_exchange.command.v1"
        assert payload["command"] == "submit_order"
        assert payload["connector_name"] == "test_conn"
        assert payload["metadata"]["paper_exchange_mode"] == "shadow"

    def test_sync_state_emitted_once_per_instance_connector_pair(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "200-0"
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE": "shadow"}, clear=False):
            hb_bridge._ensure_sync_state_command(strategy, "test_conn", "BTC-USDT")
            hb_bridge._ensure_sync_state_command(strategy, "test_conn", "BTC-USDT")
        assert mock_redis.xadd.call_count == 1


class TestPaperExchangeActiveAdapter:
    def test_sync_state_processed_marks_handshake_confirmed(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-sync-ok",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-sync-1",
            "command": "sync_state",
            "status": "processed",
            "reason": "sync_state_accepted",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("0-1", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)

        assert "bot1|test_conn|BTC-USDT" in hb_bridge._bridge_state.sync_confirmed_keys

    def test_consume_event_rejected_submit_maps_to_hb_reject(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-1",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-1",
            "command": "submit_order",
            "status": "rejected",
            "reason": "not_implemented_yet",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-1",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("1-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderRejected)
        assert fired_event.order_id == "ord-1"
        assert "paper_exchange:not_implemented_yet" in fired_event.reason
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", "ord-1")
        assert runtime_order is not None
        assert runtime_order.current_state == "failed"

    def test_consume_event_processed_cancel_maps_to_hb_cancel(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-2",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-2",
            "command": "cancel_order",
            "status": "processed",
            "reason": "ok",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-2",
            "metadata": {},
        }
        hb_bridge._upsert_runtime_order(
            strategy,
            connector_name="test_conn",
            order_id="ord-2",
            trading_pair="BTC-USDT",
            side="buy",
            order_type="limit",
            amount=Decimal("0.01"),
            price=Decimal("10000"),
            state="open",
        )
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("2-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderCanceled)
        assert fired_event.order_id == "ord-2"
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", "ord-2")
        assert runtime_order is not None
        assert runtime_order.current_state == "canceled"

    def test_consume_event_ignores_shadow_mode(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-3",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-3",
            "command": "submit_order",
            "status": "rejected",
            "reason": "not_implemented_yet",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-3",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("3-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "shadow"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_not_called()

    def test_active_buy_uses_command_path_without_local_desk_event(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "5-0"
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        hb_bridge._bridge_state.sync_confirmed_keys.add("bot1|test_conn|BTC-USDT")

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))

        assert isinstance(order_id, str)
        assert order_id.startswith("pe-")
        desk.submit_order.assert_not_called()
        mock_fire.assert_not_called()
        mock_redis.xadd.assert_called_once()
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", order_id)
        assert runtime_order is not None
        assert runtime_order.current_state == "pending_create"

    def test_active_buy_rejects_while_sync_pending(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "6-0"
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))

        assert isinstance(order_id, str)
        assert order_id.startswith("pe-")
        desk.submit_order.assert_not_called()
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderRejected)
        assert fired_event.reason == "paper_exchange_sync_pending"
        # Only sync_state command should be emitted while pending.
        assert mock_redis.xadd.call_count == 1
        payload_raw = mock_redis.xadd.call_args[0][1]["payload"]
        payload = json.loads(payload_raw)
        assert payload["command"] == "sync_state"

    def test_active_buy_timeout_forces_hard_stop(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "7-0"
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        sync_key = "bot1|test_conn|BTC-USDT"
        hb_bridge._bridge_state.sync_state_published_keys.add(sync_key)
        hb_bridge._bridge_state.sync_requested_at_ms_by_key[sync_key] = 1

        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_SYNC_TIMEOUT_MS": "10"},
            clear=False,
        ):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))

        assert isinstance(order_id, str)
        assert order_id.startswith("pe-")
        ctrl._ops_guard.force_hard_stop.assert_called()
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderRejected)
        assert fired_event.reason == "paper_exchange_sync_timeout"

    def test_submit_processed_updates_runtime_order_open(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        hb_bridge._upsert_runtime_order(
            strategy,
            connector_name="test_conn",
            order_id="ord-open",
            trading_pair="BTC-USDT",
            side="buy",
            order_type="limit",
            amount=Decimal("0.02"),
            price=Decimal("10000"),
            state="pending_create",
        )

        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-open",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-open",
            "command": "submit_order",
            "status": "processed",
            "reason": "accepted",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-open",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("4-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_not_called()
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", "ord-open")
        assert runtime_order is not None
        assert runtime_order.current_state == "open"

    def test_submit_processed_filled_maps_to_hb_fill(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        hb_bridge._upsert_runtime_order(
            strategy,
            connector_name="test_conn",
            order_id="ord-fill",
            trading_pair="BTC-USDT",
            side="buy",
            order_type="market",
            amount=Decimal("0.01"),
            price=Decimal("10000"),
            state="pending_create",
        )

        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-fill",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-fill",
            "command": "submit_order",
            "status": "processed",
            "reason": "order_filled_immediate",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-fill",
            "metadata": {
                "order_state": "filled",
                "side": "buy",
                "order_type": "market",
                "amount_base": "0.01",
                "price": "10000.0",
                "fill_price": "10000.0",
                "fill_amount_base": "0.01",
                "fill_fee_quote": "0",
                "is_maker": "0",
            },
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("5-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderFilled)
        assert fired_event.order_id == "ord-fill"
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", "ord-fill")
        assert runtime_order is not None
        assert runtime_order.current_state == "filled"

    def test_submit_processed_expired_maps_to_hb_reject(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        hb_bridge._upsert_runtime_order(
            strategy,
            connector_name="test_conn",
            order_id="ord-expired",
            trading_pair="BTC-USDT",
            side="buy",
            order_type="limit",
            amount=Decimal("0.01"),
            price=Decimal("10000"),
            state="pending_create",
        )

        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-expired",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-expired",
            "command": "submit_order",
            "status": "processed",
            "reason": "time_in_force_expired_no_fill",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-expired",
            "metadata": {"order_state": "expired", "amount_base": "0.01", "price": "10000.0"},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("6-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderRejected)
        assert fired_event.order_id == "ord-expired"
        assert "paper_exchange:time_in_force_expired_no_fill" in fired_event.reason
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", "ord-expired")
        assert runtime_order is not None
        assert runtime_order.current_state == "expired"

    def test_fill_lifecycle_event_maps_to_hb_fill(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }

        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-fill-life",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-fill-life",
            "command": "order_fill",
            "status": "processed",
            "reason": "partial_fill",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-life",
            "metadata": {
                "order_state": "partially_filled",
                "side": "sell",
                "order_type": "limit",
                "amount_base": "0.02",
                "price": "10000.0",
                "fill_price": "10001.0",
                "fill_amount_base": "0.01",
                "fill_fee_quote": "0.1",
                "remaining_amount_base": "0.01",
                "is_maker": "1",
            },
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("7-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                hb_bridge._consume_paper_exchange_events(strategy)
        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderFilled)
        assert fired_event.order_id == "ord-life"
        assert fired_event.fill_quantity == Decimal("0.01")
        runtime_order = hb_bridge._get_runtime_order_for_executor(strategy, "test_conn", "ord-life")
        assert runtime_order is not None
        assert runtime_order.current_state == "partial"
