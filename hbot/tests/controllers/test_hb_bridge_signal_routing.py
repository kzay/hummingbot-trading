"""Tests for hb_bridge signal consumption and HARD_STOP kill_switch publishing."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from controllers.paper_engine_v2 import hb_bridge
from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
from controllers.paper_engine_v2.signal_consumer import (
    _consume_signals as _consume_signals_impl,
    _check_hard_stop_transitions as _check_hard_stop_impl,
)
from controllers.paper_engine_v2.types import InstrumentId, OrderCanceled, OrderFilled, OrderRejected, OrderSide, PositionAction
from tests.controllers.test_paper_engine_v2.conftest import BTC_PERP, make_spec


def _consume_signals(strategy):
    _consume_signals_impl(strategy, hb_bridge._bridge_state)


def _check_hard_stop_transitions(strategy):
    _check_hard_stop_impl(strategy, hb_bridge._bridge_state)


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Reset all bridge state between tests."""
    hb_bridge._bridge_state.reset()
    for key in (
        "PAPER_EXCHANGE_SERVICE_ONLY",
        "PAPER_EXCHANGE_SERVICE_ONLY_BOT1",
        "PAPER_EXCHANGE_SERVICE_ONLY_BOT2",
        "PAPER_EXCHANGE_SERVICE_ONLY_BOT3",
        "PAPER_EXCHANGE_SERVICE_ONLY_BOT4",
        "PAPER_EXCHANGE_SERVICE_ONLY_BOT5",
        "PAPER_EXCHANGE_SERVICE_ONLY_BOT6",
    ):
        monkeypatch.delenv(key, raising=False)
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
            _consume_signals(strategy)

    def test_redis_unavailable_does_not_crash(self):
        strategy, _ = _make_strategy_with_controller()
        mock_redis = MagicMock()
        mock_redis.xread.side_effect = ConnectionError("Redis down")
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        _consume_signals(strategy)

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

        _consume_signals(strategy)

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

        _consume_signals(strategy)

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

        _consume_signals(strategy)

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

        _consume_signals(strategy)

        assert hb_bridge._bridge_state.last_signal_id == "20-0"


class TestHardStopTransition:
    def test_first_hard_stop_publishes_kill_switch(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="hard_stop")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        _check_hard_stop_transitions(strategy)

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

        _check_hard_stop_transitions(strategy)
        mock_redis.xadd.reset_mock()

        _check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_not_called()

    def test_running_state_does_not_publish(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="running")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        _check_hard_stop_transitions(strategy)

        mock_redis.xadd.assert_not_called()

    def test_transition_from_running_to_hard_stop(self):
        strategy, ctrl = _make_strategy_with_controller(guard_state="running")
        mock_redis = MagicMock()
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        _check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_not_called()

        ctrl._ops_guard.state = SimpleNamespace(value="hard_stop")
        _check_hard_stop_transitions(strategy)
        mock_redis.xadd.assert_called_once()

    def test_no_redis_does_not_crash(self):
        strategy, _ = _make_strategy_with_controller(guard_state="hard_stop")
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True

        _check_hard_stop_transitions(strategy)


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

    def test_active_cancel_all_retry_reuses_command_event_id_within_ttl(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ["401-0", "402-0"]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        metadata = {
            "operator": "hb_bridge",
            "reason": "retry_test",
            "change_ticket": "auto",
            "trace_id": "trace-123",
        }
        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_CANCEL_ALL_RETRY_TTL_S": "2.0"},
            clear=False,
        ):
            first_entry_id = hb_bridge._publish_paper_exchange_command(
                strategy,
                connector_name="test_conn",
                trading_pair="BTC-USDT",
                command="cancel_all",
                metadata=metadata,
            )
            second_entry_id = hb_bridge._publish_paper_exchange_command(
                strategy,
                connector_name="test_conn",
                trading_pair="BTC-USDT",
                command="cancel_all",
                metadata=metadata,
            )
        assert first_entry_id == "401-0"
        assert second_entry_id == "402-0"
        assert mock_redis.xadd.call_count == 2
        first_payload = json.loads(mock_redis.xadd.call_args_list[0][0][1]["payload"])
        second_payload = json.loads(mock_redis.xadd.call_args_list[1][0][1]["payload"])
        assert first_payload["command"] == "cancel_all"
        assert second_payload["command"] == "cancel_all"
        assert first_payload["event_id"] == second_payload["event_id"]

    def test_active_cancel_all_retry_generates_new_command_event_id_when_ttl_disabled(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ["403-0", "404-0"]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        metadata = {
            "operator": "hb_bridge",
            "reason": "retry_test",
            "change_ticket": "auto",
            "trace_id": "trace-123",
        }
        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_CANCEL_ALL_RETRY_TTL_S": "0"},
            clear=False,
        ):
            first_entry_id = hb_bridge._publish_paper_exchange_command(
                strategy,
                connector_name="test_conn",
                trading_pair="BTC-USDT",
                command="cancel_all",
                metadata=metadata,
            )
            second_entry_id = hb_bridge._publish_paper_exchange_command(
                strategy,
                connector_name="test_conn",
                trading_pair="BTC-USDT",
                command="cancel_all",
                metadata=metadata,
            )
        assert first_entry_id == "403-0"
        assert second_entry_id == "404-0"
        assert mock_redis.xadd.call_count == 2
        first_payload = json.loads(mock_redis.xadd.call_args_list[0][0][1]["payload"])
        second_payload = json.loads(mock_redis.xadd.call_args_list[1][0][1]["payload"])
        assert first_payload["event_id"] != second_payload["event_id"]

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


class TestPaperExchangeModeResolution:
    def test_auto_mode_resolves_active_when_service_heartbeat_is_fresh(self):
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [("1700000000000-0", {"payload": "{}"})]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch("controllers.paper_engine_v2.hb_bridge.time.time", return_value=1700000000.5):
            with patch.dict(
                "os.environ",
                {
                    "PAPER_EXCHANGE_MODE": "auto",
                    "PAPER_EXCHANGE_AUTO_MAX_HEARTBEAT_AGE_MS": "2000",
                },
                clear=False,
            ):
                mode = hb_bridge._paper_exchange_mode_for_instance("bot1")
        assert mode == "active"

    def test_auto_mode_falls_back_to_shadow_when_service_unavailable(self):
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict(
            "os.environ",
            {
                "PAPER_EXCHANGE_MODE": "auto",
                "PAPER_EXCHANGE_AUTO_FALLBACK": "shadow",
            },
            clear=False,
        ):
            mode = hb_bridge._paper_exchange_mode_for_instance("bot1")
        assert mode == "shadow"

    def test_auto_mode_uses_short_cache_to_avoid_repeated_redis_probes(self):
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [("1700000000000-0", {"payload": "{}"})]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch("controllers.paper_engine_v2.hb_bridge.time.time", return_value=1700000000.5):
            with patch.dict(
                "os.environ",
                {
                    "PAPER_EXCHANGE_MODE": "auto",
                    "PAPER_EXCHANGE_AUTO_MAX_HEARTBEAT_AGE_MS": "2000",
                    "PAPER_EXCHANGE_AUTO_CACHE_MS": "60000",
                },
                clear=False,
            ):
                first = hb_bridge._paper_exchange_mode_for_instance("bot1")
                second = hb_bridge._paper_exchange_mode_for_instance("bot1")
        assert first == "active"
        assert second == "active"
        assert mock_redis.xrevrange.call_count == 1

    def test_service_only_flag_overrides_shadow_to_active(self):
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict(
            "os.environ",
            {
                "PAPER_EXCHANGE_MODE": "shadow",
                "PAPER_EXCHANGE_SERVICE_ONLY": "true",
            },
            clear=False,
        ):
            mode = hb_bridge._paper_exchange_mode_for_instance("bot1")
        assert mode == "active"

    def test_service_only_auto_mode_fails_closed_when_service_unavailable(self):
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict(
            "os.environ",
            {
                "PAPER_EXCHANGE_MODE": "auto",
                "PAPER_EXCHANGE_AUTO_FALLBACK": "shadow",
                "PAPER_EXCHANGE_SERVICE_ONLY": "true",
            },
            clear=False,
        ):
            mode = hb_bridge._paper_exchange_mode_for_instance("bot1")
        assert mode == "active"

    def test_service_only_per_instance_override_can_disable_strict_path(self):
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict(
            "os.environ",
            {
                "PAPER_EXCHANGE_MODE": "shadow",
                "PAPER_EXCHANGE_SERVICE_ONLY": "true",
                "PAPER_EXCHANGE_SERVICE_ONLY_BOT1": "false",
            },
            clear=False,
        ):
            mode = hb_bridge._paper_exchange_mode_for_instance("bot1")
        assert mode == "shadow"


class TestPaperExchangeActiveAdapter:
    def test_consume_bootstraps_cursor_from_latest_stream_entry_when_missing(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_redis.xrevrange.return_value = [("42-0", {"payload": "{}"})]
        mock_redis.xread.return_value = []
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)

        assert hb_bridge._bridge_state.last_paper_exchange_event_id == "42-0"
        mock_redis.xread.assert_called_once_with({"hb.paper_exchange.event.v1": "42-0"}, count=200, block=0)
        mock_redis.set.assert_called_with("paper_exchange:last_event_id:bot1", "42-0")


def test_patch_connector_balances_exposes_hedge_leg_position_reads() -> None:
    portfolio = PaperPortfolio({"USDT": Decimal("5000"), "BTC": Decimal("0")}, PortfolioConfig())
    spec = make_spec(BTC_PERP)
    portfolio.settle_fill(
        instrument_id=BTC_PERP,
        side=OrderSide.BUY,
        quantity=Decimal("1.0"),
        price=Decimal("100"),
        fee=Decimal("0"),
        source_bot="test",
        now_ns=1_000_000_000,
        spec=spec,
        leverage=5,
        position_action=PositionAction.OPEN_LONG,
        position_mode="HEDGE",
    )
    portfolio.settle_fill(
        instrument_id=BTC_PERP,
        side=OrderSide.SELL,
        quantity=Decimal("0.4"),
        price=Decimal("105"),
        fee=Decimal("0"),
        source_bot="test",
        now_ns=1_000_000_100,
        spec=spec,
        leverage=5,
        position_action=PositionAction.OPEN_SHORT,
        position_mode="HEDGE",
    )

    desk = SimpleNamespace(portfolio=portfolio)
    connector = SimpleNamespace(
        get_balance=lambda _asset: Decimal("0"),
        get_available_balance=lambda _asset: Decimal("0"),
        ready=lambda: False,
        get_position=lambda *_args, **_kwargs: None,
        account_positions=lambda *_args, **_kwargs: {},
    )

    hb_bridge._patch_connector_balances(connector, desk, BTC_PERP)

    long_pos = connector.get_position("BTC-USDT", position_action=PositionAction.OPEN_LONG)
    short_pos = connector.get_position("BTC-USDT", position_action=PositionAction.OPEN_SHORT)
    account_positions = connector.account_positions()

    assert long_pos.amount == Decimal("1.0")
    assert short_pos.amount == Decimal("-0.4")
    assert account_positions["BTC-USDT"]["amount"] == Decimal("0.6")
    assert account_positions["BTC-USDT"]["long_amount"] == Decimal("1.0")
    assert account_positions["BTC-USDT"]["short_amount"] == Decimal("-0.4")

    def test_consume_uses_persisted_cursor_and_advances_storage(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-sync-ok",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-sync-2",
            "command": "sync_state",
            "status": "processed",
            "reason": "sync_state_accepted",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        }
        mock_redis.get.return_value = "10-0"
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("11-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)

        mock_redis.xread.assert_called_once_with({"hb.paper_exchange.event.v1": "10-0"}, count=200, block=0)
        mock_redis.set.assert_called_with("paper_exchange:last_event_id:bot1", "11-0")
        assert hb_bridge._bridge_state.last_paper_exchange_event_id == "11-0"

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

    def test_sync_state_rejected_in_active_mode_forces_hard_stop(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-sync-reject",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-sync-reject",
            "command": "sync_state",
            "status": "rejected",
            "reason": "snapshot_mismatch",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("0-2", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)

        ctrl._ops_guard.force_hard_stop.assert_called_once()
        hard_stop_reason = ctrl._ops_guard.force_hard_stop.call_args[0][0]
        assert "paper_exchange_sync_failed:snapshot_mismatch" in hard_stop_reason
        assert "bot1|test_conn|BTC-USDT" in hb_bridge._bridge_state.sync_timeout_hard_stop_keys

    def test_sync_state_for_other_instance_does_not_confirm_local_key(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "101-0"
        payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-sync-botx",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "botX",
            "command_event_id": "cmd-sync-botx",
            "command": "sync_state",
            "status": "processed",
            "reason": "sync_state_accepted",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("0-3", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)
            gate_ready, gate_reason = hb_bridge._active_sync_gate(strategy, "test_conn", "BTC-USDT")

        assert "botX|test_conn|BTC-USDT" in hb_bridge._bridge_state.sync_confirmed_keys
        assert "bot1|test_conn|BTC-USDT" not in hb_bridge._bridge_state.sync_confirmed_keys
        assert (gate_ready, gate_reason) == (False, "paper_exchange_sync_pending")

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

    def test_active_buy_retry_reuses_order_id_within_ttl(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ["11-0", "12-0"]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        hb_bridge._bridge_state.sync_confirmed_keys.add("bot1|test_conn|BTC-USDT")

        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_SUBMIT_RETRY_TTL_S": "2.0"},
            clear=False,
        ):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                first_order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))
                second_order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))

        assert first_order_id == second_order_id
        mock_fire.assert_not_called()
        assert mock_redis.xadd.call_count == 2
        first_payload = json.loads(mock_redis.xadd.call_args_list[0][0][1]["payload"])
        second_payload = json.loads(mock_redis.xadd.call_args_list[1][0][1]["payload"])
        assert first_payload["order_id"] == first_order_id
        assert second_payload["order_id"] == first_order_id

    def test_active_buy_retry_generates_new_order_id_when_retry_ttl_disabled(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ["13-0", "14-0"]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        hb_bridge._bridge_state.sync_confirmed_keys.add("bot1|test_conn|BTC-USDT")

        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_SUBMIT_RETRY_TTL_S": "0"},
            clear=False,
        ):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                first_order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))
                second_order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))

        assert first_order_id != second_order_id
        mock_fire.assert_not_called()
        assert mock_redis.xadd.call_count == 2

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

    def test_active_cancel_rejects_while_sync_pending(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "8-0"
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                strategy.cancel("test_conn", "BTC-USDT", "ord-cancel-1")

        mock_fire.assert_called_once()
        fired_event = mock_fire.call_args[0][2]
        assert isinstance(fired_event, OrderRejected)
        assert fired_event.order_id == "ord-cancel-1"
        assert fired_event.reason == "paper_exchange_sync_pending"
        # Only sync_state command should be emitted while pending.
        assert mock_redis.xadd.call_count == 1
        payload_raw = mock_redis.xadd.call_args[0][1]["payload"]
        payload = json.loads(payload_raw)
        assert payload["command"] == "sync_state"

    def test_active_cancel_retry_reuses_command_event_id_within_ttl(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ["15-0", "16-0"]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        hb_bridge._bridge_state.sync_confirmed_keys.add("bot1|test_conn|BTC-USDT")

        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_CANCEL_RETRY_TTL_S": "2.0"},
            clear=False,
        ):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                strategy.cancel("test_conn", "BTC-USDT", "ord-cancel-retry-1")
                strategy.cancel("test_conn", "BTC-USDT", "ord-cancel-retry-1")

        mock_fire.assert_not_called()
        assert mock_redis.xadd.call_count == 2
        first_payload = json.loads(mock_redis.xadd.call_args_list[0][0][1]["payload"])
        second_payload = json.loads(mock_redis.xadd.call_args_list[1][0][1]["payload"])
        assert first_payload["command"] == "cancel_order"
        assert second_payload["command"] == "cancel_order"
        assert first_payload["event_id"] == second_payload["event_id"]
        assert first_payload["order_id"] == "ord-cancel-retry-1"
        assert second_payload["order_id"] == "ord-cancel-retry-1"

    def test_active_cancel_retry_generates_new_command_event_id_when_retry_ttl_disabled(self):
        strategy, _ = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ["17-0", "18-0"]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        hb_bridge._bridge_state.sync_confirmed_keys.add("bot1|test_conn|BTC-USDT")

        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_CANCEL_RETRY_TTL_S": "0"},
            clear=False,
        ):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                strategy.cancel("test_conn", "BTC-USDT", "ord-cancel-retry-2")
                strategy.cancel("test_conn", "BTC-USDT", "ord-cancel-retry-2")

        mock_fire.assert_not_called()
        assert mock_redis.xadd.call_count == 2
        first_payload = json.loads(mock_redis.xadd.call_args_list[0][0][1]["payload"])
        second_payload = json.loads(mock_redis.xadd.call_args_list[1][0][1]["payload"])
        assert first_payload["event_id"] != second_payload["event_id"]

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

    def test_active_buy_publish_failure_applies_soft_pause_intent(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_order_delegation_installed = False
        strategy.buy = MagicMock(return_value="orig-buy")
        strategy.sell = MagicMock(return_value="orig-sell")
        strategy.cancel = MagicMock(return_value=None)
        desk = MagicMock()
        iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        hb_bridge._install_order_delegation(strategy, desk, "test_conn", iid)

        mock_redis = MagicMock()
        mock_redis.xadd.return_value = None
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True
        hb_bridge._bridge_state.sync_confirmed_keys.add("bot1|test_conn|BTC-USDT")

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            with patch.object(hb_bridge, "_fire_hb_events") as mock_fire:
                order_id = strategy.buy("test_conn", "BTC-USDT", Decimal("0.01"), "limit", Decimal("10000"))

        assert isinstance(order_id, str)
        assert order_id.startswith("pe-")
        mock_fire.assert_called_once()
        ctrl.apply_execution_intent.assert_called()
        intent = ctrl.apply_execution_intent.call_args[0][0]
        assert intent["action"] == "soft_pause"
        assert "paper_exchange_soft_pause:service_down:command_publish_failed" in str(
            intent.get("metadata", {}).get("reason", "")
        )

    def test_consume_rejected_stale_market_applies_soft_pause_policy(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
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
            "event_id": "evt-stale-1",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-stale-1",
            "command": "submit_order",
            "status": "rejected",
            "reason": "stale_market_snapshot",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-stale-1",
            "metadata": {},
        }
        mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("30-0", {"payload": json.dumps(payload)})])]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)

        ctrl.apply_execution_intent.assert_called()
        intent = ctrl.apply_execution_intent.call_args[0][0]
        assert intent["action"] == "soft_pause"
        assert "paper_exchange_soft_pause:stale_feed:stale_market_snapshot" in str(
            intent.get("metadata", {}).get("reason", "")
        )

    def test_repeated_active_failures_escalate_to_hard_stop(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        mock_redis = MagicMock()
        payload_1 = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-stale-2",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-stale-2",
            "command": "submit_order",
            "status": "rejected",
            "reason": "stale_market_snapshot",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-stale-2",
            "metadata": {},
        }
        payload_2 = dict(payload_1)
        payload_2["event_id"] = "evt-stale-3"
        payload_2["command_event_id"] = "cmd-stale-3"
        payload_2["order_id"] = "ord-stale-3"
        mock_redis.xread.return_value = [
            (
                "hb.paper_exchange.event.v1",
                [
                    ("31-0", {"payload": json.dumps(payload_1)}),
                    ("32-0", {"payload": json.dumps(payload_2)}),
                ],
            )
        ]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict(
            "os.environ",
            {"PAPER_EXCHANGE_MODE_BOT1": "active", "PAPER_EXCHANGE_FAILURE_HARD_STOP_STREAK": "2"},
            clear=False,
        ):
            hb_bridge._consume_paper_exchange_events(strategy)

        ctrl._ops_guard.force_hard_stop.assert_called()
        hard_stop_reason = ctrl._ops_guard.force_hard_stop.call_args[0][0]
        assert "paper_exchange_recovery_loop:stale_feed:stale_market_snapshot" in hard_stop_reason

    def test_processed_event_resumes_after_soft_pause_failure(self):
        strategy, ctrl = _make_strategy_with_controller(instance_name="bot1")
        strategy._paper_desk_v2_bridges = {
            "test_conn": {
                "desk": MagicMock(),
                "instrument_id": InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp"),
            }
        }
        mock_redis = MagicMock()
        stale_payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-stale-4",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-stale-4",
            "command": "submit_order",
            "status": "rejected",
            "reason": "stale_market_snapshot",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-stale-4",
            "metadata": {},
        }
        processed_payload = {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-ok-1",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_100,
            "instance_name": "bot1",
            "command_event_id": "cmd-ok-1",
            "command": "cancel_order",
            "status": "processed",
            "reason": "order_cancelled",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-stale-4",
            "metadata": {},
        }
        mock_redis.xread.side_effect = [
            [("hb.paper_exchange.event.v1", [("33-0", {"payload": json.dumps(stale_payload)})])],
            [("hb.paper_exchange.event.v1", [("34-0", {"payload": json.dumps(processed_payload)})])],
        ]
        hb_bridge._bridge_state.redis_client = mock_redis
        hb_bridge._bridge_state.redis_init_done = True

        with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
            hb_bridge._consume_paper_exchange_events(strategy)
            hb_bridge._consume_paper_exchange_events(strategy)

        actions = [call.args[0].get("action") for call in ctrl.apply_execution_intent.call_args_list]
        assert "soft_pause" in actions
        assert "resume" in actions

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


class TestExecutorInflightCompatibility:
    @staticmethod
    def _install_fake_executor_base(monkeypatch) -> type:
        hummingbot_mod = ModuleType("hummingbot")
        strategy_mod = ModuleType("hummingbot.strategy_v2")
        executors_mod = ModuleType("hummingbot.strategy_v2.executors")
        executor_base_mod = ModuleType("hummingbot.strategy_v2.executors.executor_base")

        class FakeExecutorBase:
            _epp_v2_trading_rules_fallback_enabled = False
            _epp_v2_inflight_fallback_enabled = False

            def __init__(self) -> None:
                self.connectors = {}
                self.strategy = None

            def get_trading_rules(self, connector_name: str, trading_pair: str):
                return SimpleNamespace(trading_pair=trading_pair, connector_name=connector_name)

            def get_in_flight_order(self, connector_name: str, order_id: str):
                connector = self.connectors.get(connector_name)
                if connector is None:
                    return None
                tracker = getattr(connector, "_order_tracker", None)
                if tracker is None:
                    return None
                return tracker.fetch_order(client_order_id=order_id)

        executor_base_mod.ExecutorBase = FakeExecutorBase
        executors_mod.executor_base = executor_base_mod
        strategy_mod.executors = executors_mod
        hummingbot_mod.strategy_v2 = strategy_mod

        monkeypatch.setitem(sys.modules, "hummingbot", hummingbot_mod)
        monkeypatch.setitem(sys.modules, "hummingbot.strategy_v2", strategy_mod)
        monkeypatch.setitem(sys.modules, "hummingbot.strategy_v2.executors", executors_mod)
        monkeypatch.setitem(sys.modules, "hummingbot.strategy_v2.executors.executor_base", executor_base_mod)
        return FakeExecutorBase

    def test_executor_inflight_fallback_uses_runtime_store(self, monkeypatch) -> None:
        fake_executor_cls = self._install_fake_executor_base(monkeypatch)
        hb_bridge._patch_executor_base()

        strategy = SimpleNamespace()
        hb_bridge._upsert_runtime_order(
            strategy,
            connector_name="test_conn",
            order_id="ord-compat",
            trading_pair="BTC-USDT",
            side="buy",
            order_type="limit",
            amount=Decimal("0.01"),
            price=Decimal("10000"),
            state="open",
        )

        tracker = MagicMock()
        tracker.fetch_order.return_value = None
        connector = SimpleNamespace(_order_tracker=tracker)
        executor = fake_executor_cls()
        executor.connectors = {"test_conn_paper_trade": connector}
        executor.strategy = strategy

        resolved = executor.get_in_flight_order("test_conn_paper_trade", "ord-compat")
        assert resolved is not None
        assert getattr(resolved, "order_id", "") == "ord-compat"
        tracker.fetch_order.assert_not_called()

    def test_executor_inflight_fallback_returns_none_when_missing(self, monkeypatch) -> None:
        fake_executor_cls = self._install_fake_executor_base(monkeypatch)
        hb_bridge._patch_executor_base()

        tracker = MagicMock()
        tracker.fetch_order.side_effect = RuntimeError("tracker_miss")
        connector = SimpleNamespace(_order_tracker=tracker)
        executor = fake_executor_cls()
        executor.connectors = {"test_conn": connector}
        executor.strategy = SimpleNamespace()

        resolved = executor.get_in_flight_order("test_conn", "ord-missing")
        assert resolved is None
        tracker.fetch_order.assert_called_once_with(client_order_id="ord-missing")
