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
    from controllers.epp_v2_4_bot5 import EppV24Bot5Config, EppV24Bot5Controller
    from controllers.runtime.base import DirectionalStrategyRuntimeV24Config, DirectionalStrategyRuntimeV24Controller
    from controllers.runtime.data_context import RuntimeDataContext
    from controllers.runtime.directional_core import DirectionalRuntimeAdapter
    from controllers.runtime.execution_context import RuntimeExecutionPlan
    from controllers.runtime.runtime_types import RegimeSpec
    from controllers.shared_runtime_v24 import SharedRuntimeKernel
else:  # pragma: no cover - exercised only in stripped test environments
    Bot5IftJotaV1Config = object
    Bot5IftJotaV1Controller = object
    DirectionalRuntimeAdapter = object
    RuntimeDataContext = object
    RuntimeExecutionPlan = object
    RegimeSpec = object
    DirectionalStrategyRuntimeV24Config = object
    DirectionalStrategyRuntimeV24Controller = object
    SharedRuntimeKernel = object
    EppV24Bot5Config = object
    EppV24Bot5Controller = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


def test_bot5_controller_reuses_shared_runtime_stack() -> None:
    assert issubclass(Bot5IftJotaV1Config, DirectionalStrategyRuntimeV24Config)
    assert issubclass(Bot5IftJotaV1Controller, DirectionalStrategyRuntimeV24Controller)
    assert Bot5IftJotaV1Config.controller_name == "bot5_ift_jota_v1"

    assert issubclass(EppV24Bot5Config, Bot5IftJotaV1Config)
    assert issubclass(EppV24Bot5Controller, Bot5IftJotaV1Controller)
    assert issubclass(EppV24Bot5Config, DirectionalStrategyRuntimeV24Config)
    assert issubclass(EppV24Bot5Controller, DirectionalStrategyRuntimeV24Controller)
    assert EppV24Bot5Config.controller_name == "epp_v2_4_bot5"


def test_bot5_controller_uses_directional_family_adapter() -> None:
    ctrl = object.__new__(EppV24Bot5Controller)
    adapter = EppV24Bot5Controller._make_runtime_family_adapter(ctrl)
    assert isinstance(adapter, DirectionalRuntimeAdapter)


def _make_bot5_config(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="epp_v2_4_bot5_test",
        controller_type="directional",
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
        alpha_policy_enabled=False,
        selective_quoting_enabled=False,
        adverse_fill_soft_pause_enabled=False,
        edge_confidence_soft_pause_enabled=False,
        slippage_soft_pause_enabled=False,
        min_net_edge_bps=Decimal("1.50"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_bot5_config_disables_shared_trade_quality_gates() -> None:
    cfg = EppV24Bot5Config(
        id="bot5_cfg_test",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("8"),
        buy_spreads="0.001",
        sell_spreads="0.001",
        buy_amounts_pct="100",
        sell_amounts_pct="100",
    )

    assert cfg.shared_edge_gate_enabled is False
    assert cfg.alpha_policy_enabled is False
    assert cfg.selective_quoting_enabled is False
    assert cfg.adverse_fill_soft_pause_enabled is False
    assert cfg.edge_confidence_soft_pause_enabled is False
    assert cfg.slippage_soft_pause_enabled is False


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
    ctrl._cancel_stale_side_executors = MethodType(SharedRuntimeKernel._cancel_stale_side_executors, ctrl)
    ctrl.market_data_provider = SimpleNamespace(time=lambda: 1_000.0)
    ctrl.processed_data = {}
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


def test_bot5_keeps_two_sided_quotes_when_regime_mode_is_off(monkeypatch) -> None:
    ctrl = _make_bot5_controller()
    ctrl._bot5_flow_state = {
        "direction": "off",
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
    ctrl._quote_side_mode = "off"
    ctrl._project_total_amount_quote = lambda **kwargs: Decimal(kwargs["total_levels"])

    monkeypatch.setattr(
        DirectionalStrategyRuntimeV24Controller,
        "build_runtime_execution_plan",
        lambda self, data_context: RuntimeExecutionPlan(
            family="directional",
            buy_spreads=[Decimal("0.001"), Decimal("0.002")],
            sell_spreads=[Decimal("0.001"), Decimal("0.002")],
            projected_total_quote=Decimal("4"),
            size_mult=Decimal("1"),
            metadata={},
        ),
    )

    buy_spreads, sell_spreads, projected_total_quote, size_mult = EppV24Bot5Controller._compute_levels_and_sizing(
        ctrl,
        "neutral_low_vol",
        _make_regime_spec(one_sided="off"),
        None,
        Decimal("200"),
        Decimal("67000"),
        None,
    )

    assert buy_spreads == [Decimal("0.001")]
    assert sell_spreads == [Decimal("0.001")]
    assert projected_total_quote == Decimal("2")
    assert size_mult == Decimal("1")


def test_bot5_build_runtime_execution_plan_marks_directional_family(monkeypatch) -> None:
    ctrl = _make_bot5_controller(imbalance=Decimal("0.65"))
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

    monkeypatch.setattr(
        DirectionalStrategyRuntimeV24Controller,
        "build_runtime_execution_plan",
        lambda self, data_context: RuntimeExecutionPlan(
            family="directional",
            buy_spreads=[Decimal("0.001"), Decimal("0.002")],
            sell_spreads=[Decimal("0.001"), Decimal("0.002")],
            projected_total_quote=Decimal("4"),
            size_mult=Decimal("1"),
            metadata={"base": "ok"},
        ),
    )

    plan = EppV24Bot5Controller.build_runtime_execution_plan(
        ctrl,
        RuntimeDataContext(
            now_ts=1_000.0,
            mid=Decimal("101"),
            regime_name="up",
            regime_spec=_make_regime_spec(one_sided="off"),
            spread_state=None,
            market=SimpleNamespace(side_spread_floor=Decimal("0.001")),
            equity_quote=Decimal("200"),
            target_base_pct=Decimal("0"),
            target_net_base_pct=Decimal("0.08"),
            base_pct_gross=Decimal("0"),
            base_pct_net=Decimal("0"),
        ),
    )

    assert plan.family == "directional"
    assert plan.buy_spreads == [Decimal("0.001")]
    assert plan.sell_spreads == []
    assert plan.metadata["strategy_lane"] == "bot5"
    assert plan.metadata["directional_allowed"] is True


def test_bot5_reports_strategy_gate_instead_of_shared_alpha_policy() -> None:
    ctrl = _make_bot5_controller(imbalance=Decimal("0.65"))
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

    metrics = EppV24Bot5Controller._compute_alpha_policy(
        ctrl,
        regime_name="up",
        spread_state=None,
        market=None,
        target_net_base_pct=Decimal("0.08"),
        base_pct_net=Decimal("0.0"),
    )

    assert metrics["state"] == "bot5_strategy_gate"
    assert metrics["reason"] == "directional_buy"
    assert ctrl._alpha_cross_allowed is False


def test_bot5_fail_closed_reason_is_bot_specific(monkeypatch) -> None:
    ctrl = _make_bot5_controller()
    ctrl._bot5_flow_state = {
        "direction": "off",
        "imbalance": Decimal("0.80"),
        "trend_displacement_pct": Decimal("0.0100"),
        "signed_signal": Decimal("0.80"),
        "conviction": Decimal("0.95"),
        "bias_active": False,
        "directional_allowed": False,
        "target_net_base_pct": Decimal("0.0"),
        "low_conviction": False,
        "reason": "selective_blocked",
    }

    def _fake_super(self, spread_state, base_pct_gross, equity_quote, projected_total_quote, market):
        return (["shared_reason"], False, Decimal("0"), Decimal("0"))

    monkeypatch.setattr(DirectionalStrategyRuntimeV24Controller, "_evaluate_all_risk", _fake_super)

    reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = EppV24Bot5Controller._evaluate_all_risk(
        ctrl,
        spread_state=None,
        base_pct_gross=Decimal("0"),
        equity_quote=Decimal("1000"),
        projected_total_quote=Decimal("0"),
        market=None,
    )

    assert "shared_reason" in reasons
    assert "bot5_selective_blocked" in reasons
    assert risk_hard_stop is False
    assert daily_loss_pct == Decimal("0")
    assert drawdown_pct == Decimal("0")
