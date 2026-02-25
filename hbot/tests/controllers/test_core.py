"""Tests for controllers.core — shared primitives."""
from decimal import Decimal

from controllers.core import (
    MarketConditions,
    RegimeSpec,
    RuntimeLevelState,
    SpreadEdgeState,
    clip,
)


def test_clip_within_range():
    assert clip(Decimal("5"), Decimal("0"), Decimal("10")) == Decimal("5")


def test_clip_below_low():
    assert clip(Decimal("-1"), Decimal("0"), Decimal("10")) == Decimal("0")


def test_clip_above_high():
    assert clip(Decimal("15"), Decimal("0"), Decimal("10")) == Decimal("10")


def test_clip_at_boundary():
    assert clip(Decimal("0"), Decimal("0"), Decimal("10")) == Decimal("0")
    assert clip(Decimal("10"), Decimal("0"), Decimal("10")) == Decimal("10")


def test_regime_spec_frozen():
    spec = RegimeSpec(
        spread_min=Decimal("0.001"), spread_max=Decimal("0.005"),
        levels_min=1, levels_max=3, refresh_s=60,
        target_base_pct=Decimal("0.5"),
        quote_size_pct_min=Decimal("0.001"), quote_size_pct_max=Decimal("0.002"),
        one_sided="off",
    )
    try:
        spec.spread_min = Decimal("0.999")
        assert False, "should be frozen"
    except AttributeError:
        pass


def test_runtime_level_state_mutable():
    rls = RuntimeLevelState(
        buy_spreads=[], sell_spreads=[], buy_amounts_pct=[], sell_amounts_pct=[],
        total_amount_quote=Decimal("0"), executor_refresh_time=60, cooldown_time=5,
    )
    rls.buy_spreads = [Decimal("0.01")]
    assert len(rls.buy_spreads) == 1


def test_spread_edge_state_fields():
    ses = SpreadEdgeState(
        band_pct=Decimal("0.005"), spread_pct=Decimal("0.003"),
        net_edge=Decimal("0.001"), skew=Decimal("0"),
        adverse_drift=Decimal("0"), smooth_drift=Decimal("0"),
        drift_spread_mult=Decimal("1"), turnover_x=Decimal("0"),
        min_edge_threshold=Decimal("0.0001"), edge_resume_threshold=Decimal("0.0004"),
        fill_factor=Decimal("0.4"),
    )
    assert ses.fill_factor == Decimal("0.4")


def test_market_conditions_fields():
    mc = MarketConditions(
        is_high_vol=False, bid_p=Decimal("100"), ask_p=Decimal("101"),
        market_spread_pct=Decimal("0.01"), best_bid_size=Decimal("1"),
        best_ask_size=Decimal("1"), connector_ready=True,
        order_book_stale=False, market_spread_too_small=False,
        side_spread_floor=Decimal("0.001"),
    )
    assert mc.connector_ready is True
