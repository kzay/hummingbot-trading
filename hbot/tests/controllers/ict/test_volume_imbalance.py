"""Tests for VolumeImbalanceDetector."""
from __future__ import annotations

from decimal import Decimal

from controllers.common.ict.volume_imbalance import VolumeImbalanceDetector

_D = Decimal


class TestVIDetection:
    def test_bullish_vi_detected(self):
        """Gap up in bodies: prev close < current open."""
        d = VolumeImbalanceDetector(decay_bars=50)
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))  # close=100
        event = d.add_bar(_D("102"), _D("104"), _D("101"), _D("103"))  # open=102 > close=100
        assert event is not None
        assert event.direction == +1
        assert event.bottom == _D("100")
        assert event.top == _D("102")

    def test_bearish_vi_detected(self):
        """Gap down in bodies: prev close > current open."""
        d = VolumeImbalanceDetector(decay_bars=50)
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))  # close=100
        event = d.add_bar(_D("98"), _D("99"), _D("96"), _D("97"))  # open=98 < close=100
        assert event is not None
        assert event.direction == -1
        assert event.top == _D("100")
        assert event.bottom == _D("98")

    def test_no_vi_when_no_gap(self):
        d = VolumeImbalanceDetector()
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        event = d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        assert event is None

    def test_no_event_on_first_bar(self):
        d = VolumeImbalanceDetector()
        event = d.add_bar(_D("100"), _D("105"), _D("95"), _D("102"))
        assert event is None


class TestVIMitigation:
    def test_bullish_vi_mitigated(self):
        d = VolumeImbalanceDetector(decay_bars=50)
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        d.add_bar(_D("102"), _D("104"), _D("101"), _D("103"))
        # Price drops below VI bottom (100)
        d.add_bar(_D("101"), _D("101"), _D("99"), _D("99"))
        mitigated = [e for e in d.all_events if e.mitigated]
        assert len(mitigated) >= 1


class TestVIReset:
    def test_reset_clears_state(self):
        d = VolumeImbalanceDetector()
        d.add_bar(_D("100"), _D("101"), _D("99"), _D("100"))
        d.add_bar(_D("102"), _D("104"), _D("101"), _D("103"))
        d.reset()
        assert d.bar_count == 0
        assert len(d.active) == 0
