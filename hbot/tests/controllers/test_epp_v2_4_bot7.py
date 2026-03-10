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
    from controllers.runtime.data_context import RuntimeDataContext
    from controllers.runtime.directional_core import DirectionalRuntimeAdapter
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
    DirectionalRuntimeAdapter = object
    RuntimeDataContext = object
    StrategyRuntimeV24Config = object
    StrategyRuntimeV24Controller = object
    EppV24Bot7Config = object
    EppV24Bot7Controller = object
    MarketTrade = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


class _FakePriceBuffer:
    def __init__(self, *, lower: Decimal, basis: Decimal, upper: Decimal, rsi: Decimal, adx: Decimal, atr):
        self._lower = lower
        self._basis = basis
        self._upper = upper
        self._rsi = rsi
        self._adx = adx
        self._atr = atr
        self._bars = [object()] * 20

    @property
    def bars(self):
        return self._bars

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
        bot7_rsi_probe_buy_threshold=Decimal("38"),
        bot7_rsi_probe_sell_threshold=Decimal("62"),
        bot7_adx_period=14,
        bot7_adx_activate_below=Decimal("20"),
        bot7_adx_neutral_fallback_below=Decimal("28"),
        bot7_trade_window_count=60,
        bot7_trade_stale_after_ms=15_000,
        bot7_absorption_min_trade_mult=Decimal("2.5"),
        bot7_absorption_max_price_drift_pct=Decimal("0.0015"),
        bot7_delta_trap_window=24,
        bot7_delta_trap_reversal_share=Decimal("0.30"),
        bot7_grid_spacing_atr_mult=Decimal("0.50"),
        bot7_grid_spacing_floor_pct=Decimal("0.0015"),
        bot7_grid_spacing_cap_pct=Decimal("0.0100"),
        bot7_touch_tolerance_pct=Decimal("0.0015"),
        bot7_depth_imbalance_reversal_threshold=Decimal("0.12"),
        bot7_max_grid_legs=3,
        bot7_per_leg_risk_pct=Decimal("0.003"),
        bot7_total_grid_exposure_cap_pct=Decimal("0.015"),
        bot7_hedge_ratio=Decimal("0.30"),
        bot7_funding_long_bias_threshold=Decimal("-0.0003"),
        bot7_funding_short_bias_threshold=Decimal("0.0003"),
        bot7_funding_vol_reduce_threshold=Decimal("0.0010"),
        bot7_warmup_quote_levels=1,
        bot7_warmup_quote_max_bars=3,
        bot7_probe_enabled=True,
        bot7_probe_grid_legs=1,
        bot7_probe_size_mult=Decimal("0.50"),
        alpha_policy_enabled=False,
        selective_quoting_enabled=False,
        adverse_fill_soft_pause_enabled=False,
        edge_confidence_soft_pause_enabled=False,
        slippage_soft_pause_enabled=False,
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


def test_bot7_controller_uses_directional_family_adapter() -> None:
    ctrl = object.__new__(EppV24Bot7Controller)
    adapter = EppV24Bot7Controller._make_runtime_family_adapter(ctrl)
    assert isinstance(adapter, DirectionalRuntimeAdapter)


def test_bot7_config_disables_shared_alpha_and_selective_gates() -> None:
    cfg = EppV24Bot7Config(
        id="bot7_cfg_test",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        total_amount_quote=Decimal("6"),
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


def test_bot7_activates_probe_buy_signal_when_neutral_regime_has_depth_reversal() -> None:
    trades = [
        _make_trade(1, price="95.02", size="0.7", delta="-0.2", ts_ms=999_200),
        _make_trade(2, price="95.00", size="0.8", delta="-0.1", ts_ms=999_300),
        _make_trade(3, price="94.99", size="0.7", delta="0.2", ts_ms=999_400),
        _make_trade(4, price="94.98", size="0.7", delta="0.2", ts_ms=999_500),
        _make_trade(5, price="94.97", size="0.6", delta="0.1", ts_ms=999_650),
        _make_trade(6, price="94.96", size="0.6", delta="0.1", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(
        config=_make_bot7_config(),
        price_buffer=_FakePriceBuffer(
            lower=Decimal("95"),
            basis=Decimal("100"),
            upper=Decimal("105"),
            rsi=Decimal("36"),
            adx=Decimal("24"),
            atr=Decimal("2"),
        ),
        trades=trades,
    )
    ctrl._trade_reader = _FakeTradeReader(trades, imbalance=Decimal("0.18"))

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("95.04"), regime_name="neutral_low_vol")

    assert state["active"] is True
    assert state["probe_mode"] is True
    assert state["side"] == "buy"
    assert state["reason"] == "probe_long"
    assert state["grid_levels"] == 1
    assert state["target_net_base_pct"] == Decimal("0.0015")


def test_bot7_fails_closed_when_trade_tape_is_stale() -> None:
    trades = [
        _make_trade(1, price="94.98", size="1.0", delta="1.0", ts_ms=900_000),
        _make_trade(2, price="94.97", size="1.0", delta="1.0", ts_ms=900_100),
    ]
    ctrl = _make_bot7_controller(trades=trades)

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("94.95"), regime_name="neutral_low_vol")

    assert state["active"] is False
    assert state["trade_flow_stale"] is True


def test_bot7_allows_signal_when_atr_is_not_ready() -> None:
    trades = [
        _make_trade(1, price="94.98", size="0.4", delta="-0.4", ts_ms=999_200),
        _make_trade(2, price="94.97", size="0.4", delta="-0.4", ts_ms=999_300),
        _make_trade(3, price="94.96", size="0.5", delta="-0.5", ts_ms=999_400),
        _make_trade(4, price="94.95", size="0.5", delta="0.6", ts_ms=999_500),
        _make_trade(5, price="94.94", size="0.6", delta="0.6", ts_ms=999_600),
        _make_trade(6, price="94.93", size="6.0", delta="6.0", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(
        price_buffer=_FakePriceBuffer(
            lower=Decimal("95"),
            basis=Decimal("100"),
            upper=Decimal("105"),
            rsi=Decimal("28"),
            adx=Decimal("15"),
            atr=None,
        ),
        trades=trades,
    )

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("94.94"), regime_name="neutral_low_vol")

    assert state["active"] is True
    assert state["reason"] == "mean_reversion_long"
    assert state["indicator_ready"] is True
    assert state["indicator_missing"] == "atr"
    assert state["price_buffer_bars"] == 20


def test_bot7_builds_two_sided_warmup_quotes_when_indicators_not_ready() -> None:
    ctrl = _make_bot7_controller(trades=[])
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": False,
        "reason": "indicator_warmup",
        "price_buffer_bars": 2,
        "trade_flow_stale": False,
        "funding_risk_scale": Decimal("1"),
    }
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
        bid_p=Decimal("99.9"),
        ask_p=Decimal("100.1"),
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
        mid=Decimal("100"),
        market=market,
    )

    assert buy_spreads == [Decimal("0.0015")]
    assert sell_spreads == [Decimal("0.0015")]
    assert projected_total_quote > Decimal("0")
    assert size_mult == Decimal("1")


def test_bot7_skips_warmup_quotes_after_bootstrap_window() -> None:
    ctrl = _make_bot7_controller()
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": False,
        "reason": "indicator_warmup",
        "price_buffer_bars": 4,
        "trade_flow_stale": False,
        "funding_risk_scale": Decimal("1"),
    }

    buy_spreads, sell_spreads, projected_total_quote, size_mult = EppV24Bot7Controller._compute_levels_and_sizing(
        ctrl,
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
        spread_state=SpreadEdgeState(
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
        ),
        equity_quote=Decimal("1000"),
        mid=Decimal("100"),
        market=MarketConditions(
            is_high_vol=False,
            bid_p=Decimal("99.9"),
            ask_p=Decimal("100.1"),
            market_spread_pct=Decimal("0.002"),
            best_bid_size=Decimal("1"),
            best_ask_size=Decimal("1"),
            connector_ready=True,
            order_book_stale=False,
            market_spread_too_small=False,
            side_spread_floor=Decimal("0.001"),
        ),
    )

    assert buy_spreads == []
    assert sell_spreads == []
    assert projected_total_quote == Decimal("0")
    assert size_mult == Decimal("0")


def test_bot7_skips_quotes_when_trade_flow_is_stale() -> None:
    ctrl = _make_bot7_controller()
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": False,
        "reason": "trade_flow_stale",
        "price_buffer_bars": 1,
        "trade_flow_stale": True,
        "funding_risk_scale": Decimal("1"),
    }

    buy_spreads, sell_spreads, projected_total_quote, size_mult = EppV24Bot7Controller._compute_levels_and_sizing(
        ctrl,
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
        spread_state=SpreadEdgeState(
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
        ),
        equity_quote=Decimal("1000"),
        mid=Decimal("100"),
        market=MarketConditions(
            is_high_vol=False,
            bid_p=Decimal("99.9"),
            ask_p=Decimal("100.1"),
            market_spread_pct=Decimal("0.002"),
            best_bid_size=Decimal("1"),
            best_ask_size=Decimal("1"),
            connector_ready=True,
            order_book_stale=False,
            market_spread_too_small=False,
            side_spread_floor=Decimal("0.001"),
        ),
    )

    assert buy_spreads == []
    assert sell_spreads == []
    assert projected_total_quote == Decimal("0")
    assert size_mult == Decimal("0")


def test_bot7_requests_cancel_of_active_quotes_when_trade_flow_turns_stale() -> None:
    ctrl = _make_bot7_controller()
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": False,
        "reason": "trade_flow_stale",
        "price_buffer_bars": 1,
        "trade_flow_stale": True,
    }
    ctrl._quote_side_mode = "buy_only"
    ctrl._pending_stale_cancel_actions = []
    ctrl._cancel_active_quote_executors = lambda: ["cancel_all_quotes"]

    mode = EppV24Bot7Controller._resolve_quote_side_mode(
        ctrl,
        mid=Decimal("100"),
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
    )

    assert mode == "off"
    assert "cancel_all_quotes" in ctrl._pending_stale_cancel_actions


def test_bot7_requests_cancel_of_expired_warmup_quotes() -> None:
    ctrl = _make_bot7_controller()
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": False,
        "reason": "indicator_warmup",
        "price_buffer_bars": 5,
        "trade_flow_stale": False,
    }
    ctrl._quote_side_mode = "off"
    ctrl._pending_stale_cancel_actions = []
    ctrl._cancel_active_quote_executors = lambda: ["cancel_expired_warmup_quotes"]

    mode = EppV24Bot7Controller._resolve_quote_side_mode(
        ctrl,
        mid=Decimal("100"),
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
    )

    assert mode == "off"
    assert "cancel_expired_warmup_quotes" in ctrl._pending_stale_cancel_actions


@pytest.mark.parametrize("reason", ["regime_inactive", "no_entry"])
def test_bot7_requests_cancel_of_active_quotes_when_off_state_keeps_lingering_orders(reason: str) -> None:
    ctrl = _make_bot7_controller()
    paper_cancel_calls = []
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": False,
        "reason": reason,
        "price_buffer_bars": 20,
        "trade_flow_stale": False,
    }
    ctrl._quote_side_mode = "off"
    ctrl._pending_stale_cancel_actions = []
    ctrl._cancel_active_quote_executors = lambda: [f"cancel_{reason}_quotes"]
    ctrl._cancel_alpha_no_trade_paper_orders = lambda: paper_cancel_calls.append(reason)

    mode = EppV24Bot7Controller._resolve_quote_side_mode(
        ctrl,
        mid=Decimal("100"),
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
    )

    assert mode == "off"
    assert f"cancel_{reason}_quotes" in ctrl._pending_stale_cancel_actions
    assert paper_cancel_calls == [reason]


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


def test_bot7_probe_signal_limits_grid_size_and_quote_side() -> None:
    trades = [
        _make_trade(1, price="95.02", size="0.7", delta="-0.2", ts_ms=999_200),
        _make_trade(2, price="95.00", size="0.8", delta="-0.1", ts_ms=999_300),
        _make_trade(3, price="94.99", size="0.7", delta="0.2", ts_ms=999_400),
        _make_trade(4, price="94.98", size="0.7", delta="0.2", ts_ms=999_500),
        _make_trade(5, price="94.97", size="0.6", delta="0.1", ts_ms=999_650),
        _make_trade(6, price="94.96", size="0.6", delta="0.1", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(
        price_buffer=_FakePriceBuffer(
            lower=Decimal("95"),
            basis=Decimal("100"),
            upper=Decimal("105"),
            rsi=Decimal("36"),
            adx=Decimal("24"),
            atr=Decimal("2"),
        ),
        trades=trades,
    )
    ctrl._trade_reader = _FakeTradeReader(trades, imbalance=Decimal("0.18"))
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
        bid_p=Decimal("94.9"),
        ask_p=Decimal("95.1"),
        market_spread_pct=Decimal("0.002"),
        best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"),
        connector_ready=True,
        order_book_stale=False,
        market_spread_too_small=False,
        side_spread_floor=Decimal("0.001"),
    )

    buy_spreads, sell_spreads, projected_total_quote, _ = EppV24Bot7Controller._compute_levels_and_sizing(
        ctrl,
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
        spread_state=spread_state,
        equity_quote=Decimal("1000"),
        mid=Decimal("95.04"),
        market=market,
    )

    assert len(buy_spreads) == 1
    assert sell_spreads == []
    assert projected_total_quote > Decimal("0")
    assert ctrl._bot7_state["probe_mode"] is True


def test_bot7_reports_strategy_gate_instead_of_shared_alpha_policy() -> None:
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
    metrics = EppV24Bot7Controller._compute_alpha_policy(
        ctrl,
        regime_name="neutral_low_vol",
        spread_state=SpreadEdgeState(
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
        ),
        market=MarketConditions(
            is_high_vol=False,
            bid_p=Decimal("94.9"),
            ask_p=Decimal("95.1"),
            market_spread_pct=Decimal("0.002"),
            best_bid_size=Decimal("1"),
            best_ask_size=Decimal("1"),
            connector_ready=True,
            order_book_stale=False,
            market_spread_too_small=False,
            side_spread_floor=Decimal("0.001"),
        ),
        target_net_base_pct=Decimal(state["target_net_base_pct"]),
        base_pct_net=Decimal("0"),
    )

    assert metrics["state"] == "bot7_strategy_gate"
    assert metrics["reason"] == "mean_reversion_long"
    assert ctrl._alpha_cross_allowed is False


def test_bot7_trade_flow_stale_becomes_bot_specific_risk_reason(monkeypatch) -> None:
    ctrl = _make_bot7_controller(trades=[])
    ctrl._bot7_state = ctrl._empty_bot7_state()
    ctrl._bot7_state["reason"] = "trade_flow_stale"
    ctrl._bot7_state["trade_flow_stale"] = True

    def _fake_super(self, spread_state, base_pct_gross, equity_quote, projected_total_quote, market):
        return (["shared_reason"], False, Decimal("0"), Decimal("0"))

    monkeypatch.setattr(StrategyRuntimeV24Controller, "_evaluate_all_risk", _fake_super)

    reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = EppV24Bot7Controller._evaluate_all_risk(
        ctrl,
        spread_state=SpreadEdgeState(
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
        ),
        base_pct_gross=Decimal("0"),
        equity_quote=Decimal("1000"),
        projected_total_quote=Decimal("0"),
        market=MarketConditions(
            is_high_vol=False,
            bid_p=Decimal("94.9"),
            ask_p=Decimal("95.1"),
            market_spread_pct=Decimal("0.002"),
            best_bid_size=Decimal("1"),
            best_ask_size=Decimal("1"),
            connector_ready=True,
            order_book_stale=False,
            market_spread_too_small=False,
            side_spread_floor=Decimal("0.001"),
        ),
    )

    assert "shared_reason" in reasons
    assert "bot7_trade_flow_stale" not in reasons
    assert risk_hard_stop is False
    assert daily_loss_pct == Decimal("0")
    assert drawdown_pct == Decimal("0")


def test_bot7_activates_probe_short_signal_on_upper_band_depth_reversal() -> None:
    trades = [
        _make_trade(1, price="105.02", size="0.7", delta="0.2", ts_ms=999_200),
        _make_trade(2, price="105.00", size="0.8", delta="0.1", ts_ms=999_300),
        _make_trade(3, price="104.99", size="0.7", delta="-0.2", ts_ms=999_400),
        _make_trade(4, price="104.98", size="0.7", delta="-0.2", ts_ms=999_500),
        _make_trade(5, price="104.97", size="0.6", delta="-0.1", ts_ms=999_650),
        _make_trade(6, price="104.96", size="0.6", delta="-0.1", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(
        price_buffer=_FakePriceBuffer(
            lower=Decimal("95"),
            basis=Decimal("100"),
            upper=Decimal("105"),
            rsi=Decimal("64"),
            adx=Decimal("24"),
            atr=Decimal("2"),
        ),
        trades=trades,
    )
    ctrl._trade_reader = _FakeTradeReader(trades, imbalance=Decimal("-0.18"))

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("104.96"), regime_name="neutral_low_vol")

    assert state["active"] is True
    assert state["probe_mode"] is True
    assert state["side"] == "sell"
    assert state["reason"] == "probe_short"
    assert state["grid_levels"] == 1
    assert state["target_net_base_pct"] == Decimal("-0.0015")


def test_bot7_activates_full_short_signal_on_upper_band_absorption() -> None:
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

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("105.04"), regime_name="neutral_low_vol")

    assert state["active"] is True
    assert state["probe_mode"] is False
    assert state["side"] == "sell"
    assert state["reason"] == "mean_reversion_short"
    assert state["target_net_base_pct"] < Decimal("0")


def test_bot7_compute_levels_reuses_state_for_funding_scale_and_quote_reason() -> None:
    trades = [
        _make_trade(1, price="94.98", size="0.4", delta="-0.4", ts_ms=999_200),
        _make_trade(2, price="94.97", size="0.4", delta="-0.4", ts_ms=999_300),
        _make_trade(3, price="94.96", size="0.5", delta="-0.5", ts_ms=999_400),
        _make_trade(4, price="94.95", size="0.5", delta="0.6", ts_ms=999_500),
        _make_trade(5, price="94.94", size="0.6", delta="0.6", ts_ms=999_600),
        _make_trade(6, price="94.93", size="6.0", delta="6.0", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(trades=trades)
    ctrl._funding_rate = Decimal("0.0012")
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
        bid_p=Decimal("94.9"),
        ask_p=Decimal("95.1"),
        market_spread_pct=Decimal("0.002"),
        best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"),
        connector_ready=True,
        order_book_stale=False,
        market_spread_too_small=False,
        side_spread_floor=Decimal("0.001"),
    )

    state = EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("94.94"), regime_name="neutral_low_vol")
    assert state["funding_risk_scale"] == Decimal("0.50")

    metrics = EppV24Bot7Controller._compute_alpha_policy(
        ctrl,
        regime_name="neutral_low_vol",
        spread_state=spread_state,
        market=market,
        target_net_base_pct=Decimal(state["target_net_base_pct"]),
        base_pct_net=Decimal("0"),
    )
    buy_spreads, sell_spreads, _, size_mult = EppV24Bot7Controller._compute_levels_and_sizing(
        ctrl,
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
        spread_state=spread_state,
        equity_quote=Decimal("1000"),
        mid=Decimal("94.94"),
        market=market,
    )

    assert metrics["reason"] == "mean_reversion_long"
    assert buy_spreads
    assert sell_spreads == []
    assert size_mult == Decimal("0.50")
    assert ctrl._bot7_state["funding_risk_scale"] == Decimal("0.50")
    assert ctrl._quote_side_mode == "buy_only"
    assert ctrl._quote_side_reason == "bot7_mean_reversion_long"


def test_bot7_extend_processed_data_before_log_populates_bot7_fields() -> None:
    trades = [
        _make_trade(1, price="94.98", size="0.4", delta="-0.4", ts_ms=999_200),
        _make_trade(2, price="94.97", size="0.4", delta="-0.4", ts_ms=999_300),
        _make_trade(3, price="94.96", size="0.5", delta="-0.5", ts_ms=999_400),
        _make_trade(4, price="94.95", size="0.5", delta="0.6", ts_ms=999_500),
        _make_trade(5, price="94.94", size="0.6", delta="0.6", ts_ms=999_600),
        _make_trade(6, price="94.93", size="6.0", delta="6.0", ts_ms=999_900),
    ]
    ctrl = _make_bot7_controller(trades=trades)
    EppV24Bot7Controller._update_bot7_state(ctrl, mid=Decimal("94.94"), regime_name="neutral_low_vol")
    processed_data = {}

    EppV24Bot7Controller._extend_processed_data_before_log(
        ctrl,
        processed_data=processed_data,
        snapshot={},
        state="running",
        regime_name="neutral_low_vol",
        market=SimpleNamespace(),
        projected_total_quote=Decimal("0"),
    )

    assert processed_data["bot7_gate_state"] == "active"
    assert processed_data["bot7_gate_reason"] == "mean_reversion_long"
    assert processed_data["bot7_signal_reason"] == "mean_reversion_long"
    assert processed_data["bot7_signal_side"] == "buy"
    assert processed_data["bot7_grid_levels"] >= 1


def test_bot7_build_runtime_execution_plan_matches_legacy_levels() -> None:
    ctrl = _make_bot7_controller(trades=[])
    ctrl._bot7_state = {
        **ctrl._empty_bot7_state(),
        "active": True,
        "side": "buy",
        "reason": "mean_reversion_long",
        "grid_levels": 2,
        "funding_risk_scale": Decimal("1"),
        "grid_spacing_pct": Decimal("0.0020"),
    }
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
        bid_p=Decimal("99.9"),
        ask_p=Decimal("100.1"),
        market_spread_pct=Decimal("0.002"),
        best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"),
        connector_ready=True,
        order_book_stale=False,
        market_spread_too_small=False,
        side_spread_floor=Decimal("0.001"),
    )

    legacy = EppV24Bot7Controller._compute_levels_and_sizing(
        ctrl,
        regime_name="neutral_low_vol",
        regime_spec=_make_regime_spec(),
        spread_state=spread_state,
        equity_quote=Decimal("1000"),
        mid=Decimal("100"),
        market=market,
    )
    plan = EppV24Bot7Controller.build_runtime_execution_plan(
        ctrl,
        RuntimeDataContext(
            now_ts=1_000.0,
            mid=Decimal("100"),
            regime_name="neutral_low_vol",
            regime_spec=_make_regime_spec(),
            spread_state=spread_state,
            market=market,
            equity_quote=Decimal("1000"),
            target_base_pct=Decimal("0"),
            target_net_base_pct=Decimal("0"),
            base_pct_gross=Decimal("0"),
            base_pct_net=Decimal("0"),
        ),
    )

    assert legacy == (plan.buy_spreads, plan.sell_spreads, plan.projected_total_quote, plan.size_mult)
    assert plan.family == "directional"
    assert plan.metadata["strategy_lane"] == "bot7"
