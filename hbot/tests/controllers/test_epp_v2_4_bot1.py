from __future__ import annotations

import inspect
import importlib.util
from decimal import Decimal
from types import SimpleNamespace

import pytest


def _hummingbot_available() -> bool:
    try:
        return importlib.util.find_spec("hummingbot") is not None
    except ValueError:
        return False


HUMMINGBOT_AVAILABLE = _hummingbot_available()

if HUMMINGBOT_AVAILABLE:
    from controllers.bot1_baseline_v1 import Bot1BaselineV1Config, Bot1BaselineV1Controller
    from controllers.epp_v2_4 import EppV24Config, EppV24Controller
    from controllers.epp_v2_4_bot1 import EppV24Bot1Config, EppV24Bot1Controller
    from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
else:  # pragma: no cover
    Bot1BaselineV1Config = object
    Bot1BaselineV1Controller = object
    EppV24Config = object
    EppV24Controller = object
    EppV24Bot1Config = object
    EppV24Bot1Controller = object
    StrategyRuntimeV24Config = object
    StrategyRuntimeV24Controller = object


pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


def test_bot1_controller_reuses_shared_runtime_stack() -> None:
    assert issubclass(Bot1BaselineV1Config, StrategyRuntimeV24Config)
    assert issubclass(Bot1BaselineV1Controller, StrategyRuntimeV24Controller)
    assert Bot1BaselineV1Config.controller_name == "bot1_baseline_v1"

    assert issubclass(EppV24Bot1Config, Bot1BaselineV1Config)
    assert issubclass(EppV24Bot1Controller, Bot1BaselineV1Controller)
    assert issubclass(EppV24Bot1Config, EppV24Config)
    assert issubclass(EppV24Bot1Controller, EppV24Controller)
    assert EppV24Bot1Config.controller_name == "epp_v2_4_bot1"


def test_bot1_config_keeps_shared_edge_gate_enabled() -> None:
    cfg = EppV24Bot1Config(
        id="bot1_cfg_test",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("8"),
        buy_spreads="0.001",
        sell_spreads="0.001",
        buy_amounts_pct="100",
        sell_amounts_pct="100",
    )

    assert cfg.shared_edge_gate_enabled is True


def test_bot1_gate_metrics_use_shared_alpha_state_without_changing_behavior() -> None:
    ctrl = object.__new__(EppV24Bot1Controller)
    ctrl._alpha_policy_state = "maker_bias_buy"
    ctrl._alpha_policy_reason = "inventory_relief"
    ctrl._quote_side_mode = "buy_only"
    ctrl._alpha_maker_score = Decimal("0.72")
    ctrl._alpha_aggressive_score = Decimal("0.30")

    metrics = EppV24Bot1Controller._bot1_gate_metrics(ctrl)

    assert metrics["state"] == "active"
    assert metrics["reason"] == "inventory_relief"
    assert metrics["signal_side"] == "buy"
    assert metrics["signal_reason"] == "maker_bias_buy"
    assert metrics["signal_score"] == Decimal("0.72")


def test_bot1_gate_metrics_block_on_shared_no_trade_state() -> None:
    ctrl = object.__new__(EppV24Bot1Controller)
    ctrl._alpha_policy_state = "no_trade"
    ctrl._alpha_policy_reason = "neutral_low_edge"
    ctrl._quote_side_mode = "off"
    ctrl._alpha_maker_score = Decimal("0.10")
    ctrl._alpha_aggressive_score = Decimal("0")

    metrics = EppV24Bot1Controller._bot1_gate_metrics(ctrl)

    assert metrics["state"] == "blocked"
    assert metrics["signal_side"] == "off"
    assert metrics["signal_reason"] == "no_trade"


def test_bot1_emit_tick_output_accepts_runtime_context_kwargs() -> None:
    signature = inspect.signature(Bot1BaselineV1Controller._emit_tick_output)

    assert "runtime_data_context" in signature.parameters
    assert "runtime_execution_plan" in signature.parameters
    assert "runtime_risk_decision" in signature.parameters
