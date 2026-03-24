from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from simulation.bridge import hb_bridge


@pytest.fixture(autouse=True)
def _reset_bridge_state(monkeypatch):
    hb_bridge._bridge_state.reset()
    monkeypatch.delenv("PAPER_EXCHANGE_MODE", raising=False)
    monkeypatch.delenv("PAPER_EXCHANGE_MODE_BOT1", raising=False)
    yield
    hb_bridge._bridge_state.reset()


def _make_strategy(instance_name: str = "bot1"):
    ctrl = MagicMock()
    ctrl.config = SimpleNamespace(instance_name=instance_name, connector_name="test_conn", trading_pair="BTC-USDT")
    ctrl.id = "ctrl_1"
    ops_guard = SimpleNamespace(state=SimpleNamespace(value="running"))

    def _force_hard_stop(reason: str):
        ops_guard.state = SimpleNamespace(value="hard_stop")
        ops_guard.reason = reason
        return ops_guard.state

    ops_guard.force_hard_stop = MagicMock(side_effect=_force_hard_stop)
    ctrl._ops_guard = ops_guard

    strategy = MagicMock()
    strategy.controllers = {"ctrl_1": ctrl}
    strategy._paper_desk_v2_bridges = {}
    return strategy, ctrl


def _wire_single_event(mock_redis: MagicMock, payload: dict) -> None:
    mock_redis.xread.return_value = [("hb.paper_exchange.event.v1", [("1-0", {"payload": json.dumps(payload)})])]


def test_foreign_sync_state_processed_is_ignored() -> None:
    strategy, _ = _make_strategy(instance_name="bot1")
    mock_redis = MagicMock()
    _wire_single_event(
        mock_redis,
        {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-foreign-sync-ok",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "botX",
            "command_event_id": "cmd-foreign-sync-ok",
            "command": "sync_state",
            "status": "processed",
            "reason": "sync_state_accepted",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        },
    )
    hb_bridge._bridge_state.redis_client = mock_redis
    hb_bridge._bridge_state.redis_init_done = True

    with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
        hb_bridge._consume_paper_exchange_events(strategy)

    assert "bot1|test_conn|BTC-USDT" not in hb_bridge._bridge_state.sync_confirmed_keys
    assert "botX|test_conn|BTC-USDT" not in hb_bridge._bridge_state.sync_confirmed_keys


def test_foreign_sync_state_rejected_does_not_hard_stop_local_controller() -> None:
    strategy, ctrl = _make_strategy(instance_name="bot1")
    mock_redis = MagicMock()
    _wire_single_event(
        mock_redis,
        {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-foreign-sync-reject",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "botX",
            "command_event_id": "cmd-foreign-sync-reject",
            "command": "sync_state",
            "status": "rejected",
            "reason": "snapshot_mismatch",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        },
    )
    hb_bridge._bridge_state.redis_client = mock_redis
    hb_bridge._bridge_state.redis_init_done = True

    with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
        hb_bridge._consume_paper_exchange_events(strategy)

    ctrl._ops_guard.force_hard_stop.assert_not_called()
    assert "bot1|test_conn|BTC-USDT" not in hb_bridge._bridge_state.sync_timeout_hard_stop_keys
    assert "botX|test_conn|BTC-USDT" not in hb_bridge._bridge_state.sync_timeout_hard_stop_keys


def test_local_sync_state_rejected_still_forces_hard_stop() -> None:
    strategy, ctrl = _make_strategy(instance_name="bot1")
    mock_redis = MagicMock()
    _wire_single_event(
        mock_redis,
        {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-local-sync-reject",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-local-sync-reject",
            "command": "sync_state",
            "status": "rejected",
            "reason": "snapshot_mismatch",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        },
    )
    hb_bridge._bridge_state.redis_client = mock_redis
    hb_bridge._bridge_state.redis_init_done = True

    with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
        hb_bridge._consume_paper_exchange_events(strategy)

    ctrl._ops_guard.force_hard_stop.assert_called_once()
    assert "bot1|test_conn|BTC-USDT" in hb_bridge._bridge_state.sync_timeout_hard_stop_keys


def test_local_sync_state_expired_command_allows_republish_without_hard_stop() -> None:
    strategy, ctrl = _make_strategy(instance_name="bot1")
    mock_redis = MagicMock()
    _wire_single_event(
        mock_redis,
        {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-local-sync-expired",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-local-sync-expired",
            "command": "sync_state",
            "status": "rejected",
            "reason": "expired_command",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        },
    )
    hb_bridge._bridge_state.redis_client = mock_redis
    hb_bridge._bridge_state.redis_init_done = True
    sync_key = "bot1|test_conn|BTC-USDT"
    hb_bridge._bridge_state.sync_state_published_keys.add(sync_key)
    hb_bridge._bridge_state.sync_requested_at_ms_by_key[sync_key] = 1_000

    with patch.dict("os.environ", {"PAPER_EXCHANGE_MODE_BOT1": "active"}, clear=False):
        hb_bridge._consume_paper_exchange_events(strategy)

    ctrl._ops_guard.force_hard_stop.assert_not_called()
    assert sync_key not in hb_bridge._bridge_state.sync_state_published_keys
    assert sync_key not in hb_bridge._bridge_state.sync_requested_at_ms_by_key
    assert sync_key not in hb_bridge._bridge_state.sync_timeout_hard_stop_keys


def test_bridge_buy_with_paper_trade_suffix_routes_to_registered_bridge(monkeypatch) -> None:
    strategy, _ = _make_strategy(instance_name="bot1")
    strategy._paper_desk_v2_order_delegation_installed = False
    original_buy = MagicMock(return_value="original-buy")
    original_sell = MagicMock(return_value="original-sell")
    original_cancel = MagicMock(return_value=None)
    strategy.buy = original_buy
    strategy.sell = original_sell
    strategy.cancel = original_cancel

    desk = SimpleNamespace(
        submit_order=MagicMock(return_value=SimpleNamespace(order_id="paper_v2_order_1")),
        cancel_order=MagicMock(return_value=None),
    )
    instrument_id = SimpleNamespace(key="iid-test", trading_pair="BTC-USDT")
    monkeypatch.setattr(hb_bridge, "_fire_hb_events", lambda *args, **kwargs: None)
    monkeypatch.setattr(hb_bridge, "_publish_paper_exchange_command", lambda *args, **kwargs: "1-0")

    hb_bridge._install_order_delegation(strategy, desk, "test_conn", instrument_id)

    result = strategy.buy(
        "test_conn_paper_trade",
        "BTC-USDT",
        Decimal("0.01"),
        "limit",
        Decimal("100"),
    )

    assert result == "paper_v2_order_1"
    desk.submit_order.assert_called_once()
    original_buy.assert_not_called()


def test_sync_state_processed_hydrates_runtime_orders_from_service_snapshot(tmp_path, monkeypatch) -> None:
    strategy, ctrl = _make_strategy(instance_name="bot1")
    ctrl.executors_info = [SimpleNamespace(order_id="pe-sync-owned")]

    state_snapshot_path = tmp_path / "paper_exchange_state_snapshot_latest.json"
    state_snapshot_path.write_text(
        json.dumps(
            {
                "orders_total": 1,
                "orders": {
                    "pe-sync-owned": {
                        "order_id": "pe-sync-owned",
                        "instance_name": "bot1",
                        "connector_name": "test_conn",
                        "trading_pair": "BTC-USDT",
                        "side": "buy",
                        "order_type": "limit",
                        "amount_base": 0.01,
                        "price": 100.0,
                        "state": "working",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_redis.xrevrange.return_value = []
    _wire_single_event(
        mock_redis,
        {
            "schema_version": "1.0",
            "event_type": "paper_exchange_event",
            "event_id": "evt-local-sync-ok",
            "producer": "paper_exchange_service",
            "timestamp_ms": 1_000,
            "instance_name": "bot1",
            "command_event_id": "cmd-local-sync-ok",
            "command": "sync_state",
            "status": "processed",
            "reason": "sync_state_accepted",
            "connector_name": "test_conn",
            "trading_pair": "BTC-USDT",
            "metadata": {},
        },
    )
    hb_bridge._bridge_state.redis_client = mock_redis
    hb_bridge._bridge_state.redis_init_done = True

    with patch.dict(
        "os.environ",
        {
            "PAPER_EXCHANGE_MODE_BOT1": "active",
            "PAPER_EXCHANGE_STATE_SNAPSHOT_PATH": str(state_snapshot_path),
        },
        clear=False,
    ):
        hb_bridge._consume_paper_exchange_events(strategy)

    runtime_bucket = strategy._paper_exchange_runtime_orders["test_conn"]
    runtime_order = runtime_bucket["pe-sync-owned"]
    assert runtime_order.current_state == "working"
    assert runtime_order.is_open is True


def test_hydrate_runtime_orders_logs_snapshot_read_failure(tmp_path, monkeypatch) -> None:
    bad_snapshot_path = tmp_path / "paper_exchange_state_snapshot_latest.json"
    bad_snapshot_path.write_text("{invalid", encoding="utf-8")
    strategy, _ctrl = _make_strategy(instance_name="bot1")

    from simulation.bridge import paper_exchange_protocol as _pep

    with patch.object(_pep.logger, "warning") as warning_mock, patch.dict(
        "os.environ",
        {
            "PAPER_EXCHANGE_STATE_SNAPSHOT_PATH": str(bad_snapshot_path),
        },
        clear=False,
    ):
        hydrated = hb_bridge._hydrate_runtime_orders_from_state_snapshot(
            strategy,
            instance_name="bot1",
            connector_name="test_conn",
            trading_pair="BTC-USDT",
        )

    assert hydrated == []
    warning_mock.assert_called_once()


def test_paper_command_constraints_metadata_reads_trading_rule() -> None:
    rule = SimpleNamespace(
        min_order_size="0.01",
        min_notional="100",
        min_base_amount_increment="0.001",
        min_price_tick_size="0.5",
    )
    strategy = SimpleNamespace(
        get_trading_rules=lambda connector_name: {"BTC-USDT": rule},
    )

    metadata = hb_bridge._paper_command_constraints_metadata(strategy, "test_conn", "BTC-USDT")

    assert metadata == {
        "min_quantity": "0.01",
        "size_increment": "0.001",
        "price_increment": "0.5",
        "min_notional": "100",
    }
