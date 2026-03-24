"""Tests for StructureDetector."""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict._types import SwingEvent
from controllers.common.ict.structure import StructureDetector

_D = Decimal


class TestStructureDetectorBasics:
    def test_no_events_on_first_swing(self):
        d = StructureDetector()
        event = d.on_swing(SwingEvent(index=0, direction=+1, level=_D("100")))
        assert event is None

    def test_trend_starts_undefined(self):
        d = StructureDetector()
        assert d.trend == 0

    def test_bar_count_tracks(self):
        d = StructureDetector()
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        assert d.bar_count == 1


class TestBOS:
    def test_bullish_bos_on_higher_high(self):
        d = StructureDetector()
        d.on_swing(SwingEvent(index=0, direction=+1, level=_D("100")))
        d.on_swing(SwingEvent(index=5, direction=-1, level=_D("95")))
        event = d.on_swing(SwingEvent(index=10, direction=+1, level=_D("105")))

        assert event is not None
        assert event.event_type == "bos"
        assert event.direction == +1
        assert d.trend == +1

    def test_bearish_bos_on_lower_low(self):
        d = StructureDetector()
        d.on_swing(SwingEvent(index=0, direction=-1, level=_D("100")))
        d.on_swing(SwingEvent(index=5, direction=+1, level=_D("105")))
        event = d.on_swing(SwingEvent(index=10, direction=-1, level=_D("95")))

        assert event is not None
        assert event.event_type == "bos"
        assert event.direction == -1
        assert d.trend == -1

    def test_no_bos_on_lower_high(self):
        d = StructureDetector()
        d.on_swing(SwingEvent(index=0, direction=+1, level=_D("100")))
        d.on_swing(SwingEvent(index=5, direction=-1, level=_D("95")))
        event = d.on_swing(SwingEvent(index=10, direction=+1, level=_D("98")))
        assert event is None


class TestCHoCH:
    def test_choch_on_trend_reversal(self):
        """Establish bullish trend, then detect CHoCH on lower low."""
        d = StructureDetector()
        d.on_swing(SwingEvent(index=0, direction=+1, level=_D("100")))
        d.on_swing(SwingEvent(index=5, direction=-1, level=_D("95")))
        d.on_swing(SwingEvent(index=10, direction=+1, level=_D("105")))
        assert d.trend == +1

        d.on_swing(SwingEvent(index=15, direction=-1, level=_D("96")))
        event = d.on_swing(SwingEvent(index=20, direction=-1, level=_D("93")))

        assert event is not None
        assert event.event_type == "choch"
        assert event.direction == -1
        assert d.trend == -1


class TestStructureReset:
    def test_reset_clears_state(self):
        d = StructureDetector()
        d.on_swing(SwingEvent(index=0, direction=+1, level=_D("100")))
        d.on_swing(SwingEvent(index=5, direction=-1, level=_D("95")))
        d.on_swing(SwingEvent(index=10, direction=+1, level=_D("105")))
        assert d.trend == +1

        d.reset()
        assert d.trend == 0
        assert len(d.events) == 0
        assert d.bar_count == 0
