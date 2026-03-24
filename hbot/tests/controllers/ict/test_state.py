"""Integration tests for ICTState facade."""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict.state import ICTConfig, ICTState

_D = Decimal


def _trending_series(
    n: int = 60, start: str = "100"
) -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Uptrend then downtrend: n/2 bars up, n/2 bars down."""
    candles = []
    base = _D(start)
    half = n // 2
    for i in range(half):
        o = base + _D(i)
        c = o + _D("1")
        h = c + _D("0.5")
        l = o - _D("0.25")
        candles.append((o, h, l, c, _D("100")))
    peak = base + _D(half)
    for i in range(half):
        o = peak - _D(i)
        c = o - _D("1")
        h = o + _D("0.25")
        l = c - _D("0.5")
        candles.append((o, h, l, c, _D("100")))
    return candles


class TestICTStateSmoke:
    def test_add_bar_does_not_crash(self):
        state = ICTState()
        for o, h, l, c, v in _trending_series():
            state.add_bar(o, h, l, c, v)
        assert state.bar_count == 60

    def test_default_config(self):
        state = ICTState()
        assert state.bar_count == 0

    def test_custom_config(self):
        cfg = ICTConfig(swing_length=5, fvg_decay_bars=5)
        state = ICTState(config=cfg)
        assert state.bar_count == 0


class TestICTStateWarmup:
    def test_warmup_replays_bars(self):
        state = ICTState(config=ICTConfig(swing_length=2))
        series = [(o, h, l, c) for o, h, l, c, _ in _trending_series(40)]
        state.warmup(series)
        assert state.bar_count == 40

    def test_warmup_equivalent_to_add_bar(self):
        cfg = ICTConfig(swing_length=2)
        s1 = ICTState(config=cfg)
        s2 = ICTState(config=cfg)

        series = _trending_series(40)

        for o, h, l, c, v in series:
            s1.add_bar(o, h, l, c, v)

        s2.warmup([(o, h, l, c) for o, h, l, c, _ in series])

        assert s1.bar_count == s2.bar_count
        assert s1.swings == s2.swings
        assert s1.trend == s2.trend


class TestICTStateReset:
    def test_reset_clears_all_detectors(self):
        state = ICTState(config=ICTConfig(swing_length=2))
        for o, h, l, c, v in _trending_series():
            state.add_bar(o, h, l, c, v)
        assert state.bar_count > 0

        state.reset()
        assert state.bar_count == 0
        assert len(state.swings) == 0
        assert state.trend == 0
        assert len(state.active_fvgs) == 0
        assert len(state.active_obs) == 0
        assert len(state.active_liquidity) == 0
        assert len(state.displacement_events) == 0
        assert len(state.active_vis) == 0
        assert len(state.active_breakers) == 0

    def test_reset_replay_parity(self):
        """Reset + replay must produce identical results."""
        cfg = ICTConfig(swing_length=2)
        state = ICTState(config=cfg)
        series = _trending_series(40)

        for o, h, l, c, v in series:
            state.add_bar(o, h, l, c, v)
        first_swings = state.swings
        first_trend = state.trend

        state.reset()
        for o, h, l, c, v in series:
            state.add_bar(o, h, l, c, v)
        second_swings = state.swings
        second_trend = state.trend

        assert first_swings == second_swings
        assert first_trend == second_trend


class TestICTStateAccessors:
    def test_zone_for_price(self):
        state = ICTState(config=ICTConfig(swing_length=2))
        for o, h, l, c, v in _trending_series():
            state.add_bar(o, h, l, c, v)
        zone = state.zone_for_price(_D("120"))
        assert zone in ("premium", "discount", "equilibrium")

    def test_fib_levels_populated_after_swings(self):
        state = ICTState(config=ICTConfig(swing_length=2))
        for o, h, l, c, v in _trending_series():
            state.add_bar(o, h, l, c, v)
        # After enough bars with swings, fib levels should exist
        if state.equilibrium > _D("0"):
            assert len(state.fib_levels) > 0
