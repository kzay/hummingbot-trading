from decimal import Decimal

from controllers.core import RegimeSpec
from controllers.epp_v2_4 import EppV24Controller
from controllers.spread_engine import SpreadEngine

NEUTRAL = EppV24Controller.PHASE0_SPECS["neutral_low_vol"]
SHOCK = EppV24Controller.PHASE0_SPECS["high_vol_shock"]


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
