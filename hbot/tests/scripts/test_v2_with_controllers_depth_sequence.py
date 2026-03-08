from __future__ import annotations

import importlib
import sys
import types
from enum import Enum
from types import SimpleNamespace
from unittest.mock import patch


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
    hb_bridge = _ensure_module("controllers.paper_engine_v2.hb_bridge")
    _ensure_module("controllers")
    _ensure_module("controllers.paper_engine_v2")
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
    preflight.run_controller_preflight = lambda *args, **kwargs: []


def _controller_cls():
    _install_import_stubs()
    module = importlib.import_module("scripts.shared.v2_with_controllers")
    return module.V2WithControllers


def test_resolve_depth_market_sequence_seeds_from_source_and_then_increments():
    controller_cls = _controller_cls()
    runner = SimpleNamespace(_depth_market_sequence_by_key={})

    seq1 = controller_cls._resolve_depth_market_sequence(
        runner, "bot1", "ctrl-1", "bitget_perpetual", "BTC-USDT", 1772742156834
    )
    seq2 = controller_cls._resolve_depth_market_sequence(
        runner, "bot1", "ctrl-1", "bitget_perpetual", "BTC-USDT", 1772742156834
    )
    seq3 = controller_cls._resolve_depth_market_sequence(
        runner, "bot1", "ctrl-1", "bitget_perpetual", "BTC-USDT", 1772742499396
    )

    assert seq1 == 1772742156834
    assert seq2 == 1772742156835
    assert seq3 == 1772742156836


def test_resolve_depth_market_sequence_uses_time_seed_when_source_missing():
    controller_cls = _controller_cls()
    runner = SimpleNamespace(_depth_market_sequence_by_key={})

    with patch("scripts.shared.v2_with_controllers.time.time", return_value=1700000000.123):
        seq1 = controller_cls._resolve_depth_market_sequence(
            runner, "bot1", "ctrl-2", "bitget_perpetual", "ETH-USDT", None
        )
        seq2 = controller_cls._resolve_depth_market_sequence(
            runner, "bot1", "ctrl-2", "bitget_perpetual", "ETH-USDT", None
        )

    assert seq1 == 1700000000123
    assert seq2 == 1700000000124


def test_resolve_depth_market_sequence_seeds_from_latest_depth_stream_entry():
    controller_cls = _controller_cls()
    runner = SimpleNamespace(
        _depth_market_sequence_by_key={},
        _bus_client=SimpleNamespace(
            read_latest=lambda _stream: (
                "1772744234111-0",
                {
                    "instance_name": "bot1",
                    "controller_id": "ctrl-3",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                    "market_sequence": 500,
                },
            )
        ),
    )

    seq1 = controller_cls._resolve_depth_market_sequence(
        runner, "bot1", "ctrl-3", "bitget_perpetual", "BTC-USDT", 999999
    )
    seq2 = controller_cls._resolve_depth_market_sequence(
        runner, "bot1", "ctrl-3", "bitget_perpetual", "BTC-USDT", 999999
    )

    assert seq1 == 501
    assert seq2 == 502
