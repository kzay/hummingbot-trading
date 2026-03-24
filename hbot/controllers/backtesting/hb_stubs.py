"""Reusable Hummingbot stub installer for replay/backtest imports."""
from __future__ import annotations

import sys
import types as _types_mod
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import BaseModel

_HB_MODULES: dict[str, _types_mod.ModuleType] = {}


class _EnumValue(str):
    def __new__(cls, name: str):
        value = str.__new__(cls, name)
        value.name = name
        return value


def _enum_namespace(*names: str) -> SimpleNamespace:
    return SimpleNamespace(**{name: _EnumValue(name) for name in names})


def _ensure_mock_module(name: str) -> _types_mod.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    if name in _HB_MODULES:
        return _HB_MODULES[name]
    module = _types_mod.ModuleType(name)
    _HB_MODULES[name] = module
    sys.modules[name] = module
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent_name = ".".join(parts[:i])
        parent = _ensure_mock_module(parent_name)
        setattr(parent, parts[i], module if i == len(parts) - 1 else sys.modules[".".join(parts[: i + 1])])
    return module


class _FakeMMConfig(BaseModel):
    id: str = "replay_controller"
    controller_name: str = "fake"
    connector_name: str = ""
    trading_pair: str = ""
    leverage: int = 1
    position_mode: str = "one_way"
    total_amount_quote: Decimal = Decimal("100")
    min_spread: Decimal = Decimal("0.001")
    buy_spreads: list = [Decimal("0.001")]
    sell_spreads: list = [Decimal("0.001")]
    buy_amounts_pct: list = [Decimal("50")]
    sell_amounts_pct: list = [Decimal("50")]
    executor_refresh_time: int = 60
    cooldown_time: int = 15
    skip_rebalance: bool = False
    candles_config: list = []
    model_config = {"arbitrary_types_allowed": True}


class _FakeMMBase:
    def __init__(self, config, *args, **kwargs):
        self.config = config
        self.connectors = {}
        self.market_data_provider = None
        self.strategy = None
        self._strategy = None
        self.executors_info = []

    def buy(self, *args, **kwargs):
        return "stub-buy-order"

    def sell(self, *args, **kwargs):
        return "stub-sell-order"

    def cancel(self, *args, **kwargs):
        return True

    @staticmethod
    def filter_executors(*, executors, filter_func):
        return [executor for executor in executors if filter_func(executor)]


def install_hb_stubs() -> None:
    """Install lightweight Hummingbot modules needed for imports/tests."""
    if "hummingbot" in sys.modules:
        return

    _ensure_mock_module("hummingbot")
    _ensure_mock_module("hummingbot.core")
    _ensure_mock_module("hummingbot.core.data_type")
    common = _ensure_mock_module("hummingbot.core.data_type.common")
    common.PriceType = _enum_namespace("MidPrice", "BestBid", "BestAsk", "LastTrade")
    common.TradeType = _enum_namespace("BUY", "SELL")
    common.OrderType = _enum_namespace("LIMIT", "MARKET")
    common.PositionAction = _enum_namespace("OPEN", "CLOSE", "AUTO")

    _ensure_mock_module("hummingbot.core.event")
    events = _ensure_mock_module("hummingbot.core.event.events")
    events.MarketOrderFailureEvent = MagicMock
    events.OrderCancelledEvent = MagicMock
    events.OrderFilledEvent = MagicMock
    events.TokenAmount = MagicMock
    events.TradeFee = MagicMock

    _ensure_mock_module("hummingbot.strategy_v2")
    _ensure_mock_module("hummingbot.strategy_v2.controllers")
    mm_base = _ensure_mock_module("hummingbot.strategy_v2.controllers.market_making_controller_base")
    mm_base.MarketMakingControllerConfigBase = _FakeMMConfig
    mm_base.MarketMakingControllerBase = _FakeMMBase

    _ensure_mock_module("hummingbot.strategy_v2.executors")
    _ensure_mock_module("hummingbot.strategy_v2.executors.position_executor")
    pe_dt = _ensure_mock_module("hummingbot.strategy_v2.executors.position_executor.data_types")
    pe_dt.PositionExecutorConfig = MagicMock
    executor_base = _ensure_mock_module("hummingbot.strategy_v2.executors.executor_base")
    executor_base.ExecutorBase = MagicMock

    _ensure_mock_module("hummingbot.strategy_v2.models")
    executor_actions = _ensure_mock_module("hummingbot.strategy_v2.models.executor_actions")
    executor_actions.StopExecutorAction = MagicMock
    executor_actions.CreateExecutorAction = MagicMock

    _ensure_mock_module("hummingbot.data_feed")
    market_data_provider = _ensure_mock_module("hummingbot.data_feed.market_data_provider")
    market_data_provider.MarketDataProvider = MagicMock


__all__ = ["install_hb_stubs"]
