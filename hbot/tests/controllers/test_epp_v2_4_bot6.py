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
    from controllers.runtime.market_making_types import RegimeSpec
    from services.common.market_data_plane import DirectionalTradeFeatures, TradeFlowFeatures
else:  # pragma: no cover - stripped environments
    Bot6CvdDivergenceV1Config = object
    Bot6CvdDivergenceV1Controller = object
    EppV24Config = object
    EppV24Controller = object
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
