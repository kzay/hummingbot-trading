"""Tests for DisplacementDetector."""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict.displacement import DisplacementDetector

_D = Decimal


class TestDisplacementDetection:
    def test_large_body_detected(self):
        d = DisplacementDetector(atr_period=3, atr_mult=_D("1.5"))
        # Warm up ATR with small bars
        for _ in range(5):
            d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))

        # Large bullish displacement
        event = d.add_bar(_D("100"), _D("115"), _D("99"), _D("114"))
        assert event is not None
        assert event.direction == +1
        assert event.body_atr_ratio >= _D("1.5")

    def test_small_body_not_detected(self):
        d = DisplacementDetector(atr_period=3, atr_mult=_D("2.0"))
        for _ in range(5):
            d.add_bar(_D("100"), _D("102"), _D("98"), _D("101"))
        event = d.add_bar(_D("100"), _D("101"), _D("99"), _D("100.5"))
        assert event is None

    def test_bearish_displacement(self):
        d = DisplacementDetector(atr_period=3, atr_mult=_D("1.5"))
        for _ in range(5):
            d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        event = d.add_bar(_D("114"), _D("115"), _D("99"), _D("100"))
        assert event is not None
        assert event.direction == -1

    def test_no_event_during_warmup(self):
        d = DisplacementDetector(atr_period=3)
        event = d.add_bar(_D("100"), _D("200"), _D("50"), _D("150"))
        assert event is None


class TestDisplacementReset:
    def test_reset_clears_state(self):
        d = DisplacementDetector(atr_period=3, atr_mult=_D("1.5"))
        for _ in range(5):
            d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        d.add_bar(_D("100"), _D("115"), _D("99"), _D("114"))
        assert len(d.events) > 0

        d.reset()
        assert d.bar_count == 0
        assert len(d.events) == 0
