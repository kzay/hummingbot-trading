from __future__ import annotations

import importlib.util
from decimal import Decimal
from types import MethodType, SimpleNamespace

import pytest


def _hummingbot_available() -> bool:
    try:
        return importlib.util.find_spec("hummingbot") is not None
    except ValueError:
        return False


HUMMINGBOT_AVAILABLE = _hummingbot_available()

if HUMMINGBOT_AVAILABLE:
    from controllers.bot5_ift_jota_v1 import Bot5IftJotaV1Config, Bot5IftJotaV1Controller
    from controllers.epp_v2_4 import EppV24Config, EppV24Controller
    from controllers.epp_v2_4_bot5 import EppV24Bot5Config, EppV24Bot5Controller
    from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
    from controllers.runtime.market_making_types import RegimeSpec
else:  # pragma: no cover - exercised only in stripped test environments
    Bot5IftJotaV1Config = object
    Bot5IftJotaV1Controller = object
    EppV24Config = object
    EppV24Controller = object
    RegimeSpec = object
    StrategyRuntimeV24Config = object
    StrategyRuntimeV24Controller = object
    EppV24Bot5Config = object
    EppV24Bot5Controller = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


def test_bot5_controller_reuses_shared_runtime_stack() -> None:
    assert issubclass(Bot5IftJotaV1Config, StrategyRuntimeV24Config)
    assert issubclass(Bot5IftJotaV1Controller, StrategyRuntimeV24Controller)
    assert Bot5IftJotaV1Config.controller_name == "bot5_ift_jota_v1"

    assert issubclass(EppV24Bot5Config, Bot5IftJotaV1Config)
    assert issubclass(EppV24Bot5Controller, Bot5IftJotaV1Controller)
    assert issubclass(EppV24Bot5Config, StrategyRuntimeV24Config)
    assert issubclass(EppV24Bot5Controller, StrategyRuntimeV24Controller)
    assert issubclass(EppV24Bot5Config, EppV24Config)
    assert issubclass(EppV24Bot5Controller, EppV24Controller)
    assert EppV24Bot5Config.controller_name == "epp_v2_4_bot5"


def _make_bot5_config(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="epp_v2_4_bot5_test",
        controller_type="market_making",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        variant="a",
        instance_name="bot5",
        trend_eps_pct=Decimal("0.0006"),
        high_vol_band_pct=Decimal("0.0065"),
        max_base_pct=Decimal("0.55"),
        perp_target_net_base_pct=Decimal("0.0"),
        slippage_est_pct=Decimal("0.00005"),
        adaptive_min_edge_bps_floor=Decimal("1.0"),
        adaptive_min_edge_bps_cap=Decimal("30.0"),
        bot5_flow_imbalance_threshold=Decimal("0.18"),
        bot5_flow_trend_threshold_pct=Decimal("0.0008"),
        bot5_flow_bias_threshold=Decimal("0.55"),
        bot5_flow_directional_threshold=Decimal("0.75"),
        bot5_directional_target_net_base_pct=Decimal("0.08"),
        bot5_low_conviction_extra_edge_bps=Decimal("0.60"),
        bot5_directional_market_floor_bps=Decimal("0.25"),
        min_net_edge_bps=Decimal("1.50"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_regime_spec(one_sided: str = "off", target_base_pct: str = "0.0") -> RegimeSpec:
    return RegimeSpec(
        spread_min=Decimal("0.00018"),
        spread_max=Decimal("0.00065"),
        levels_min=2,
        levels_max=2,
        refresh_s=45,
        target_base_pct=Decimal(target_base_pct),
        quote_size_pct_min=Decimal("0.0025"),
        quote_size_pct_max=Decimal("0.0040"),
        one_sided=one_sided,
        fill_factor=Decimal("0.90"),
    )


def _make_bot5_controller(
    *,
    config: SimpleNamespace | None = None,
    imbalance: Decimal = Decimal("0"),
    ema_value: Decimal = Decimal("100"),
    selective_state: str = "inactive",
    fill_edge_ewma: Decimal | None = None,
) -> EppV24Bot5Controller:
    ctrl = object.__new__(EppV24Bot5Controller)
    ctrl.config = config or _make_bot5_config()
    ctrl._is_perp = True
    ctrl._ob_imbalance = imbalance
    ctrl._regime_ema_value = ema_value
    ctrl._selective_quote_state = selective_state
    ctrl._fill_edge_ewma = fill_edge_ewma
    ctrl._maker_fee_pct = Decimal("0.0002")
    ctrl._quote_side_mode = "off"
    ctrl._quote_side_reason = "regime"
    ctrl._pending_stale_cancel_actions = []
    ctrl.executors_info = []
    ctrl._external_target_base_pct_override = None
    ctrl._bot5_flow_state = EppV24Bot5Controller._empty_bot5_flow_state(ctrl)
    ctrl._cancel_stale_side_executors = MethodType(EppV24Controller._cancel_stale_side_executors, ctrl)
    return ctrl


def test_bot5_targets_directional_net_bias_on_strong_up_flow() -> None:
    ctrl = _make_bot5_controller(imbalance=Decimal("0.72"))
    ctrl._detect_regime = lambda mid: ("up", _make_regime_spec(), Decimal("0.0025"))

    regime_name, _regime_spec, _target_base_pct, target_net_base_pct, _band_pct = (
        EppV24Bot5Controller._resolve_regime_and_targets(ctrl, Decimal("101.0"))
    )

    assert regime_name == "up"
    assert target_net_base_pct > Decimal("0")
    assert ctrl._bot5_flow_state["bias_active"] is True
    assert ctrl._bot5_flow_state["directional_allowed"] is True


def test_bot5_preserves_shared_safety_veto_when_selective_quote_is_blocked() -> None:
    ctrl = _make_bot5_controller(
        imbalance=Decimal("0.80"),
        selective_state="blocked",
    )
    ctrl._detect_regime = lambda mid: ("up", _make_regime_spec(), Decimal("0.0025"))

    _regime_name, _regime_spec, _target_base_pct, target_net_base_pct, _band_pct = (
        EppV24Bot5Controller._resolve_regime_and_targets(ctrl, Decimal("101.0"))
    )

    assert target_net_base_pct == Decimal("0.0")
    assert ctrl._bot5_flow_state["bias_active"] is False
    assert ctrl._bot5_flow_state["directional_allowed"] is False
    assert ctrl._bot5_flow_state["reason"] == "selective_blocked"


def test_bot5_quote_side_switches_to_directional_mode_when_conviction_is_strong() -> None:
    sell_executor = SimpleNamespace(
        is_active=True,
        id="exec-sell",
        custom_info={"level_id": "sell_0"},
    )
    ctrl = _make_bot5_controller(imbalance=Decimal("0.65"))
    ctrl.executors_info = [sell_executor]
    ctrl._bot5_flow_state = {
        "direction": "buy",
        "imbalance": Decimal("0.65"),
        "trend_displacement_pct": Decimal("0.0100"),
        "signed_signal": Decimal("0.80"),
        "conviction": Decimal("0.95"),
        "bias_active": True,
        "directional_allowed": True,
        "target_net_base_pct": Decimal("0.08"),
        "low_conviction": False,
        "reason": "directional_buy",
    }

    mode = EppV24Bot5Controller._resolve_quote_side_mode(
        ctrl,
        mid=Decimal("101.0"),
        regime_name="up",
        regime_spec=_make_regime_spec(one_sided="off"),
    )

    assert mode == "buy_only"
    assert ctrl._quote_side_reason == "bot5_directional_buy"
    assert len(ctrl._pending_stale_cancel_actions) == 1


def test_bot5_quote_side_stays_two_sided_when_conviction_is_weak() -> None:
    ctrl = _make_bot5_controller(imbalance=Decimal("0.08"))
    ctrl._bot5_flow_state = {
        "direction": "buy",
        "imbalance": Decimal("0.08"),
        "trend_displacement_pct": Decimal("0.0002"),
        "signed_signal": Decimal("0.12"),
        "conviction": Decimal("0.30"),
        "bias_active": False,
        "directional_allowed": False,
        "target_net_base_pct": Decimal("0.0"),
        "low_conviction": True,
        "reason": "weak_flow",
    }

    mode = EppV24Bot5Controller._resolve_quote_side_mode(
        ctrl,
        mid=Decimal("100.1"),
        regime_name="up",
        regime_spec=_make_regime_spec(one_sided="off"),
    )

    assert mode == "off"
    assert ctrl._quote_side_reason == "regime"
    assert ctrl._pending_stale_cancel_actions == []
