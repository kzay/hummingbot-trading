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
    from controllers.bot6_cvd_divergence_v1 import Bot6CvdDivergenceV1Config, Bot6CvdDivergenceV1Controller
    from controllers.epp_v2_4 import EppV24Config, EppV24Controller
    from controllers.epp_v2_4_bot6 import EppV24Bot6Config, EppV24Bot6Controller
    from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
    from controllers.runtime.data_context import RuntimeDataContext
    from controllers.runtime.directional_core import DirectionalRuntimeAdapter
    from controllers.runtime.execution_context import RuntimeExecutionPlan
    from controllers.runtime.market_making_types import RegimeSpec
    from services.common.market_data_plane import DirectionalTradeFeatures, TradeFlowFeatures
else:  # pragma: no cover - stripped environments
    Bot6CvdDivergenceV1Config = object
    Bot6CvdDivergenceV1Controller = object
    EppV24Config = object
    EppV24Controller = object
    DirectionalRuntimeAdapter = object
    RuntimeDataContext = object
    RuntimeExecutionPlan = object
    RegimeSpec = object
    StrategyRuntimeV24Config = object
    StrategyRuntimeV24Controller = object
    EppV24Bot6Config = object
    EppV24Bot6Controller = object
    DirectionalTradeFeatures = object
    TradeFlowFeatures = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


def test_bot6_controller_reuses_shared_runtime_stack() -> None:
    assert issubclass(Bot6CvdDivergenceV1Config, StrategyRuntimeV24Config)
    assert issubclass(Bot6CvdDivergenceV1Controller, StrategyRuntimeV24Controller)
    assert Bot6CvdDivergenceV1Config.controller_name == "bot6_cvd_divergence_v1"

    assert issubclass(EppV24Bot6Config, Bot6CvdDivergenceV1Config)
    assert issubclass(EppV24Bot6Controller, Bot6CvdDivergenceV1Controller)
    assert issubclass(EppV24Bot6Config, StrategyRuntimeV24Config)
    assert issubclass(EppV24Bot6Controller, StrategyRuntimeV24Controller)
    assert issubclass(EppV24Bot6Config, EppV24Config)
    assert issubclass(EppV24Bot6Controller, EppV24Controller)
    assert EppV24Bot6Config.controller_name == "epp_v2_4_bot6"


def test_bot6_controller_uses_directional_family_adapter() -> None:
    ctrl = object.__new__(EppV24Bot6Controller)
    adapter = EppV24Bot6Controller._make_runtime_family_adapter(ctrl)
    assert isinstance(adapter, DirectionalRuntimeAdapter)


def _make_bot6_config(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="epp_v2_4_bot6_test",
        controller_type="market_making",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        candles_connector="bitget_perpetual",
        candles_trading_pair="BTC-USDT",
        variant="a",
        instance_name="bot6",
        max_base_pct=Decimal("0.20"),
        bot6_spot_connector_name="bitget",
        bot6_spot_trading_pair="BTC-USDT",
        bot6_candle_interval="15m",
        bot6_sma_fast_period=50,
        bot6_sma_slow_period=200,
        bot6_adx_period=14,
        bot6_adx_threshold=Decimal("25"),
        bot6_trade_window_count=120,
        bot6_spot_trade_window_count=120,
        bot6_trade_features_stale_after_ms=90000,
        bot6_cvd_divergence_threshold_pct=Decimal("0.15"),
        bot6_stacked_imbalance_min=3,
        bot6_delta_spike_threshold=Decimal("3.0"),
        bot6_signal_score_threshold=7,
        bot6_directional_target_net_base_pct=Decimal("0.12"),
        bot6_dynamic_size_floor_mult=Decimal("0.80"),
        bot6_dynamic_size_cap_mult=Decimal("1.50"),
        bot6_long_funding_max=Decimal("0.0005"),
        bot6_short_funding_min=Decimal("-0.0003"),
        bot6_partial_exit_on_flip_ratio=Decimal("0.50"),
        bot6_enable_hedge_bias=True,
        alpha_policy_enabled=False,
        selective_quoting_enabled=False,
        adverse_fill_soft_pause_enabled=False,
        edge_confidence_soft_pause_enabled=False,
        slippage_soft_pause_enabled=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_bot6_config_disables_shared_trade_quality_gates() -> None:
    cfg = EppV24Bot6Config(
        id="bot6_cfg_test",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("10"),
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


def _trade_features(
    *,
    long_score: int,
    short_score: int,
    divergence_ratio: str,
    funding_bias: str = "long",
    stale: bool = False,
) -> DirectionalTradeFeatures:
    futures = TradeFlowFeatures(
        trade_count=120,
        buy_volume=Decimal("15"),
        sell_volume=Decimal("5"),
        delta_volume=Decimal("10"),
        cvd=Decimal("10"),
        last_price=Decimal("101"),
        latest_ts_ms=1,
        stale=stale,
        imbalance_ratio=Decimal("0.50"),
        stacked_buy_count=4,
        stacked_sell_count=1,
        delta_spike_ratio=Decimal("3.5"),
    )
    spot = TradeFlowFeatures(
        trade_count=120,
        buy_volume=Decimal("18"),
        sell_volume=Decimal("4"),
        delta_volume=Decimal("14"),
        cvd=Decimal("14"),
        last_price=Decimal("100"),
        latest_ts_ms=1,
        stale=stale,
        imbalance_ratio=Decimal("0.63"),
        stacked_buy_count=3,
        stacked_sell_count=0,
        delta_spike_ratio=Decimal("2.0"),
    )
    return DirectionalTradeFeatures(
        futures=futures,
        spot=spot,
        futures_price_change_pct=Decimal("-0.01"),
        spot_price_change_pct=Decimal("0.005"),
        cvd_divergence_ratio=Decimal(divergence_ratio),
        bullish_divergence=True,
        bearish_divergence=False,
        funding_rate=Decimal("0.0002"),
        funding_bias=funding_bias,
        funding_aligned_long=True,
        funding_aligned_short=False,
        long_score=long_score,
        short_score=short_score,
        stale=stale,
    )


def _make_bot6_controller(*, config: SimpleNamespace | None = None) -> EppV24Bot6Controller:
    ctrl = object.__new__(EppV24Bot6Controller)
    ctrl.config = config or _make_bot6_config()
    ctrl._is_perp = True
    ctrl._funding_rate = Decimal("0.0002")
    ctrl._position_base = Decimal("0")
    ctrl._quote_side_mode = "off"
    ctrl._quote_side_reason = "regime"
    ctrl._pending_stale_cancel_actions = []
    ctrl.executors_info = []
    ctrl.processed_data = {}
    ctrl._bot6_signal_state = EppV24Bot6Controller._empty_bot6_signal_state(ctrl)
    ctrl._cancel_stale_side_executors = MethodType(EppV24Controller._cancel_stale_side_executors, ctrl)
    ctrl.market_data_provider = SimpleNamespace(time=lambda: 1_000.0)
    return ctrl


def test_bot6_targets_directional_net_bias_on_strong_bullish_cvd() -> None:
    ctrl = _make_bot6_controller()
    ctrl._detect_regime = lambda mid: ("up", _make_regime_spec(), Decimal("0.0025"))
    ctrl._get_bot6_candle_signal = lambda: {
        "sma_fast": Decimal("101"),
        "sma_slow": Decimal("100"),
        "adx": Decimal("31"),
    }
    ctrl._runtime_adapter = SimpleNamespace(
        get_directional_trade_features=lambda **_kwargs: _trade_features(
            long_score=8,
            short_score=1,
            divergence_ratio="0.22",
        )
    )

    regime_name, _regime_spec, _target_base_pct, target_net_base_pct, _band_pct = (
        EppV24Bot6Controller._resolve_regime_and_targets(ctrl, Decimal("101.0"))
    )

    assert regime_name == "up"
    assert target_net_base_pct > Decimal("0")
    assert ctrl._bot6_signal_state["direction"] == "buy"
    assert ctrl._bot6_signal_state["active_score"] >= 8


def test_bot6_can_infer_direction_from_trade_scores_when_candles_unavailable() -> None:
    ctrl = _make_bot6_controller()
    ctrl._get_bot6_candle_signal = lambda: {
        "sma_fast": Decimal("0"),
        "sma_slow": Decimal("0"),
        "adx": Decimal("0"),
    }
    ctrl._runtime_adapter = SimpleNamespace(
        get_directional_trade_features=lambda **_kwargs: _trade_features(
            long_score=8,
            short_score=1,
            divergence_ratio="0.22",
            stale=False,
        )
    )

    signal_state = EppV24Bot6Controller._bot6_update_signal_state(ctrl, Decimal("101.0"))

    assert signal_state["trend_direction"] == "long"
    assert signal_state["direction"] == "buy"


def test_bot6_flags_partial_exit_hedge_candidate_on_divergence_flip() -> None:
    ctrl = _make_bot6_controller()
    ctrl._position_base = Decimal("0.30")
    ctrl._get_bot6_candle_signal = lambda: {
        "sma_fast": Decimal("99"),
        "sma_slow": Decimal("100"),
        "adx": Decimal("32"),
    }
    ctrl._runtime_adapter = SimpleNamespace(
        get_directional_trade_features=lambda **_kwargs: DirectionalTradeFeatures(
            futures=TradeFlowFeatures(stacked_sell_count=4, delta_spike_ratio=Decimal("3.2"), cvd=Decimal("-8")),
            spot=TradeFlowFeatures(cvd=Decimal("-10")),
            futures_price_change_pct=Decimal("0.01"),
            spot_price_change_pct=Decimal("-0.005"),
            cvd_divergence_ratio=Decimal("-0.18"),
            bullish_divergence=False,
            bearish_divergence=True,
            funding_rate=Decimal("-0.0004"),
            funding_bias="short",
            funding_aligned_long=False,
            funding_aligned_short=True,
            long_score=1,
            short_score=8,
            stale=False,
        )
    )

    signal_state = EppV24Bot6Controller._bot6_update_signal_state(ctrl, Decimal("99.5"))

    assert signal_state["direction"] == "sell"
    assert signal_state["hedge_state"] == "candidate_short_hedge"
    assert signal_state["partial_exit_ratio"] == Decimal("0.50")


def test_bot6_quote_side_switches_to_directional_mode_when_signal_active() -> None:
    sell_executor = SimpleNamespace(
        is_active=True,
        id="exec-sell",
        custom_info={"level_id": "sell_0"},
    )
    ctrl = _make_bot6_controller()
    ctrl.executors_info = [sell_executor]
    ctrl._bot6_signal_state = {
        **EppV24Bot6Controller._empty_bot6_signal_state(ctrl),
        "direction": "buy",
        "directional_allowed": True,
        "reason": "bullish_cvd_divergence",
    }

    mode = EppV24Bot6Controller._resolve_quote_side_mode(
        ctrl,
        mid=Decimal("101.0"),
        regime_name="up",
        regime_spec=_make_regime_spec(one_sided="off"),
    )

    assert mode == "buy_only"
    assert ctrl._quote_side_reason == "bot6_bullish_cvd_divergence"
    assert len(ctrl._pending_stale_cancel_actions) == 1


def test_bot6_keeps_two_sided_quotes_when_regime_mode_is_off(monkeypatch) -> None:
    ctrl = _make_bot6_controller()
    ctrl._bot6_signal_state = {
        **EppV24Bot6Controller._empty_bot6_signal_state(ctrl),
        "direction": "off",
        "directional_allowed": False,
        "reason": "trade_features_warmup",
    }
    ctrl._quote_side_mode = "off"
    ctrl._project_total_amount_quote = lambda **kwargs: Decimal(kwargs["total_levels"])

    monkeypatch.setattr(
        StrategyRuntimeV24Controller,
        "build_runtime_execution_plan",
        lambda self, data_context: RuntimeExecutionPlan(
            family="market_making",
            buy_spreads=[Decimal("0.001"), Decimal("0.002")],
            sell_spreads=[Decimal("0.001"), Decimal("0.002")],
            projected_total_quote=Decimal("4"),
            size_mult=Decimal("1"),
            metadata={},
        ),
    )

    buy_spreads, sell_spreads, projected_total_quote, size_mult = EppV24Bot6Controller._compute_levels_and_sizing(
        ctrl,
        "neutral_low_vol",
        _make_regime_spec(one_sided="off"),
        None,
        Decimal("250"),
        Decimal("67000"),
        None,
    )

    assert buy_spreads == [Decimal("0.001"), Decimal("0.002")]
    assert sell_spreads == [Decimal("0.001"), Decimal("0.002")]
    assert projected_total_quote == Decimal("4")
    assert size_mult == Decimal("1")


def test_bot6_build_runtime_execution_plan_marks_directional_family(monkeypatch) -> None:
    ctrl = _make_bot6_controller()
    ctrl._bot6_signal_state = {
        **EppV24Bot6Controller._empty_bot6_signal_state(ctrl),
        "direction": "buy",
        "directional_allowed": True,
        "active_score": 9,
        "size_mult": Decimal("1.3"),
        "reason": "bullish_cvd_divergence",
    }

    monkeypatch.setattr(
        StrategyRuntimeV24Controller,
        "build_runtime_execution_plan",
        lambda self, data_context: RuntimeExecutionPlan(
            family="market_making",
            buy_spreads=[Decimal("0.001"), Decimal("0.002")],
            sell_spreads=[Decimal("0.001"), Decimal("0.002")],
            projected_total_quote=Decimal("4"),
            size_mult=Decimal("1"),
            metadata={"base": "ok"},
        ),
    )

    plan = EppV24Bot6Controller.build_runtime_execution_plan(
        ctrl,
        RuntimeDataContext(
            now_ts=1_000.0,
            mid=Decimal("101"),
            regime_name="up",
            regime_spec=_make_regime_spec(one_sided="off"),
            spread_state=None,
            market=SimpleNamespace(side_spread_floor=Decimal("0.001")),
            equity_quote=Decimal("250"),
            target_base_pct=Decimal("0"),
            target_net_base_pct=Decimal("0.12"),
            base_pct_gross=Decimal("0"),
            base_pct_net=Decimal("0"),
        ),
    )

    assert plan.family == "directional"
    assert plan.buy_spreads == [Decimal("0.001")]
    assert plan.sell_spreads == []
    assert plan.size_mult == Decimal("1.3")
    assert plan.metadata["strategy_lane"] == "bot6"


def test_bot6_reports_strategy_gate_instead_of_shared_alpha_policy() -> None:
    ctrl = _make_bot6_controller()
    ctrl._bot6_signal_state = {
        **EppV24Bot6Controller._empty_bot6_signal_state(ctrl),
        "direction": "buy",
        "directional_allowed": True,
        "active_score": 9,
        "reason": "bullish_cvd_divergence",
    }

    metrics = EppV24Bot6Controller._compute_alpha_policy(
        ctrl,
        regime_name="up",
        spread_state=None,
        market=None,
        target_net_base_pct=Decimal("0.12"),
        base_pct_net=Decimal("0.0"),
    )

    assert metrics["state"] == "bot6_strategy_gate"
    assert metrics["reason"] == "bullish_cvd_divergence"
    assert ctrl._alpha_cross_allowed is False


def test_bot6_trade_feature_warmup_does_not_hard_block_risk(monkeypatch) -> None:
    ctrl = _make_bot6_controller()
    ctrl._bot6_signal_state = {
        **EppV24Bot6Controller._empty_bot6_signal_state(ctrl),
        "reason": "trade_features_warmup",
    }

    def _fake_super(self, spread_state, base_pct_gross, equity_quote, projected_total_quote, market):
        return (["shared_reason"], False, Decimal("0"), Decimal("0"))

    monkeypatch.setattr(StrategyRuntimeV24Controller, "_evaluate_all_risk", _fake_super)

    reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = EppV24Bot6Controller._evaluate_all_risk(
        ctrl,
        spread_state=None,
        base_pct_gross=Decimal("0"),
        equity_quote=Decimal("1000"),
        projected_total_quote=Decimal("0"),
        market=None,
    )

    assert "shared_reason" in reasons
    assert "bot6_trade_features_stale" not in reasons
    assert risk_hard_stop is False
    assert daily_loss_pct == Decimal("0")
    assert drawdown_pct == Decimal("0")
