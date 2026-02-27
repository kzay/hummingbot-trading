"""Tests for MidPriceBuffer: EMA, ATR/band_pct, adverse_drift, bar construction."""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.price_buffer import MidPriceBuffer

_D = Decimal


def _fill_buffer(buf: MidPriceBuffer, prices: list, start_ts: float = 1000.0, interval_s: float = 60.0):
    """Feed one price per minute into the buffer."""
    for i, p in enumerate(prices):
        buf.add_sample(start_ts + i * interval_s, _D(str(p)))


class TestBarConstruction:
    def test_single_sample_creates_one_bar(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        assert len(buf.bars) == 1
        assert buf.bars[0].close == _D("100")

    def test_same_minute_updates_high_low_close(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1005.0, _D("105"))
        buf.add_sample(1010.0, _D("95"))
        assert len(buf.bars) == 1
        bar = buf.bars[0]
        assert bar.high == _D("105")
        assert bar.low == _D("95")
        assert bar.close == _D("95")

    def test_new_minute_creates_new_bar(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1060.0, _D("101"))
        assert len(buf.bars) == 2

    def test_gap_fills_missing_minutes(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1180.0, _D("102"))  # 3 minutes later
        assert len(buf.bars) >= 3

    def test_zero_price_ignored(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("0"))
        assert len(buf.bars) == 0

    def test_negative_price_ignored(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("-5"))
        assert len(buf.bars) == 0


class TestEma:
    def test_ema_none_when_insufficient_bars(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.ema(10) is None

    def test_ema_converges_to_constant_price(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100.0] * 60)
        ema = buf.ema(20)
        assert ema is not None
        assert abs(ema - _D("100")) < _D("0.01")

    def test_ema_tracks_rising_prices(self):
        prices = [100 + i * 0.5 for i in range(60)]
        buf = MidPriceBuffer()
        _fill_buffer(buf, prices)
        ema = buf.ema(20)
        assert ema is not None
        assert ema > _D("100")
        assert ema < _D(str(prices[-1]))

    def test_ema_invalid_period_returns_none(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100] * 10)
        assert buf.ema(0) is None
        assert buf.ema(-1) is None

    def test_ema_incremental_matches_full_recompute(self):
        buf = MidPriceBuffer()
        prices = [100 + (i % 10) * 0.3 for i in range(80)]
        _fill_buffer(buf, prices)
        ema_first = buf.ema(20)
        buf._ema_values.clear()
        ema_recomputed = buf.ema(20)
        assert ema_first is not None
        assert ema_recomputed is not None
        assert abs(ema_first - ema_recomputed) < _D("0.001")


class TestAtrAndBandPct:
    def test_atr_none_when_insufficient_bars(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.atr(14) is None

    def test_atr_zero_for_constant_price(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100.0] * 20)
        atr = buf.atr(5)
        assert atr is not None
        assert atr == _D("0")

    def test_atr_positive_for_varying_prices(self):
        prices = [100 + (i % 3) * 2 for i in range(20)]
        buf = MidPriceBuffer()
        _fill_buffer(buf, prices)
        atr = buf.atr(5)
        assert atr is not None
        assert atr > _D("0")

    def test_band_pct_none_when_atr_unavailable(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.band_pct(14) is None

    def test_band_pct_zero_for_constant_price(self):
        buf = MidPriceBuffer()
        _fill_buffer(buf, [100.0] * 20)
        bp = buf.band_pct(5)
        assert bp is not None
        assert bp == _D("0")

    def test_band_pct_positive_for_varying_prices(self):
        prices = [100, 102, 98, 103, 97, 101, 99, 104, 96, 100,
                  102, 98, 103, 97, 101, 99, 104, 96, 100, 102]
        buf = MidPriceBuffer()
        _fill_buffer(buf, prices)
        bp = buf.band_pct(5)
        assert bp is not None
        assert bp > _D("0")


class TestAdverseDrift:
    def test_drift_zero_with_empty_buffer(self):
        buf = MidPriceBuffer()
        assert buf.adverse_drift_30s(1000.0) == _D("0")

    def test_drift_zero_with_single_sample(self):
        buf = MidPriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        assert buf.adverse_drift_30s(1000.0) == _D("0")

    def test_drift_zero_for_constant_price(self):
        buf = MidPriceBuffer()
        for i in range(10):
            buf.add_sample(970.0 + i * 5, _D("100"))
        drift = buf.adverse_drift_30s(1015.0)
        assert drift == _D("0")

    def test_drift_positive_for_price_change(self):
        buf = MidPriceBuffer()
        buf.add_sample(960.0, _D("100"))
        buf.add_sample(970.0, _D("100"))
        buf.add_sample(980.0, _D("100"))
        buf.add_sample(995.0, _D("105"))
        drift = buf.adverse_drift_30s(995.0)
        assert drift > _D("0")

    def test_drift_monotonic_increase_detected(self):
        buf = MidPriceBuffer()
        for i in range(10):
            buf.add_sample(960.0 + i * 5, _D(str(100 + i)))
        drift = buf.adverse_drift_30s(1005.0)
        assert drift > _D("0")

    def test_smooth_drift_initializes_to_raw(self):
        buf = MidPriceBuffer()
        buf.add_sample(960.0, _D("100"))
        buf.add_sample(995.0, _D("105"))
        raw = buf.adverse_drift_30s(995.0)
        smooth = buf.adverse_drift_smooth(995.0, _D("0.25"))
        assert smooth == raw

    def test_smooth_drift_converges(self):
        buf = MidPriceBuffer()
        for i in range(20):
            buf.add_sample(960.0 + i * 5, _D("100"))
        for _ in range(10):
            buf.adverse_drift_smooth(1060.0, _D("0.25"))
        smooth = buf.adverse_drift_smooth(1060.0, _D("0.25"))
        assert smooth >= _D("0")
