from __future__ import annotations

import importlib
import sys
import types
from enum import Enum
from types import SimpleNamespace
from unittest.mock import Mock, patch


def _install_import_stubs() -> None:
    def _ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    _ensure_module("hummingbot")
    _ensure_module("hummingbot.client")
    hb_app_module = _ensure_module("hummingbot.client.hummingbot_application")
    interface_utils = _ensure_module("hummingbot.client.ui.interface_utils")
    _ensure_module("hummingbot.client.ui")
    connector_manager = _ensure_module("hummingbot.core.connector_manager")
    _ensure_module("hummingbot.core")
    connector_base = _ensure_module("hummingbot.connector.connector_base")
    _ensure_module("hummingbot.connector")
    events = _ensure_module("hummingbot.core.event.events")
    _ensure_module("hummingbot.core.event")
    data_types = _ensure_module("hummingbot.data_feed.candles_feed.data_types")
    _ensure_module("hummingbot.data_feed")
    _ensure_module("hummingbot.data_feed.candles_feed")
    strategy_base = _ensure_module("hummingbot.strategy.strategy_v2_base")
    _ensure_module("hummingbot.strategy")
    models_base = _ensure_module("hummingbot.strategy_v2.models.base")
    models_actions = _ensure_module("hummingbot.strategy_v2.models.executor_actions")
    _ensure_module("hummingbot.strategy_v2")
    _ensure_module("hummingbot.strategy_v2.models")
    hb_bridge = _ensure_module("simulation.bridge.hb_bridge")
    _ensure_module("controllers")
    _ensure_module("simulation")
    preflight = _ensure_module("services.common.preflight")

    async def _noop_async(*args, **kwargs):
        return None

    class _ConnectorManager:
        async def update_connector_balances(self, connector_name):
            return None

    class _ConnectorBase:
        pass

    class _MarketOrderFailureEvent:
        pass

    class _CandlesConfig:
        pass

    class _StrategyV2Base:
        def __init__(self, *args, **kwargs):
            self.config = kwargs.get("config")
            self.connectors = kwargs.get("connectors", {})
            self.controllers = {}

    class _StrategyV2ConfigBase:
        pass

    class _RunnableStatus(Enum):
        RUNNING = "running"
        TERMINATED = "terminated"

    class _CreateExecutorAction:
        pass

    class _StopExecutorAction:
        pass

    class _HummingbotApplication:
        pass

    hb_app_module.HummingbotApplication = _HummingbotApplication
    hb_app_module.start_trade_monitor = _noop_async
    interface_utils.start_trade_monitor = _noop_async
    connector_manager.ConnectorManager = _ConnectorManager
    connector_base.ConnectorBase = _ConnectorBase
    events.MarketOrderFailureEvent = _MarketOrderFailureEvent
    data_types.CandlesConfig = _CandlesConfig
    strategy_base.StrategyV2Base = _StrategyV2Base
    strategy_base.StrategyV2ConfigBase = _StrategyV2ConfigBase
    models_base.RunnableStatus = _RunnableStatus
    models_actions.CreateExecutorAction = _CreateExecutorAction
    models_actions.StopExecutorAction = _StopExecutorAction
    hb_bridge._canonical_name = lambda name: str(name).replace("_paper_trade", "")
    hb_bridge._paper_exchange_mode_for_instance = lambda *a, **kw: None
    hb_bridge.enable_framework_paper_compat_fallbacks = lambda: None
    hb_bridge.install_paper_desk_bridge = lambda *args, **kwargs: None
    preflight.run_controller_preflight = lambda *args, **kwargs: []


def _controller_cls():
    _install_import_stubs()
    module = importlib.import_module("scripts.shared.v2_with_controllers")
    return module.V2WithControllers


class _FakeController:
    def __init__(self, state: str, risk_reasons: str):
        self._state = state
        self._risk_reasons = risk_reasons
        self.config = SimpleNamespace(instance_name="bot1")

    def set_status(self, state: str, risk_reasons: str) -> None:
        self._state = state
        self._risk_reasons = risk_reasons

    def get_custom_info(self):
        return {"state": self._state, "risk_reasons": self._risk_reasons}


def _build_runner(controller: _FakeController):
    logger = SimpleNamespace(error=Mock(), info=Mock())
    return SimpleNamespace(
        _bus_publisher=object(),
        _bus_client=SimpleNamespace(xadd=Mock()),
        controllers={"ctrl_1": controller},
        _hard_stop_kill_switch_last_reason_by_controller={},
        _hard_stop_kill_switch_last_ts_by_controller={},
        _hard_stop_kill_switch_latched_by_controller={},
        _hard_stop_kill_switch_republish_s=300.0,
        _hard_stop_clear_candidate_since_by_controller={},
        _hard_stop_resume_last_ts_by_controller={},
        _hard_stop_auto_resume_on_clear=False,
        _hard_stop_clear_cooldown_s=30.0,
        config=SimpleNamespace(script_file_name="v2_with_controllers.py"),
        logger=lambda: logger,
    )


def test_collect_open_orders_snapshot_includes_paper_desk_orders():
    controller_cls = _controller_cls()
    controller = SimpleNamespace(
        config=SimpleNamespace(
            connector_name="bitget_perpetual",
            trading_pair="BTC-USDT",
            instance_name="bot1",
        )
    )
    paper_order = SimpleNamespace(
        order_id="paper_v2_91",
        client_order_id="paper_v2_91",
        trading_pair="BTC-USDT",
        trade_type=SimpleNamespace(name="BUY", value="BUY"),
        side=SimpleNamespace(value="buy"),
        price="68356.1",
        amount="0.001",
        quantity="0.001",
        remaining_quantity="0.001",
        created_at_ns=1_700_000_000_000_000_000,
        source_bot="bitget_perpetual",
    )
    connector = SimpleNamespace(get_open_orders=lambda: [paper_order])
    runner = SimpleNamespace(
        controllers={"ctrl_1": controller},
        connectors={"bitget_perpetual": connector},
        _paper_exchange_runtime_orders={},
    )
    runner._iter_connector_open_orders = types.MethodType(
        controller_cls._iter_connector_open_orders, runner
    )
    runner._iter_runtime_open_orders = types.MethodType(
        controller_cls._iter_runtime_open_orders, runner
    )
    runner._append_open_order_snapshot_entry = types.MethodType(
        controller_cls._append_open_order_snapshot_entry, runner
    )

    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1_700_000_100.0):
        payload = controller_cls._collect_open_orders_snapshot(runner)

    assert payload["controllers_checked"] == 1
    assert payload["orders_count"] == 1
    assert payload["orders"][0]["order_id"] == "paper_v2_91"
    assert payload["orders"][0]["side"] == "BUY"
    assert payload["orders"][0]["trading_pair"] == "BTC-USDT"


def test_collect_open_orders_snapshot_dedupes_connector_and_paper_orders():
    controller_cls = _controller_cls()
    controller = SimpleNamespace(
        config=SimpleNamespace(
            connector_name="bitget_perpetual",
            trading_pair="BTC-USDT",
            instance_name="bot1",
        )
    )
    shared_order = SimpleNamespace(
        order_id="paper_v2_92",
        client_order_id="paper_v2_92",
        trading_pair="BTC-USDT",
        trade_type=SimpleNamespace(name="BUY", value="BUY"),
        price="68300.0",
        amount="0.001",
        age=5.0,
    )
    connector = SimpleNamespace(get_open_orders=lambda: [shared_order])
    runner = SimpleNamespace(
        controllers={"ctrl_1": controller},
        connectors={"bitget_perpetual": connector},
        _paper_exchange_runtime_orders={},
    )
    runner._iter_connector_open_orders = types.MethodType(
        controller_cls._iter_connector_open_orders, runner
    )
    runner._iter_runtime_open_orders = types.MethodType(
        controller_cls._iter_runtime_open_orders, runner
    )
    runner._append_open_order_snapshot_entry = types.MethodType(
        controller_cls._append_open_order_snapshot_entry, runner
    )

    payload = controller_cls._collect_open_orders_snapshot(runner)

    assert payload["orders_count"] == 1
    assert payload["orders"][0]["order_id"] == "paper_v2_92"


def test_hard_stop_kill_switch_is_one_shot_per_episode():
    controller_cls = _controller_cls()
    controller = _FakeController("hard_stop", "daily_loss_hard_limit|eod_close_pending")
    runner = _build_runner(controller)

    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1700000000.0):
        controller_cls._check_hard_stop_kill_switch(runner)
        controller_cls._check_hard_stop_kill_switch(runner)

    assert runner._bus_client.xadd.call_count == 1
    payload = runner._bus_client.xadd.call_args.args[1]
    assert payload["action"] == "kill_switch"
    assert payload["controller_id"] == "ctrl_1"
    assert runner._hard_stop_kill_switch_latched_by_controller["ctrl_1"] is True


def test_hard_stop_kill_switch_latch_resets_after_state_recovery():
    controller_cls = _controller_cls()
    controller = _FakeController("hard_stop", "daily_loss_hard_limit|eod_close_pending")
    runner = _build_runner(controller)

    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1700000000.0):
        controller_cls._check_hard_stop_kill_switch(runner)

    controller.set_status("running", "")
    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1700000010.0):
        controller_cls._check_hard_stop_kill_switch(runner)

    assert "ctrl_1" not in runner._hard_stop_kill_switch_latched_by_controller

    controller.set_status("hard_stop", "daily_loss_hard_limit|eod_close_pending")
    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1700000020.0):
        controller_cls._check_hard_stop_kill_switch(runner)

    assert runner._bus_client.xadd.call_count == 2


def test_hard_stop_without_hard_risk_reason_does_not_publish_kill_switch():
    controller_cls = _controller_cls()
    controller = _FakeController("hard_stop", "base_pct_above_max|eod_close_pending")
    runner = _build_runner(controller)

    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1700000000.0):
        controller_cls._check_hard_stop_kill_switch(runner)

    assert runner._bus_client.xadd.call_count == 0
    assert "ctrl_1" not in runner._hard_stop_kill_switch_latched_by_controller
    assert "ctrl_1" in runner._hard_stop_clear_candidate_since_by_controller
