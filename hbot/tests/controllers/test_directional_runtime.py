"""Unit tests for DirectionalRuntimeController and DirectionalRuntimeConfig.

Validates that the directional runtime base class properly stubs MM-only
methods and that the config defaults lock out MM subsystems.
"""
from __future__ import annotations

import sys
import types as _types_mod
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Hummingbot stub injection (same pattern as test_epp_v2_4_core)
# ---------------------------------------------------------------------------

_HB_MODULES: dict[str, _types_mod.ModuleType] = {}


def _ensure_mock_module(name: str) -> _types_mod.ModuleType:
    if name in _HB_MODULES:
        return _HB_MODULES[name]
    mod = _types_mod.ModuleType(name)
    _HB_MODULES[name] = mod
    sys.modules[name] = mod
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        _ensure_mock_module(parent)
    return mod


def _install_hb_stubs() -> None:
    if "hummingbot" in sys.modules:
        return
    from pydantic import BaseModel

    _ensure_mock_module("hummingbot")
    _ensure_mock_module("hummingbot.core")
    _ensure_mock_module("hummingbot.core.data_type")
    common = _ensure_mock_module("hummingbot.core.data_type.common")
    common.PriceType = MagicMock()
    common.TradeType = MagicMock()
    _ensure_mock_module("hummingbot.core.event")
    events = _ensure_mock_module("hummingbot.core.event.events")
    events.MarketOrderFailureEvent = MagicMock
    events.OrderCancelledEvent = MagicMock
    events.OrderFilledEvent = MagicMock
    _ensure_mock_module("hummingbot.strategy_v2")
    _ensure_mock_module("hummingbot.strategy_v2.controllers")
    mm_base = _ensure_mock_module(
        "hummingbot.strategy_v2.controllers.market_making_controller_base"
    )

    class _FakeMMConfig(BaseModel):
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
        def __init__(self, config, *a, **kw):
            pass

    mm_base.MarketMakingControllerConfigBase = _FakeMMConfig
    mm_base.MarketMakingControllerBase = _FakeMMBase
    _ensure_mock_module("hummingbot.strategy_v2.executors")
    _ensure_mock_module("hummingbot.strategy_v2.executors.position_executor")
    pe_dt = _ensure_mock_module(
        "hummingbot.strategy_v2.executors.position_executor.data_types"
    )
    pe_dt.PositionExecutorConfig = MagicMock
    _ensure_mock_module("hummingbot.strategy_v2.models")
    ea = _ensure_mock_module("hummingbot.strategy_v2.models.executor_actions")
    ea.StopExecutorAction = MagicMock


_install_hb_stubs()

# Now safe to import --------------------------------------------------------
from controllers.runtime.directional_config import DirectionalRuntimeConfig
from controllers.runtime.directional_core import DirectionalRuntimeAdapter
from controllers.runtime.directional_runtime import DirectionalRuntimeController

_ZERO = Decimal("0")
_ONE = Decimal("1")


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestDirectionalRuntimeConfig:
    """Verify MM-only fields are locked to disabled defaults."""

    def test_mm_enable_flags_default_false(self):
        cfg = DirectionalRuntimeConfig(
            connector_name="bitget_perpetual",
            trading_pair="BTC-USDT",
        )
        assert cfg.shared_edge_gate_enabled is False
        assert cfg.alpha_policy_enabled is False
        assert cfg.selective_quoting_enabled is False
        assert cfg.adverse_fill_soft_pause_enabled is False
        assert cfg.edge_confidence_soft_pause_enabled is False
        assert cfg.slippage_soft_pause_enabled is False
        assert cfg.pnl_governor_enabled is False
        assert cfg.adaptive_params_enabled is False
        assert cfg.auto_calibration_enabled is False
        assert cfg.use_kelly_sizing is False

    def test_mm_numeric_defaults_zeroed(self):
        cfg = DirectionalRuntimeConfig(
            connector_name="bitget_perpetual",
            trading_pair="BTC-USDT",
        )
        assert cfg.min_net_edge_bps == _ZERO
        assert cfg.edge_resume_bps == _ZERO
        assert cfg.max_quote_to_market_spread_mult == _ZERO
        assert cfg.ob_imbalance_skew_weight == _ZERO

    def test_shared_fields_still_accessible(self):
        cfg = DirectionalRuntimeConfig(
            connector_name="bitget_perpetual",
            trading_pair="BTC-USDT",
        )
        assert cfg.max_daily_loss_pct_hard == Decimal("0.03")
        assert cfg.max_drawdown_pct_hard == Decimal("0.05")
        assert cfg.sample_interval_s == 10

    def test_inherits_from_epp_config(self):
        from controllers.shared_runtime_v24 import EppV24Config
        assert issubclass(DirectionalRuntimeConfig, EppV24Config)


# ---------------------------------------------------------------------------
# Controller method stub tests
# ---------------------------------------------------------------------------


class TestDirectionalRuntimeStubs:
    """Verify each MM-only method is stubbed to safe defaults."""

    def test_fill_edge_below_cost_floor_always_false(self):
        assert DirectionalRuntimeController._fill_edge_below_cost_floor(None) is False

    def test_adverse_fill_soft_pause_always_false(self):
        assert DirectionalRuntimeController._adverse_fill_soft_pause_active(None) is False

    def test_edge_confidence_soft_pause_always_false(self):
        assert DirectionalRuntimeController._edge_confidence_soft_pause_active(None) is False

    def test_slippage_soft_pause_always_false(self):
        assert DirectionalRuntimeController._slippage_soft_pause_active(None) is False

    def test_kelly_order_quote_always_zero(self):
        result = DirectionalRuntimeController._get_kelly_order_quote(None, Decimal("1000"))
        assert result == _ZERO

    def test_pnl_governor_always_one(self):
        stub = SimpleNamespace(
            _pnl_governor_size_mult=None,
            _pnl_governor_size_boost_active=None,
            _pnl_governor_size_boost_reason=None,
        )
        result = DirectionalRuntimeController._compute_pnl_governor_size_mult(
            stub, Decimal("1000"), Decimal("1.5"),
        )
        assert result == _ONE
        assert stub._pnl_governor_size_mult == _ONE
        assert stub._pnl_governor_size_boost_active is False
        assert stub._pnl_governor_size_boost_reason == "directional_runtime"

    def test_selective_quote_quality_inactive(self):
        result = DirectionalRuntimeController._compute_selective_quote_quality(None, "neutral_low_vol")
        assert result["state"] == "inactive"
        assert result["score"] == _ZERO

    def test_alpha_policy_directional(self):
        result = DirectionalRuntimeController._compute_alpha_policy(
            None,
            regime_name="neutral_low_vol",
            spread_state=MagicMock(),
            market=MagicMock(),
            target_net_base_pct=_ZERO,
            base_pct_net=_ZERO,
        )
        assert result["state"] == "directional"
        assert result["reason"] == "directional_runtime"
        assert result["cross_allowed"] is False

    def test_edge_gate_ewma_clears_pause(self):
        stub = SimpleNamespace(_soft_pause_edge=True)
        DirectionalRuntimeController._update_edge_gate_ewma(stub, 1000.0, MagicMock())
        assert stub._soft_pause_edge is False

    def test_spread_competitiveness_cap_passthrough(self):
        stub = SimpleNamespace(
            _spread_competitiveness_cap_active=None,
            _spread_competitiveness_cap_side_pct=None,
        )
        buy = [Decimal("0.001"), Decimal("0.002")]
        sell = [Decimal("0.003"), Decimal("0.004")]
        result_buy, result_sell = DirectionalRuntimeController._apply_spread_competitiveness_cap(
            stub, buy, sell, MagicMock(),
        )
        assert result_buy is buy
        assert result_sell is sell
        assert stub._spread_competitiveness_cap_active is False

    def test_auto_calibration_noop(self):
        DirectionalRuntimeController._auto_calibration_record_minute(None, 1.0, "state", [], {}, _ZERO, _ZERO)
        DirectionalRuntimeController._auto_calibration_record_fill(None, 1.0, _ZERO, _ZERO, _ZERO, _ZERO, True)
        DirectionalRuntimeController._auto_calibration_maybe_run(None, 1.0, "state", [], _ZERO, _ZERO)

    def test_update_adaptive_history_noop(self):
        DirectionalRuntimeController._update_adaptive_history(
            None, band_pct=Decimal("0.01"), market_spread_pct=Decimal("0.002"),
        )

    def test_increment_governor_reason_count_noop(self):
        DirectionalRuntimeController._increment_governor_reason_count(None, "_counts", "reason")

    def test_edge_gate_update_noop(self):
        DirectionalRuntimeController._edge_gate_update(None, 1.0, _ZERO, _ZERO, _ZERO)


# ---------------------------------------------------------------------------
# Inheritance tests
# ---------------------------------------------------------------------------


class TestDirectionalRuntimeInheritance:
    """Verify the class hierarchy is correct."""

    def test_inherits_from_shared_kernel_not_epp(self):
        from controllers.shared_runtime_v24 import EppV24Controller, SharedRuntimeKernel
        assert issubclass(DirectionalRuntimeController, SharedRuntimeKernel)
        assert not issubclass(DirectionalRuntimeController, EppV24Controller)

    def test_family_adapter_is_directional(self):
        stub = SimpleNamespace()
        adapter = DirectionalRuntimeController._make_runtime_family_adapter(stub)
        assert isinstance(adapter, DirectionalRuntimeAdapter)

    def test_runtime_family_label(self):
        adapter = DirectionalRuntimeAdapter(SimpleNamespace())
        class_name = type(adapter).__name__
        assert "Directional" in class_name
