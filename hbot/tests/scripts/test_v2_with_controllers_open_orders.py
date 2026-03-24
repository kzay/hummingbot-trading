from __future__ import annotations

import importlib
import sys
import time
import types
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from unittest.mock import Mock


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


def _attach_open_order_helpers(controller_cls, fake_self) -> None:
    for name in (
        "_append_open_order_snapshot_entry",
        "_iter_connector_open_orders",
        "_iter_runtime_open_orders",
    ):
        setattr(fake_self, name, types.MethodType(getattr(controller_cls, name), fake_self))


def test_collect_open_orders_snapshot_includes_active_runtime_orders() -> None:
    controller_cls = _controller_cls()
    now = time.time()
    fake_self = SimpleNamespace(
        controllers={
            "ctrl_1": SimpleNamespace(
                config=SimpleNamespace(
                    instance_name="bot1",
                    connector_name="bitget_perpetual",
                    trading_pair="BTC-USDT",
                )
            )
        },
        connectors={"bitget_perpetual": SimpleNamespace(get_open_orders=lambda: [])},
        _paper_desk_v2_bridges={
            "bitget_perpetual": {
                "desk": SimpleNamespace(_engines={"iid-btc": SimpleNamespace(open_orders=lambda: [])}),
                "instrument_id": SimpleNamespace(key="iid-btc", trading_pair="BTC-USDT"),
            }
        },
        _paper_exchange_runtime_orders={
            "bitget_perpetual": {
                "pe-open-1": SimpleNamespace(
                    client_order_id="pe-open-1",
                    order_id="pe-open-1",
                    trading_pair="BTC-USDT",
                    trade_type="BUY",
                    amount=Decimal("0.01"),
                    price=Decimal("100"),
                    current_state="working",
                    is_open=True,
                    creation_timestamp=now - 5,
                )
            }
        },
    )
    _attach_open_order_helpers(controller_cls, fake_self)

    payload = controller_cls._collect_open_orders_snapshot(fake_self)

    assert payload["orders_count"] == 1
    assert payload["orders"][0]["order_id"] == "pe-open-1"
    assert payload["orders"][0]["connector_name"] == "bitget_perpetual"
    assert payload["orders"][0]["state"] == "working"


def test_log_paper_engine_probe_reports_active_runtime_open() -> None:
    controller_cls = _controller_cls()
    logger = SimpleNamespace(warning=Mock(), info=Mock(), error=Mock(), debug=Mock())
    engine = SimpleNamespace(open_orders=lambda: [], _inflight=[], _book=None)
    fake_self = SimpleNamespace(
        _paper_engine_probe_enabled=True,
        _order_exec_trace_all_levels=True,
        _paper_engine_probe_last_ts=0.0,
        _paper_engine_probe_cooldown_s=0.0,
        _paper_desk_v2=SimpleNamespace(_engines={"iid-btc": engine}),
        _paper_desk_v2_bridges={"bitget_perpetual": {"instrument_id": SimpleNamespace(key="iid-btc", trading_pair="BTC-USDT")}},
        controllers={
            "ctrl_1": SimpleNamespace(
                config=SimpleNamespace(
                    instance_name="bot1",
                    connector_name="bitget_perpetual",
                    trading_pair="BTC-USDT",
                )
            )
        },
        _paper_exchange_runtime_orders={
            "bitget_perpetual": {
                "pe-open-1": SimpleNamespace(
                    order_id="pe-open-1",
                    trading_pair="BTC-USDT",
                    is_open=True,
                )
            }
        },
        logger=lambda: logger,
    )
    _attach_open_order_helpers(controller_cls, fake_self)

    controller_cls._log_paper_engine_probe(fake_self)

    assert logger.warning.called
    message = logger.warning.call_args[0][0]
    assert "active_runtime_open=%d" in message


def test_collect_open_orders_snapshot_dedupes_same_order_id_across_sources() -> None:
    controller_cls = _controller_cls()
    now = time.time()
    shared_order = SimpleNamespace(
        client_order_id="dup-1",
        order_id="dup-1",
        trading_pair="BTC-USDT",
        trade_type="BUY",
        amount=Decimal("0.01"),
        price=Decimal("100"),
        is_open=True,
        creation_timestamp=now - 5,
    )
    fake_self = SimpleNamespace(
        controllers={
            "ctrl_1": SimpleNamespace(
                config=SimpleNamespace(
                    instance_name="bot1",
                    connector_name="bitget_perpetual",
                    trading_pair="BTC-USDT",
                )
            )
        },
        connectors={"bitget_perpetual": SimpleNamespace(get_open_orders=lambda: [shared_order])},
        _paper_desk_v2_bridges={
            "bitget_perpetual": {
                "desk": SimpleNamespace(_engines={"iid-btc": SimpleNamespace(open_orders=lambda: [shared_order])}),
                "instrument_id": SimpleNamespace(key="iid-btc", trading_pair="BTC-USDT"),
            }
        },
        _paper_exchange_runtime_orders={"bitget_perpetual": {"dup-1": shared_order}},
    )
    _attach_open_order_helpers(controller_cls, fake_self)

    payload = controller_cls._collect_open_orders_snapshot(fake_self)

    assert payload["orders_count"] == 1
    assert payload["orders"][0]["order_id"] == "dup-1"
