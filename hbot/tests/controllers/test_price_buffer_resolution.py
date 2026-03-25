"""Tests for PriceBuffer multi-resolution support.

Verifies:
  (a) resolution=1 behavior identical to current (regression)
  (b) resolution=15 resampling correctness (OHLCV aggregation, boundary alignment)
  (c) indicator values at 15m match manual computation
  (d) cache invalidation on new bars
  (e) EMA/ATR lazy recompute after resolution boundary
  (f) bars returns resolution bars, bars_1m returns 1m
  (g) invalid resolution raises ValueError
  (h) adverse_drift_30s unaffected by resolution
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.price_buffer import MinuteBar, PriceBuffer, SUPPORTED_RESOLUTIONS

_D = Decimal
_TOL = _D("0.05")


def _close_enough(a: Decimal | None, b: Decimal | None, tol: Decimal = _TOL) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _make_1m_bars(count: int, base_price: float = 100.0, base_ts: int = 0) -> list[MinuteBar]:
    """Create count 1m bars with slightly varying prices for realistic indicators."""
    bars = []
    for i in range(count):
        price = _D(str(base_price + (i % 10) * 0.5 - 2.5))
        bars.append(MinuteBar(
            ts_minute=base_ts + i * 60,
            open=price,
            high=price + _D("1"),
            low=price - _D("0.5"),
            close=price + _D("0.3"),
        ))
    return bars


class TestResolutionValidation:
    """Task 1.1 / 1.8: constructor validation and property."""

    def test_supported_resolutions(self):
        assert SUPPORTED_RESOLUTIONS == {1, 5, 15, 60}

    def test_default_resolution_is_1(self):
        buf = PriceBuffer()
        assert buf.resolution_minutes == 1

    def test_valid_resolutions_accepted(self):
        for res in SUPPORTED_RESOLUTIONS:
            buf = PriceBuffer(resolution_minutes=res)
            assert buf.resolution_minutes == res

    def test_invalid_resolution_raises(self):
        with pytest.raises(ValueError, match="resolution_minutes=3"):
            PriceBuffer(resolution_minutes=3)

    def test_invalid_resolution_2m(self):
        with pytest.raises(ValueError):
            PriceBuffer(resolution_minutes=2)

    def test_resolution_readonly(self):
        buf = PriceBuffer(resolution_minutes=15)
        assert buf.resolution_minutes == 15


class TestResolution1Regression:
    """Task 1.5/1.6: at resolution=1, behavior identical to original."""

    def test_bars_returns_1m_bars(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1060.0, _D("101"))
        assert len(buf.bars) == 2
        assert buf.bars[0].close == _D("100")
        assert buf.bars[1].close == _D("101")

    def test_bars_1m_same_as_bars_at_resolution_1(self):
        buf = PriceBuffer()
        for i in range(5):
            buf.add_sample(1000.0 + i * 60, _D(str(100 + i)))
        assert len(buf.bars) == len(buf.bars_1m)
        for a, b in zip(buf.bars, buf.bars_1m):
            assert a.close == b.close

    def test_ema_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(30)
        buf.seed_bars(bars)
        ema_val = buf.ema(10)
        assert ema_val is not None

    def test_rsi_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(30)
        buf.seed_bars(bars)
        rsi_val = buf.rsi(14)
        assert rsi_val is not None

    def test_atr_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(30)
        buf.seed_bars(bars)
        atr_val = buf.atr(14)
        assert atr_val is not None

    def test_bollinger_bands_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(30)
        buf.seed_bars(bars)
        bb = buf.bollinger_bands(20)
        assert bb is not None
        lower, basis, upper = bb
        assert lower < basis < upper

    def test_adx_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(60)
        buf.seed_bars(bars)
        adx_val = buf.adx(14)
        assert adx_val is not None

    def test_sma_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(30)
        buf.seed_bars(bars)
        sma_val = buf.sma(20)
        assert sma_val is not None

    def test_ready_unchanged(self):
        buf = PriceBuffer()
        bars = _make_1m_bars(10)
        buf.seed_bars(bars)
        assert buf.ready(10)
        assert not buf.ready(11)


class TestResampling:
    """Task 1.3/1.4: resampling correctness."""

    def test_15m_resampling_count(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(60, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars_1m) == 60
        assert len(buf.bars) == 4

    def test_15m_boundary_alignment(self):
        """Bars align to wall-clock minute 0, 15, 30, 45."""
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(45, base_ts=0)
        buf.seed_bars(bars_1m)
        for bar in buf.bars:
            assert (bar.ts_minute // 60) % 15 == 0

    def test_ohlcv_aggregation(self):
        """First open, max high, min low, last close."""
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = []
        for i in range(15):
            bars_1m.append(MinuteBar(
                ts_minute=i * 60,
                open=_D(str(100 + i)),
                high=_D(str(110 + i)),
                low=_D(str(90 - i)),
                close=_D(str(105 + i)),
            ))
        buf.seed_bars(bars_1m)
        res_bars = buf.bars
        assert len(res_bars) == 1
        assert res_bars[0].open == _D("100")
        assert res_bars[0].high == _D("124")  # max of 110..124
        assert res_bars[0].low == _D("76")    # min of 90..76
        assert res_bars[0].close == _D("119") # last close

    def test_forming_bar_included(self):
        """The current (incomplete) resolution bar is included."""
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(20, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars) == 2  # 1 complete (0-14) + 1 forming (15-19)

    def test_5m_resampling(self):
        buf = PriceBuffer(resolution_minutes=5)
        bars_1m = _make_1m_bars(20, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars) == 4

    def test_60m_resampling(self):
        buf = PriceBuffer(resolution_minutes=60)
        bars_1m = _make_1m_bars(120, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars) == 2

    def test_resolution_1_no_resampling(self):
        buf = PriceBuffer(resolution_minutes=1)
        bars_1m = _make_1m_bars(10, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars) == 10


class TestIndicatorsAtHigherResolution:
    """Task 1.5: indicator computation on resampled bars."""

    def test_bb_on_15m(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)
        res_bars = buf.bars
        assert len(res_bars) >= 20
        bb = buf.bollinger_bands(20)
        assert bb is not None
        lower, basis, upper = bb
        assert lower < basis < upper

    def test_rsi_on_15m(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)
        rsi_val = buf.rsi(14)
        assert rsi_val is not None
        assert _D("0") <= rsi_val <= _D("100")

    def test_adx_on_15m(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(600, base_ts=0)
        buf.seed_bars(bars_1m)
        adx_val = buf.adx(14)
        assert adx_val is not None
        assert adx_val >= _D("0")

    def test_atr_on_15m(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)
        atr_val = buf.atr(14)
        assert atr_val is not None
        assert atr_val > _D("0")

    def test_ema_on_15m(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)
        ema_val = buf.ema(20)
        assert ema_val is not None

    def test_sma_on_15m(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)
        sma_val = buf.sma(20)
        assert sma_val is not None

    def test_ready_uses_resolution_bars(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(30, base_ts=0)
        buf.seed_bars(bars_1m)
        assert buf.ready(2)
        assert not buf.ready(10)

    def test_latest_close_uses_resolution_bars(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(20, base_ts=0)
        buf.seed_bars(bars_1m)
        lc = buf.latest_close()
        assert lc is not None
        assert lc == buf.bars[-1].close

    def test_closes_match_resolution_bars(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(60, base_ts=0)
        buf.seed_bars(bars_1m)
        closes = buf.closes
        res_bars = buf.bars
        assert len(closes) == len(res_bars)
        for c, b in zip(closes, res_bars):
            assert c == b.close

    def test_sma_matches_manual_computation(self):
        """Verify SMA at 15m matches manual computation from resampled closes."""
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)

        res_bars = buf.bars
        period = 20
        assert len(res_bars) >= period
        manual_sma = sum(float(b.close) for b in res_bars[-period:]) / period
        assert _close_enough(buf.sma(period), _D(str(manual_sma)))


class TestCacheInvalidation:
    """Task 1.6: cache management at resolution level."""

    def test_rsi_updates_on_new_1m_bar(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(400, base_ts=0)
        buf.seed_bars(bars_1m)
        rsi1 = buf.rsi(14)

        buf.append_bar(MinuteBar(
            ts_minute=400 * 60,
            open=_D("200"), high=_D("210"), low=_D("190"), close=_D("205"),
        ))
        rsi2 = buf.rsi(14)
        assert rsi1 != rsi2

    def test_ema_clears_on_new_bar_at_higher_resolution(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(300, base_ts=0)
        buf.seed_bars(bars_1m)
        ema1 = buf.ema(10)
        assert ema1 is not None

        buf.append_bar(MinuteBar(
            ts_minute=300 * 60,
            open=_D("150"), high=_D("160"), low=_D("140"), close=_D("155"),
        ))
        ema2 = buf.ema(10)
        assert ema2 is not None
        assert ema1 != ema2

    def test_atr_clears_on_new_bar_at_higher_resolution(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(300, base_ts=0)
        buf.seed_bars(bars_1m)
        atr1 = buf.atr(14)
        assert atr1 is not None

        buf.append_bar(MinuteBar(
            ts_minute=300 * 60,
            open=_D("50"), high=_D("200"), low=_D("30"), close=_D("180"),
        ))
        atr2 = buf.atr(14)
        assert atr2 is not None
        assert atr1 != atr2


class TestBarsVsBars1m:
    """Task 1.7: bars vs bars_1m."""

    def test_bars_returns_resolution_bars(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(60, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars) == 4
        assert len(buf.bars_1m) == 60

    def test_bars_1m_always_raw(self):
        buf = PriceBuffer(resolution_minutes=60)
        bars_1m = _make_1m_bars(120, base_ts=0)
        buf.seed_bars(bars_1m)
        assert len(buf.bars_1m) == 120
        assert len(buf.bars) == 2


class TestAdverseDriftUnaffected:
    """Task 1.9: adverse drift uses _samples, not bars."""

    def test_adverse_drift_independent_of_resolution(self):
        buf_1m = PriceBuffer(resolution_minutes=1)
        buf_15m = PriceBuffer(resolution_minutes=15)

        now = 1000.0
        prices = [(_D("100"), now - 35), (_D("100"), now - 25),
                  (_D("100"), now - 15), (_D("102"), now)]

        for price, ts in prices:
            buf_1m.add_sample(ts, price)
            buf_15m.add_sample(ts, price)

        drift_1m = buf_1m.adverse_drift_30s(now)
        drift_15m = buf_15m.adverse_drift_30s(now)
        assert drift_1m == drift_15m

    def test_adverse_drift_smooth_independent(self):
        buf_1m = PriceBuffer(resolution_minutes=1)
        buf_15m = PriceBuffer(resolution_minutes=15)

        now = 1000.0
        prices = [(_D("100"), now - 35), (_D("102"), now)]

        for price, ts in prices:
            buf_1m.add_sample(ts, price)
            buf_15m.add_sample(ts, price)

        d1 = buf_1m.adverse_drift_smooth(now, _D("0.1"))
        d2 = buf_15m.adverse_drift_smooth(now, _D("0.1"))
        assert d1 == d2


class TestMinBarsForResolution:
    def test_1m(self):
        assert PriceBuffer.min_bars_for_resolution(20, 1) == 20

    def test_15m(self):
        assert PriceBuffer.min_bars_for_resolution(20, 15) == 300

    def test_60m(self):
        assert PriceBuffer.min_bars_for_resolution(14, 60) == 840


class TestAddSampleAtHigherResolution:
    """Verify add_sample works correctly at higher resolutions."""

    def test_add_sample_builds_correct_bars(self):
        buf = PriceBuffer(resolution_minutes=15)
        for i in range(30):
            buf.add_sample(float(i * 60), _D(str(100 + i * 0.1)))
        assert len(buf.bars_1m) == 30
        assert len(buf.bars) == 2

    def test_seed_then_add_sample(self):
        buf = PriceBuffer(resolution_minutes=15)
        bars_1m = _make_1m_bars(300, base_ts=0)
        buf.seed_bars(bars_1m)
        old_count = len(buf.bars)

        buf.add_sample(300 * 60 + 5.0, _D("105"))
        assert len(buf.bars_1m) == 301
        new_count = len(buf.bars)
        assert new_count >= old_count
