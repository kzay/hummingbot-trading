"""Tests for SwingDetector."""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.common.ict.swing import SwingDetector
from tests.controllers.ict.conftest import (
    make_candle,
    make_uptrend,
    swing_series,
)

_D = Decimal


class TestSwingDetectorBasics:
    def test_no_swings_before_warmup(self):
        d = SwingDetector(length=3)
        for o, h, l, c, v in make_uptrend(5):
            d.add_bar(o, h, l, c, v)
        assert d.bar_count == 5
        assert len(d.swings) == 0

    def test_bar_count_increments(self):
        d = SwingDetector(length=2)
        assert d.bar_count == 0
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        assert d.bar_count == 1

    def test_reset_clears_state(self):
        d = SwingDetector(length=2)
        for o, h, l, c, v in swing_series()[:20]:
            d.add_bar(o, h, l, c, v)
        assert d.bar_count > 0
        d.reset()
        assert d.bar_count == 0
        assert len(d.swings) == 0
        assert d.last_swing is None


class TestSwingDetectorDetection:
    def test_detects_swing_high(self):
        """A bar with the highest high in a 2*length+1 window = swing high."""
        d = SwingDetector(length=2)
        # Build: 3 ascending, 1 peak, 3 descending
        candles = [
            make_candle("100", "101", "99", "100"),
            make_candle("101", "103", "100", "102"),
            make_candle("102", "110", "101", "109"),  # peak
            make_candle("109", "108", "106", "107"),
            make_candle("107", "106", "104", "105"),
        ]
        results = []
        for o, h, l, c, v in candles:
            r = d.add_bar(o, h, l, c, v)
            if r is not None:
                results.append(r)

        high_events = [e for e in results if e.direction == +1]
        assert len(high_events) >= 1
        assert high_events[0].level == _D("110")

    def test_detects_swing_low(self):
        """A bar with the lowest low in a 2*length+1 window = swing low."""
        d = SwingDetector(length=2)
        candles = [
            make_candle("110", "111", "109", "110"),
            make_candle("109", "108", "107", "108"),
            make_candle("108", "107", "90", "91"),  # trough
            make_candle("91", "94", "92", "93"),
            make_candle("93", "96", "94", "95"),
        ]
        results = []
        for o, h, l, c, v in candles:
            r = d.add_bar(o, h, l, c, v)
            if r is not None:
                results.append(r)

        low_events = [e for e in results if e.direction == -1]
        assert len(low_events) >= 1
        assert low_events[0].level == _D("90")


class TestSwingAlternation:
    def test_alternation_enforced(self):
        """Two consecutive swing highs -> only the higher one kept."""
        d = SwingDetector(length=2)
        series = swing_series()
        for o, h, l, c, v in series:
            d.add_bar(o, h, l, c, v)

        swings = d.swings
        for i in range(1, len(swings)):
            assert swings[i].direction != swings[i - 1].direction, (
                f"Alternation violated at index {i}: "
                f"{swings[i-1].direction} -> {swings[i].direction}"
            )

    def test_reset_replay_parity(self):
        """After reset + replay, swings must be identical."""
        d = SwingDetector(length=2)
        series = swing_series()
        for o, h, l, c, v in series:
            d.add_bar(o, h, l, c, v)
        first_run = d.swings

        d.reset()
        for o, h, l, c, v in series:
            d.add_bar(o, h, l, c, v)
        second_run = d.swings

        assert first_run == second_run


class TestSwingEdgeCases:
    def test_length_1(self):
        d = SwingDetector(length=1)
        candles = [
            make_candle("100", "105", "99", "103"),
            make_candle("103", "110", "102", "108"),
            make_candle("108", "107", "100", "101"),
        ]
        for o, h, l, c, v in candles:
            d.add_bar(o, h, l, c, v)
        assert d.bar_count == 3

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError):
            SwingDetector(length=0)

    def test_flat_market_no_swings(self):
        """Identical bars should not produce swings."""
        d = SwingDetector(length=2)
        for _ in range(20):
            d.add_bar(_D("100"), _D("100"), _D("100"), _D("100"))
        assert len(d.swings) == 0
