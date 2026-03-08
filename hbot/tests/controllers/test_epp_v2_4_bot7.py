from __future__ import annotations

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
    from controllers.bot7_adaptive_grid_v1 import Bot7AdaptiveGridV1Config, Bot7AdaptiveGridV1Controller
    from controllers.epp_v2_4 import EppV24Config, EppV24Controller
    from controllers.epp_v2_4_bot7 import EppV24Bot7Config, EppV24Bot7Controller
    from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
    from controllers.runtime.market_making_types import MarketConditions, QuoteGeometry, RegimeSpec, SpreadEdgeState
    from services.common.market_data_plane import MarketTrade
else:  # pragma: no cover
    Bot7AdaptiveGridV1Config = object
    Bot7AdaptiveGridV1Controller = object
    MarketConditions = object
    QuoteGeometry = object
    RegimeSpec = object
    SpreadEdgeState = object
    EppV24Config = object
    EppV24Controller = object
    StrategyRuntimeV24Config = object
    StrategyRuntimeV24Controller = object
    EppV24Bot7Config = object
    EppV24Bot7Controller = object
    MarketTrade = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


class _FakePriceBuffer:
    def __init__(self, *, lower: Decimal, basis: Decimal, upper: Decimal, rsi: Decimal, adx: Decimal, atr: Decimal):
        self._lower = lower
        self._basis = basis
        self._upper = upper
        self._rsi = rsi
        self._adx = adx
        self._atr = atr

    def bollinger_bands(self, period: int = 20, stddev_mult: Decimal = Decimal("2")):
        return self._lower, self._basis, self._upper

    def rsi(self, period: int = 14):
        return self._rsi

    def adx(self, period: int = 14):
        return self._adx

    def atr(self, period: int = 14):
        return self._atr


class _FakeTradeReader:
    def __init__(self, trades, imbalance: Decimal = Decimal("0")):
        self._trades = list(trades)
        self._imbalance = imbalance

    def recent_trades(self, count: int = 100):
        return self._trades[-count:]

    def get_depth_imbalance(self, depth: int = 5):
        return self._imbalance


def _make_bot7_config(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="epp_v2_4_bot7_test",
        controller_type="market_making",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        variant="a",
        instance_name="bot7",
        atr_period=14,
        bot7_bb_period=20,
        bot7_bb_stddev=Decimal("2.0"),
        bot7_rsi_period=14,
        bot7_rsi_buy_threshold=Decimal("32"),
        bot7_rsi_sell_threshold=Decimal("68"),
        bot7_adx_period=14,
        bot7_adx_activate_below=Decimal("20"),
        bot7_trade_window_count=60,
        bot7_trade_stale_after_ms=15_000,
        bot7_absorption_min_trade_mult=Decimal("2.5"),
        bot7_absorption_max_price_drift_pct=Decimal("0.0015"),
        bot7_delta_trap_window=24,
        bot7_delta_trap_reversal_share=Decimal("0.30"),
        bot7_grid_spacing_atr_mult=Decimal("0.50"),
        bot7_grid_spacing_floor_pct=Decimal("0.0015"),
        bot7_grid_spacing_cap_pct=Decimal("0.0100"),
        bot7_max_grid_legs=3,
        bot7_per_leg_risk_pct=Decimal("0.003"),
        bot7_total_grid_exposure_cap_pct=Decimal("0.015"),
        bot7_hedge_ratio=Decimal("0.30"),
        bot7_funding_long_bias_threshold=Decimal("-0.0003"),
        bot7_funding_short_bias_threshold=Decimal("0.0003"),
        bot7_funding_vol_reduce_threshold=Decimal("0.0010"),
        min_net_edge_bps=Decimal("1.5"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_trade(idx: int, *, price: str, size: str, delta: str, ts_ms: int) -> MarketTrade:
    delta_d = Decimal(delta)
    return MarketTrade(
        trade_id=f"t{idx}",
        side="buy" if delta_d >= 0 else "sell",
        price=Decimal(price),
        size=Decimal(size),
        delta=delta_d,
        exchange_ts_ms=ts_ms,
        ingest_ts_ms=ts_ms,
        market_sequence=idx,
        aggressor_side="buy" if delta_d >= 0 else "sell",
    )


def _make_bot7_controller(*, config: SimpleNamespace | None = None, price_buffer=None, trades=None) -> EppV24Bot7Controller:
    ctrl = object.__new__(EppV24Bot7Controller)
    ctrl.config = config or _make_bot7_config()
    ctrl._price_buffer = price_buffer or _FakePriceBuffer(
        lower=Decimal("95"),
        basis=Decimal("100"),
        upper=Decimal("105"),
        rsi=Decimal("28"),
        adx=Decimal("15"),
        atr=Decimal("2"),
    )
    ctrl._trade_reader = _FakeTradeReader(trades or [])
    ctrl._bot7_state = EppV24Bot7Controller._empty_bot7_state(ctrl)
    ctrl._bot7_last_funding_rate = Decimal("0")
    ctrl._funding_rate = Decimal("-0.0004")
    ctrl._is_perp = True
    ctrl._pending_stale_cancel_actions = []
    ctrl._quote_side_mode = "off"
    ctrl._quote_side_reason = "inactive"
    ctrl._cancel_stale_side_executors = lambda old, new: []
    ctrl._runtime_levels = SimpleNamespace(executor_refresh_time=0)
    ctrl._compute_pnl_governor_size_mult = lambda equity_quote, turnover_x: Decimal("1")
    ctrl._project_total_amount_quote = (
        lambda equity_quote, mid, quote_size_pct, total_levels, size_mult: equity_quote * quote_size_pct * Decimal(total_levels) * size_mult
    )
    ctrl.market_data_provider = SimpleNamespace(time=lambda: 1000.0)
    return ctrl


def _make_regime_spec(one_sided: str = "off") -> RegimeSpec:
    return RegimeSpec(
        spread_min=Decimal("0.0010"),
        spread_max=Decimal("0.0040"),
        levels_min=1,
        levels_max=3,
        refresh_s=30,
        target_base_pct=Decimal("0"),
        quote_size_pct_min=Decimal("0.003"),
        quote_size_pct_max=Decimal("0.003"),
        one_sided=one_sided,
        fill_factor=Decimal("0.9"),
    )


def test_bot7_controller_reuses_shared_runtime_stack() -> None:
    assert issubclass(Bot7AdaptiveGridV1Config, StrategyRuntimeV24Config)
    assert issubclass(Bot7AdaptiveGridV1Controller, StrategyRuntimeV24Controller)
    assert Bot7AdaptiveGridV1Config.controller_name == "bot7_adaptive_grid_v1"

    assert issubclass(EppV24Bot7Config, Bot7AdaptiveGridV1Config)
    assert issubclass(EppV24Bot7Controller, Bot7AdaptiveGridV1Controller)
    assert issubclass(EppV24Bot7Config, StrategyRuntimeV24Config)
    assert issubclass(EppV24Bot7Controller, StrategyRuntimeV24Controller)
    assert issubclass(EppV24Bot7Config, EppV24Config)
    assert issubclass(EppV24Bot7Controller, EppV24Controller)
    assert EppV24Bot7Config.controller_name == "epp_v2_4_bot7"


def test_bot7_activates_buy_signal_on_lower_band_absorption() -> None:
    trades = [
        _make_trade(1, price="94.98", size="0.4", delta="-0.4", ts_ms=999_200),
        _make_trade(2, price="94.97", size="0.4", delta="-0.4", ts_ms=999_300),
        _make_trade(3, price="94.96", size="0.5", delta="-0.5", ts_ms=999_400),
        _make_trade(4, price="94.95", size="0.5", delta="0.6", ts_ms=999_500),
        _make_trade(5, price="94.94", size="0.6", delta="0.6", ts_ms=999_600),
        _make_trade(6, price="94.93", size="6.0", delta="6.0", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(trades=trades)

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("94.94"), regime_name="neutral_low_vol")

    assert state["active"] is True
    assert state["side"] == "buy"
    assert state["absorption_long"] is True
    assert state["target_net_base_pct"] > Decimal("0")
    assert state["grid_levels"] >= 1


def test_bot7_fails_closed_when_trade_tape_is_stale() -> None:
    trades = [
        _make_trade(1, price="94.98", size="1.0", delta="1.0", ts_ms=900_000),
        _make_trade(2, price="94.97", size="1.0", delta="1.0", ts_ms=900_100),
    ]
    ctrl = _make_bot7_controller(trades=trades)

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("94.95"), regime_name="neutral_low_vol")

    assert state["active"] is False
    assert state["trade_flow_stale"] is True


def test_bot7_builds_sell_only_grid_when_short_signal_is_active() -> None:
    trades = [
        _make_trade(1, price="105.00", size="0.4", delta="0.4", ts_ms=999_200),
        _make_trade(2, price="105.02", size="0.4", delta="0.4", ts_ms=999_300),
        _make_trade(3, price="105.03", size="0.5", delta="0.5", ts_ms=999_400),
        _make_trade(4, price="105.04", size="0.5", delta="-0.6", ts_ms=999_500),
        _make_trade(5, price="105.05", size="0.6", delta="-0.6", ts_ms=999_600),
        _make_trade(6, price="105.06", size="6.0", delta="-6.0", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(
        price_buffer=_FakePriceBuffer(
            lower=Decimal("95"),
            basis=Decimal("100"),
            upper=Decimal("105"),
            rsi=Decimal("72"),
            adx=Decimal("14"),
            atr=Decimal("2"),
        ),
        trades=trades,
    )
    ctrl._funding_rate = Decimal("0.0004")
    spread_state = SpreadEdgeState(
        band_pct=Decimal("0.002"),
        spread_pct=Decimal("0.002"),
        net_edge=Decimal("0.0010"),
        skew=Decimal("0"),
        adverse_drift=Decimal("0"),
        smooth_drift=Decimal("0"),
        drift_spread_mult=Decimal("1"),
        turnover_x=Decimal("0"),
        min_edge_threshold=Decimal("0.0001"),
        edge_resume_threshold=Decimal("0.0002"),
        fill_factor=Decimal("0.9"),
        quote_geometry=QuoteGeometry(
            base_spread_pct=Decimal("0.002"),
            spread_floor_pct=Decimal("0.001"),
            reservation_price_adjustment_pct=Decimal("0"),
            inventory_urgency=Decimal("0"),
            inventory_skew=Decimal("0"),
            alpha_skew=Decimal("0"),
        ),
    )
    market = MarketConditions(
        is_high_vol=False,
        bid_p=Decimal("104.9"),
        ask_p=Decimal("105.1"),
        market_spread_pct=Decimal("0.002"),
        best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"),
        connector_ready=True,
        order_book_stale=False,
        market_spread_too_small=False,
        side_spread_floor=Decimal("0.001"),
    )

    buy_spreads, sell_spreads, projected_total_quote, size_mult = EppV24Bot7Controller._compute_levels_and_sizing(
        ctrl,
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
        spread_state=spread_state,
        equity_quote=Decimal("1000"),
        mid=Decimal("105.04"),
        market=market,
    )

    assert buy_spreads == []
    assert len(sell_spreads) >= 1
    assert projected_total_quote > Decimal("0")
    assert size_mult > Decimal("0")
