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

        def on_tick(self):
            pass

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
    hb_bridge._paper_exchange_mode_for_instance = lambda instance_name: "disabled"
    preflight.run_controller_preflight = lambda *args, **kwargs: []


def _controller_cls():
    _install_import_stubs()
    sys.modules.pop("scripts.shared.v2_with_controllers", None)
    module = importlib.import_module("scripts.shared.v2_with_controllers")
    return module.V2WithControllers


def _fake_controller(controller_cls, *, circuit_breaker_threshold: int = 5):
    logger = SimpleNamespace(
        info=Mock(), warning=Mock(), error=Mock(), debug=Mock(),
        exception=Mock(), critical=Mock(),
    )
    latency_tracker = SimpleNamespace(observe=Mock(), flush=Mock())

    controller = controller_cls.__new__(controller_cls)
    controller.controllers = {}
    controller.config = SimpleNamespace(
        external_signal_risk_enabled=False,
        bus_soft_pause_on_outage=False,
    )
    controller.logger = lambda: logger
    controller._write_watchdog_heartbeat = Mock()
    controller._install_internal_paper_adapters = Mock()
    controller._tick_paper_adapters = Mock()
    controller._preflight_checked = True
    controller._preflight_failed = False
    controller._observe_controller_hot_path_metrics = Mock()
    controller._observe_hb_framework_overhead = Mock()
    controller._log_paper_engine_probe = Mock()
    controller._publish_market_state_to_bus = Mock()
    controller._consume_execution_intents = Mock()
    controller._is_stop_triggered = False
    controller._write_open_orders_snapshot = Mock()
    controller._last_on_tick_exit_ts = 0.0
    controller._latency_tracker = latency_tracker
    controller._bus_client = None
    controller._tick_consecutive_error_count = 0
    controller._tick_error_total = 0
    controller._tick_circuit_breaker_tripped = False
    controller._tick_circuit_breaker_threshold = circuit_breaker_threshold
    controller._artifact_write_failures = {}
    controller._heartbeat_path = Path("heartbeat.json")
    controller._heartbeat_write_interval_s = 0.0
    controller._last_heartbeat_write_ts = 0.0
    return controller, logger


def test_on_tick_survives_exception_in_super() -> None:
    """An exception in the inner tick should not crash the tick loop."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]

    call_count = {"n": 0}

    def _exploding_on_tick(self):
        call_count["n"] += 1
        raise RuntimeError("simulated failure in super().on_tick()")

    with patch.object(strategy_base.StrategyV2Base, "on_tick", _exploding_on_tick):
        controller_cls.on_tick(controller)

    assert controller._tick_consecutive_error_count == 1
    assert controller._tick_error_total == 1
    assert controller._tick_circuit_breaker_tripped is False
    logger.exception.assert_called_once()
    controller._write_watchdog_heartbeat.assert_called_with(reason="tick_error")


def test_on_tick_resets_consecutive_count_on_success() -> None:
    """A successful tick resets the consecutive error counter."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    controller._tick_consecutive_error_count = 3
    controller._tick_error_total = 5
    controller.check_manual_kill_switch = Mock()
    controller.control_max_drawdown = Mock()
    controller.send_performance_report = Mock()
    controller._handle_bus_outage_soft_pause = Mock()
    controller._check_hard_stop_kill_switch = Mock()

    controller_cls.on_tick(controller)

    assert controller._tick_consecutive_error_count == 0
    assert controller._tick_error_total == 5  # total is never reset


def test_circuit_breaker_trips_after_threshold_consecutive_errors() -> None:
    """After N consecutive failures the circuit breaker should trip and request soft-pause."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls, circuit_breaker_threshold=3)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]

    def _exploding_on_tick(self):
        raise RuntimeError("boom")

    with patch.object(strategy_base.StrategyV2Base, "on_tick", _exploding_on_tick):
        for _ in range(3):
            controller_cls.on_tick(controller)

    assert controller._tick_consecutive_error_count == 3
    assert controller._tick_error_total == 3
    assert controller._tick_circuit_breaker_tripped is True
    logger.critical.assert_called_once()
    assert "circuit breaker TRIPPED" in str(logger.critical.call_args)


def test_circuit_breaker_does_not_trip_below_threshold() -> None:
    """Errors below the threshold should NOT trip the breaker."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls, circuit_breaker_threshold=5)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]

    def _exploding_on_tick(self):
        raise RuntimeError("boom")

    with patch.object(strategy_base.StrategyV2Base, "on_tick", _exploding_on_tick):
        for _ in range(4):
            controller_cls.on_tick(controller)

    assert controller._tick_consecutive_error_count == 4
    assert controller._tick_circuit_breaker_tripped is False
    logger.critical.assert_not_called()


def test_circuit_breaker_calls_set_external_soft_pause() -> None:
    """When circuit breaker trips, it should call set_external_soft_pause on controllers."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls, circuit_breaker_threshold=2)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]

    mock_ctrl = Mock()
    mock_ctrl.set_external_soft_pause = Mock()
    controller.controllers = {"test_ctrl": mock_ctrl}

    def _exploding_on_tick(self):
        raise RuntimeError("boom")

    with patch.object(strategy_base.StrategyV2Base, "on_tick", _exploding_on_tick):
        for _ in range(2):
            controller_cls.on_tick(controller)

    assert controller._tick_circuit_breaker_tripped is True
    mock_ctrl.set_external_soft_pause.assert_called_once_with(True, reason="tick_circuit_breaker")


def test_system_exit_is_not_caught() -> None:
    """SystemExit must propagate — the guard should NOT swallow it."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]

    def _system_exit_on_tick(self):
        raise SystemExit(1)

    import pytest
    with patch.object(strategy_base.StrategyV2Base, "on_tick", _system_exit_on_tick), pytest.raises(SystemExit):
        controller_cls.on_tick(controller)

    assert controller._tick_consecutive_error_count == 0


def test_keyboard_interrupt_is_not_caught() -> None:
    """KeyboardInterrupt must propagate — the guard should NOT swallow it."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    strategy_base = sys.modules["hummingbot.strategy.strategy_v2_base"]

    def _keyboard_interrupt_on_tick(self):
        raise KeyboardInterrupt()

    import pytest
    with patch.object(strategy_base.StrategyV2Base, "on_tick", _keyboard_interrupt_on_tick):
        with pytest.raises(KeyboardInterrupt):
            controller_cls.on_tick(controller)

    assert controller._tick_consecutive_error_count == 0


def test_heartbeat_includes_tick_error_fields() -> None:
    """The heartbeat JSON should include tick error fields."""
    controller_cls = _controller_cls()
    controller, logger = _fake_controller(controller_cls)
    controller._tick_consecutive_error_count = 2
    controller._tick_error_total = 7
    controller._tick_circuit_breaker_tripped = True
    controller._config_reload_degraded = False
    controller._config_reload_error_count = 0
    controller._config_reload_last_error = ""
    controller._config_reload_last_error_ts = 0.0
    controller._config_reload_last_success_ts = 0.0
    controller._write_watchdog_heartbeat = controller_cls._write_watchdog_heartbeat.__get__(controller)

    with patch("pathlib.Path.write_text") as mock_write, \
         patch("pathlib.Path.mkdir"):
        controller._write_watchdog_heartbeat(reason="tick_end")

    assert mock_write.called
    import json
    payload = json.loads(mock_write.call_args[0][0])
    assert payload["tick_consecutive_error_count"] == 2
    assert payload["tick_error_total"] == 7
    assert payload["tick_circuit_breaker_tripped"] is True
