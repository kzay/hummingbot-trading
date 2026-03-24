from decimal import Decimal

import pytest

from controllers.core import RegimeSpec, RuntimeLevelState
from controllers.spread_engine import SpreadEngine

NEUTRAL = RegimeSpec(
    spread_min=Decimal("0.0010"),
    spread_max=Decimal("0.0040"),
    levels_min=1,
    levels_max=3,
    refresh_s=30,
    target_base_pct=Decimal("0.50"),
    quote_size_pct_min=Decimal("0.01"),
    quote_size_pct_max=Decimal("0.02"),
    one_sided="off",
    fill_factor=Decimal("0.40"),
)


def _engine(**overrides) -> SpreadEngine:
    defaults = dict(
        turnover_cap_x=Decimal("3.0"),
        spread_step_multiplier=Decimal("0.4"),
        vol_penalty_multiplier=Decimal("0.5"),
    )
    defaults.update(overrides)
    return SpreadEngine(**defaults)


def test_spread_at_zero_turnover_equals_min():
    eng = _engine()
    spread = eng.pick_spread_pct(NEUTRAL, Decimal("0"))
    assert spread == NEUTRAL.spread_min


def test_spread_at_cap_turnover_equals_max():
    eng = _engine()
    spread = eng.pick_spread_pct(NEUTRAL, Decimal("3.0"))
    assert spread == NEUTRAL.spread_max


def test_spread_interpolates_between_min_max():
    eng = _engine()
    spread = eng.pick_spread_pct(NEUTRAL, Decimal("1.5"))
    assert NEUTRAL.spread_min < spread < NEUTRAL.spread_max


def test_levels_decrease_with_turnover():
    eng = _engine()
    levels_low = eng.pick_levels(NEUTRAL, Decimal("0"))
    levels_high = eng.pick_levels(NEUTRAL, Decimal("3.0"))
    assert levels_low >= levels_high


def test_build_side_spreads_buy_only():
    eng = _engine()
    buy, sell = eng.build_side_spreads(
        Decimal("0.004"), Decimal("0"), 3, "buy_only", Decimal("0.0001")
    )
    assert len(buy) == 3
    assert len(sell) == 0


def test_build_side_spreads_respects_min_floor():
    eng = _engine()
    buy, sell = eng.build_side_spreads(
        Decimal("0.0001"), Decimal("0"), 2, "off", Decimal("0.005")
    )
    for s in buy + sell:
        assert s >= Decimal("0.005")


def test_spread_floor_increases_with_fees():
    eng = _engine()
    floor_low = eng.compute_spread_floor(
        maker_fee_pct=Decimal("0.0005"),
        slippage_est_pct=Decimal("0.0005"),
        adverse_drift=Decimal("0"),
        turnover_penalty=Decimal("0"),
        min_edge_threshold=Decimal("0.0002"),
        fill_factor=Decimal("0.4"),
        vol_band_pct=Decimal("0"),
    )
    floor_high = eng.compute_spread_floor(
        maker_fee_pct=Decimal("0.002"),
        slippage_est_pct=Decimal("0.001"),
        adverse_drift=Decimal("0"),
        turnover_penalty=Decimal("0"),
        min_edge_threshold=Decimal("0.0002"),
        fill_factor=Decimal("0.4"),
        vol_band_pct=Decimal("0"),
    )
    assert floor_high > floor_low


def test_skew_shifts_buy_sell_asymmetrically():
    eng = _engine()
    buy, sell = eng.build_side_spreads(
        Decimal("0.004"), Decimal("0.001"), 2, "off", Decimal("0.0001")
    )
    assert buy[0] < sell[0]


def test_compute_spread_and_edge_exposes_quote_geometry_components():
    eng = _engine()
    state, floor = eng.compute_spread_and_edge(
        regime_name="neutral_low_vol",
        regime_spec=NEUTRAL,
        band_pct=Decimal("0.002"),
        raw_drift=Decimal("0.0001"),
        smooth_drift=Decimal("0.00005"),
        target_base_pct=Decimal("0.50"),
        base_pct=Decimal("0.35"),
        equity_quote=Decimal("1000"),
        traded_notional_today=Decimal("100"),
        ob_imbalance=Decimal("0.40"),
        ob_imbalance_skew_weight=Decimal("0.30"),
        maker_fee_pct=Decimal("0.001"),
        is_perp=False,
        funding_rate=Decimal("0"),
        adverse_fill_count=0,
        fill_edge_ewma=None,
    )
    assert state.quote_geometry.spread_floor_pct == floor
    assert state.quote_geometry.base_spread_pct > 0
    assert state.quote_geometry.inventory_urgency > 0
    assert state.quote_geometry.reservation_price_adjustment_pct == state.skew


def test_apply_runtime_spreads_and_sizing_enforces_min_base_per_level():
    eng = _engine()
    runtime = RuntimeLevelState(
        buy_spreads=[],
        sell_spreads=[],
        buy_amounts_pct=[],
        sell_amounts_pct=[],
        total_amount_quote=Decimal("0"),
        executor_refresh_time=30,
        cooldown_time=5,
    )
    eng.apply_runtime_spreads_and_sizing(
        runtime_levels=runtime,
        buy_spreads=[Decimal("0.0010")],
        sell_spreads=[Decimal("0.0010")],
        equity_quote=Decimal("1000"),
        mid=Decimal("67000"),
        quote_size_pct=Decimal("0.001"),
        size_mult=Decimal("1"),
        kelly_order_quote=Decimal("0"),
        min_notional_quote=Decimal("5"),
        min_base_amount=Decimal("0.001"),
        max_order_notional_quote=Decimal("250"),
        max_total_notional_quote=Decimal("1000"),
        cooldown_time=8,
        no_trade=False,
        variant="a",
        enabled=True,
    )
    assert runtime.total_amount_quote == Decimal("134")


# ------------------------------------------------------------------
# Parametrized boundary tests
# ------------------------------------------------------------------

@pytest.mark.parametrize("turnover_x,expect_min", [
    (Decimal("0"), True),
    (Decimal("0.001"), False),
    (Decimal("1.5"), False),
    (Decimal("3.0"), False),
])
def test_spread_at_turnover_boundaries(turnover_x, expect_min):
    eng = _engine()
    spread = eng.pick_spread_pct(NEUTRAL, turnover_x)
    if expect_min:
        assert spread == NEUTRAL.spread_min
    else:
        assert spread >= NEUTRAL.spread_min
        assert spread <= NEUTRAL.spread_max


@pytest.mark.parametrize("one_sided,expect_buy,expect_sell", [
    ("off", 2, 2),
    ("buy_only", 2, 0),
    ("sell_only", 0, 2),
])
def test_build_side_spreads_one_sided_modes(one_sided, expect_buy, expect_sell):
    eng = _engine()
    buy, sell = eng.build_side_spreads(
        Decimal("0.004"), Decimal("0"), 2, one_sided, Decimal("0.0001"),
    )
    assert len(buy) == expect_buy
    assert len(sell) == expect_sell


@pytest.mark.parametrize("base_spread,min_floor", [
    (Decimal("0.0001"), Decimal("0.005")),
    (Decimal("0.005"), Decimal("0.005")),
    (Decimal("0.010"), Decimal("0.005")),
])
def test_build_side_spreads_floor_boundary(base_spread, min_floor):
    eng = _engine()
    buy, sell = eng.build_side_spreads(base_spread, Decimal("0"), 2, "off", min_floor)
    for s in buy + sell:
        assert s >= min_floor


@pytest.mark.parametrize("skew", [
    Decimal("0.001"),
    Decimal("-0.001"),
    Decimal("0"),
])
def test_skew_direction(skew):
    eng = _engine()
    buy, sell = eng.build_side_spreads(Decimal("0.004"), skew, 2, "off", Decimal("0.0001"))
    if skew > 0:
        assert buy[0] < sell[0]
    elif skew < 0:
        assert buy[0] > sell[0]
    else:
        assert buy[0] == sell[0]
