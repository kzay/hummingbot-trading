"""Tests for FVGDetector."""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict.fvg import FVGDetector
from tests.controllers.ict.conftest import (
    fvg_bearish_series,
    fvg_bullish_series,
    make_candle,
)

_D = Decimal


class TestFVGDetection:
    def test_bullish_fvg_detected(self):
        d = FVGDetector(decay_bars=50)
        for o, h, l, c, v in fvg_bullish_series():
            d.add_bar(o, h, l, c, v)

        events = d.all_events
        assert len(events) >= 1
        bullish = [e for e in events if e.direction == +1]
        assert len(bullish) >= 1
        fvg = bullish[0]
        assert fvg.bottom == _D("102")
        assert fvg.top == _D("103")
        assert fvg.size_bps > _D("0")
        assert fvg.mitigated is False

    def test_bearish_fvg_detected(self):
        d = FVGDetector(decay_bars=50)
        for o, h, l, c, v in fvg_bearish_series():
            d.add_bar(o, h, l, c, v)

        events = d.all_events
        bearish = [e for e in events if e.direction == -1]
        assert len(bearish) >= 1
        fvg = bearish[0]
        assert fvg.top == _D("98")
        assert fvg.bottom == _D("97")

    def test_no_fvg_in_first_two_bars(self):
        d = FVGDetector()
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        assert len(d.all_events) == 0

    def test_no_fvg_when_no_gap(self):
        d = FVGDetector()
        for _ in range(10):
            d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        assert len(d.all_events) == 0


class TestFVGMitigation:
    def test_bullish_fvg_mitigated(self):
        d = FVGDetector(decay_bars=50)
        for o, h, l, c, v in fvg_bullish_series():
            d.add_bar(o, h, l, c, v)

        assert len(d.active) >= 1

        # Price drops to 101 -> below FVG bottom (102) -> mitigated
        d.add_bar(_D("103"), _D("103"), _D("101"), _D("101"))
        mitigated = [e for e in d.all_events if e.mitigated]
        assert len(mitigated) >= 1

    def test_bearish_fvg_mitigated(self):
        d = FVGDetector(decay_bars=50)
        for o, h, l, c, v in fvg_bearish_series():
            d.add_bar(o, h, l, c, v)

        # Price rises to 99 -> above FVG top (98) -> mitigated
        d.add_bar(_D("96"), _D("99"), _D("95"), _D("98"))
        mitigated = [e for e in d.all_events if e.mitigated]
        assert len(mitigated) >= 1


class TestFVGDecayAndBounding:
    def test_fvg_decays_after_max_bars(self):
        d = FVGDetector(decay_bars=3)
        for o, h, l, c, v in fvg_bullish_series():
            d.add_bar(o, h, l, c, v)
        assert len(d.active) >= 1

        for _ in range(5):
            d.add_bar(_D("105"), _D("106"), _D("104"), _D("105"))
        assert len(d.active) == 0

    def test_max_active_bounded(self):
        d = FVGDetector(decay_bars=100, max_active=2)
        # Create multiple FVGs
        base = _D("100")
        for i in range(10):
            offset = _D(i) * _D("10")
            candles = [
                make_candle(
                    str(base + offset),
                    str(base + offset + 2),
                    str(base + offset - 1),
                    str(base + offset + 1),
                ),
                make_candle(
                    str(base + offset + 1),
                    str(base + offset + 4),
                    str(base + offset),
                    str(base + offset + 3),
                ),
                make_candle(
                    str(base + offset + 5),
                    str(base + offset + 8),
                    str(base + offset + 5),
                    str(base + offset + 7),
                ),
            ]
            for o, h, l, c, v in candles:
                d.add_bar(o, h, l, c, v)
        assert len(d.active) <= 2

    def test_bullish_bias(self):
        d = FVGDetector(decay_bars=50)
        for o, h, l, c, v in fvg_bullish_series():
            d.add_bar(o, h, l, c, v)
        assert d.bullish_bias > 0


class TestFVGReset:
    def test_reset_clears_state(self):
        d = FVGDetector()
        for o, h, l, c, v in fvg_bullish_series():
            d.add_bar(o, h, l, c, v)
        assert d.bar_count > 0
        d.reset()
        assert d.bar_count == 0
        assert len(d.active) == 0
        assert len(d.all_events) == 0

    def test_reset_replay_parity(self):
        d = FVGDetector(decay_bars=50)
        series = fvg_bullish_series()
        for o, h, l, c, v in series:
            d.add_bar(o, h, l, c, v)
        first_run = d.all_events

        d.reset()
        for o, h, l, c, v in series:
            d.add_bar(o, h, l, c, v)
        second_run = d.all_events

        assert first_run == second_run
