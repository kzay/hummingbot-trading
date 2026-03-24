from __future__ import annotations

import importlib
import sys
import types
from enum import Enum
from pathlib import Path
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

        def update_controllers_configs(self):
            return None

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
    hb_bridge.enable_framework_paper_compat_fallbacks = lambda: None
    hb_bridge.install_paper_desk_bridge = lambda *args, **kwargs: None
    hb_bridge._canonical_name = lambda name: str(name or "").removesuffix("_paper_trade")
    hb_bridge._paper_exchange_mode_for_instance = lambda instance_name: "active" if instance_name == "bot1" else "disabled"
    preflight.run_controller_preflight = lambda *args, **kwargs: []


def _controller_cls():
    _install_import_stubs()
    sys.modules.pop("scripts.shared.v2_with_controllers", None)
    module = importlib.import_module("scripts.shared.v2_with_controllers")
    return module.V2WithControllers


def _fake_controller(controller_cls):
    logger = SimpleNamespace(info=Mock(), warning=Mock(), error=Mock(), debug=Mock())
    controller = controller_cls.__new__(controller_cls)
    controller._config_reload_retry_after_ts = 0.0
    controller._config_reload_retry_interval_s = 30.0
    controller._config_reload_error_count = 0
    controller._config_reload_last_error = ""
    controller._config_reload_last_error_ts = 0.0
    controller._config_reload_degraded = False
    controller._config_reload_last_success_ts = 0.0
    controller._config_reload_validation_error_types = tuple()
    controller._controller_module_mtime_by_name = {}
    controller.controllers = {}
    controller.logger = lambda: logger
    controller._write_watchdog_heartbeat = Mock()
    controller._artifact_write_failures = {}
    controller._heartbeat_path = Path("heartbeat.json")
    controller._startup_sync_report_path = Path("startup_sync_report.json")
    controller._open_orders_snapshot_path = Path("open_orders_latest.json")
    controller._heartbeat_write_interval_s = 0.0
    controller._last_heartbeat_write_ts = 0.0
    controller._open_orders_write_interval_s = 0.0
    controller._last_open_orders_write_ts = 0.0
    controller._preflight_checked = False
    controller._preflight_failed = False
    return controller, logger


def test_invalid_hot_reload_enters_degraded_mode_and_keeps_bot_alive() -> None:
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]
    controller._reload_controller_modules_if_changed = lambda force: False

    def _raise_validation(self):
        raise ValueError("validation errors for controller config")

    with patch.object(strategy_base.StrategyV2Base, "update_controllers_configs", _raise_validation):
        with patch("scripts.shared.v2_with_controllers.time.time", return_value=1_700_000_000.0):
            controller_cls.update_controllers_configs(controller)

    assert controller._config_reload_degraded is True
    assert controller._config_reload_error_count == 1
    assert "ValueError" in controller._config_reload_last_error
    assert controller._config_reload_retry_after_ts == 1_700_000_030.0
    controller._write_watchdog_heartbeat.assert_called_once_with(reason="config_reload_validation_error")
    assert logger.error.called


def test_hot_reload_recovers_after_forced_module_reload_retry() -> None:
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    controller._config_reload_degraded = True
    controller._config_reload_error_count = 1
    controller._config_reload_last_error = "ValueError: stale config"
    controller._config_reload_last_error_ts = 1_699_999_000.0
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]
    base_calls = {"count": 0}

    def _reload(force: bool) -> bool:
        return bool(force)

    def _update(self):
        base_calls["count"] += 1
        if base_calls["count"] == 1:
            raise ValueError("validation errors for controller config")
        return None

    controller._reload_controller_modules_if_changed = _reload

    with patch.object(strategy_base.StrategyV2Base, "update_controllers_configs", _update):
        with patch("scripts.shared.v2_with_controllers.time.time", return_value=1_700_000_100.0):
            controller_cls.update_controllers_configs(controller)

    assert base_calls["count"] == 2
    assert controller._config_reload_degraded is False
    assert controller._config_reload_last_error == ""
    assert controller._config_reload_last_error_ts == 0.0
    assert controller._config_reload_retry_after_ts == 0.0
    assert controller._config_reload_last_success_ts == 1_700_000_100.0
    logger.info.assert_called_once()


def test_watchdog_heartbeat_write_failure_is_logged_and_counted() -> None:
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)

    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        controller_cls._write_watchdog_heartbeat(controller, reason="tick_end")

    assert controller._artifact_write_failures["watchdog_heartbeat"] == 1
    logger.warning.assert_called_once()


def test_open_orders_snapshot_write_failure_is_logged_and_counted() -> None:
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    controller._collect_open_orders_snapshot = lambda: {"orders": []}

    with patch("pathlib.Path.write_text", side_effect=OSError("permission denied")):
        controller_cls._write_open_orders_snapshot(controller, reason="tick_end")

    assert controller._artifact_write_failures["open_orders_snapshot"] == 1
    logger.warning.assert_called_once()
