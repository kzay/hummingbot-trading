"""Tests for PriceBuffer: EMA, ATR/band_pct, adverse_drift, bar construction, indicator caches."""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.common import indicators as _ind
from controllers.price_buffer import MinuteBar, PriceBuffer
import itertools

_D = Decimal

# Tolerance for float-vs-Decimal comparison.  PriceBuffer uses float
# internally for speed; the reference functions use Decimal.  On a
# 0-100 RSI/ADX scale this allows ~0.02 absolute difference.
_TOL = _D("0.02")


def _close_enough(a: Decimal | None, b: Decimal | None, tol: Decimal = _TOL) -> bool:
    """Return True if a and b are both None, or within *tol* of each other."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _fill_buffer(buf: PriceBuffer, prices: list, start_ts: float = 1000.0, interval_s: float = 60.0):
    """Feed one price per minute into the buffer."""
    for i, p in enumerate(prices):
        buf.add_sample(start_ts + i * interval_s, _D(str(p)))


class TestBarConstruction:
    def test_single_sample_creates_one_bar(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        assert len(buf.bars) == 1
        assert buf.bars[0].close == _D("100")

    def test_same_minute_updates_high_low_close(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1005.0, _D("105"))
        buf.add_sample(1010.0, _D("95"))
        assert len(buf.bars) == 1
        bar = buf.bars[0]
        assert bar.high == _D("105")
        assert bar.low == _D("95")
        assert bar.close == _D("95")

    def test_new_minute_creates_new_bar(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1060.0, _D("101"))
        assert len(buf.bars) == 2

    def test_gap_fills_missing_minutes(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        buf.add_sample(1180.0, _D("102"))  # 3 minutes later
        assert len(buf.bars) >= 3

    def test_zero_price_ignored(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("0"))
        assert len(buf.bars) == 0

    def test_negative_price_ignored(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("-5"))
        assert len(buf.bars) == 0

    def test_seed_bars_empty_is_noop(self):
        buf = PriceBuffer()
        assert buf.seed_bars([]) == 0
        assert len(buf.bars) == 0

    def test_seed_bars_non_empty_without_reset_raises(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        with pytest.raises(ValueError):
            buf.seed_bars([MinuteBar(ts_minute=1060, open=_D("101"), high=_D("101"), low=_D("101"), close=_D("101"))])

    def test_seed_bars_gap_fills_missing_minutes(self):
        buf = PriceBuffer()
        seeded = buf.seed_bars(
            [
                MinuteBar(ts_minute=960, open=_D("100"), high=_D("100"), low=_D("100"), close=_D("100")),
                MinuteBar(ts_minute=1140, open=_D("102"), high=_D("102"), low=_D("102"), close=_D("102")),
            ]
        )
        assert seeded == 4
        assert len(buf.bars) == 4
        assert buf.bars[1].close == _D("100")
        assert buf.bars[2].close == _D("100")

    def test_seed_samples_populates_recent_sample_tail(self):
        buf = PriceBuffer()
        seeded = buf.seed_samples([(960.0, _D("100")), (995.0, _D("101"))])
        assert seeded == 2
        assert buf.adverse_drift_30s(995.0) > _D("0")


class TestEma:
    def test_ema_none_when_insufficient_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.ema(10) is None

    def test_ema_converges_to_constant_price(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100.0] * 60)
        ema = buf.ema(20)
        assert ema is not None
        assert abs(ema - _D("100")) < _D("0.01")

    def test_ema_tracks_rising_prices(self):
        prices = [100 + i * 0.5 for i in range(60)]
        buf = PriceBuffer()
        _fill_buffer(buf, prices)
        ema = buf.ema(20)
        assert ema is not None
        assert ema > _D("100")
        assert ema < _D(str(prices[-1]))

    def test_ema_invalid_period_returns_none(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100] * 10)
        assert buf.ema(0) is None
        assert buf.ema(-1) is None

    def test_ema_incremental_matches_full_recompute(self):
        buf = PriceBuffer()
        prices = [100 + (i % 10) * 0.3 for i in range(80)]
        _fill_buffer(buf, prices)
        ema_first = buf.ema(20)
        buf._ema_values.clear()
        ema_recomputed = buf.ema(20)
        assert ema_first is not None
        assert ema_recomputed is not None
        assert abs(ema_first - ema_recomputed) < _D("0.001")

    def test_seeded_bars_match_live_fed_indicator_values(self):
        live = PriceBuffer()
        seeded = PriceBuffer()
        prices = [100, 101, 102, 101, 103, 104, 105, 104, 106, 107]
        start_ts = 960.0
        _fill_buffer(live, prices, start_ts=start_ts, interval_s=60.0)
        bars = [MinuteBar(ts_minute=bar.ts_minute, open=bar.open, high=bar.high, low=bar.low, close=bar.close) for bar in live.bars]
        seeded.seed_bars(bars)
        assert seeded.ema(5) == live.ema(5)


class TestAtrAndBandPct:
    def test_atr_none_when_insufficient_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.atr(14) is None

    def test_atr_zero_for_constant_price(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100.0] * 20)
        atr = buf.atr(5)
        assert atr is not None
        assert atr == _D("0")

    def test_atr_positive_for_varying_prices(self):
        prices = [100 + (i % 3) * 2 for i in range(20)]
        buf = PriceBuffer()
        _fill_buffer(buf, prices)
        atr = buf.atr(5)
        assert atr is not None
        assert atr > _D("0")

    def test_band_pct_none_when_atr_unavailable(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.band_pct(14) is None

    def test_band_pct_zero_for_constant_price(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100.0] * 20)
        bp = buf.band_pct(5)
        assert bp is not None
        assert bp == _D("0")

    def test_band_pct_positive_for_varying_prices(self):
        prices = [100, 102, 98, 103, 97, 101, 99, 104, 96, 100,
                  102, 98, 103, 97, 101, 99, 104, 96, 100, 102]
        buf = PriceBuffer()
        _fill_buffer(buf, prices)
        bp = buf.band_pct(5)
        assert bp is not None
        assert bp > _D("0")


class TestAdditionalIndicators:
    def test_bollinger_bands_center_on_constant_price(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100.0] * 40)
        bands = buf.bollinger_bands(20)
        assert bands is not None
        lower, basis, upper = bands
        assert _close_enough(lower, _D("100"))
        assert _close_enough(basis, _D("100"))
        assert _close_enough(upper, _D("100"))

    def test_rsi_above_50_on_rising_series(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100 + i for i in range(25)])
        rsi = buf.rsi(14)
        assert rsi is not None
        assert rsi > _D("50")

    def test_rsi_below_50_on_falling_series(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [125 - i for i in range(25)])
        rsi = buf.rsi(14)
        assert rsi is not None
        assert rsi < _D("50")

    def test_adx_positive_when_series_has_directional_moves(self):
        buf = PriceBuffer()
        prices = [100, 101, 103, 104, 106, 107, 109, 110, 112, 113, 115, 116, 118, 119, 121,
                  122, 124, 125, 127, 128, 130, 131, 133, 134, 136, 137, 139, 140, 142, 143]
        _fill_buffer(buf, prices)
        adx = buf.adx(14)
        assert adx is not None
        assert adx > _D("0")

    def test_adx_returns_none_below_minimum_bars(self):
        # Needs period * 2 + 1 bars; period=5 requires 11 bars.
        buf = PriceBuffer()
        prices = [100 + i for i in range(10)]  # 10 bars — one short
        _fill_buffer(buf, prices)
        assert buf.adx(5) is None

    def test_adx_returns_value_at_minimum_bars(self):
        buf = PriceBuffer()
        prices = [100 + i for i in range(11)]  # exactly 11 bars for period=5
        _fill_buffer(buf, prices)
        adx = buf.adx(5)
        assert adx is not None
        assert adx > _D("0")

    def test_adx_wilder_smoothing_correctness(self):
        """Verify that ADX matches a manually computed Wilder SMMA of DX.

        Uses explicit MinuteBar seeds so the exact TR/+DM/-DM values are
        known, allowing a deterministic expected-value comparison.
        """
        from decimal import Decimal as D
        period = 3
        # Build bars manually so we control H/L/C precisely.
        # 7 bars = period * 2 + 1 = 7, the minimum for period=3.
        bars = [
            MinuteBar(ts_minute=i * 60, open=D(str(100 + i)), high=D(str(101 + i)),
                      low=D(str(99 + i)), close=D(str(100 + i)))
            for i in range(9)  # extra bars so Wilder smoothing applies beyond seed
        ]
        buf = PriceBuffer()
        buf.seed_bars(bars)

        # Manually compute expected ADX with Wilder SMMA.
        trs, pdm, mdm = [], [], []
        for prev, cur in itertools.pairwise(bars):
            up = cur.high - prev.high
            dn = prev.low - cur.low
            trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
            pdm.append(up if up > dn and up > 0 else D(0))
            mdm.append(dn if dn > up and dn > 0 else D(0))
        p = D(period)
        atr = sum(trs[:period], D(0))
        plus = sum(pdm[:period], D(0))
        minus = sum(mdm[:period], D(0))
        dxs = []
        for i in range(period, len(trs)):
            atr = atr - atr / p + trs[i]
            plus = plus - plus / p + pdm[i]
            minus = minus - minus / p + mdm[i]
            plus_di = D(100) * (plus / atr) if atr > 0 else D(0)
            minus_di = D(100) * (minus / atr) if atr > 0 else D(0)
            denom = plus_di + minus_di
            dxs.append(D(100) * abs(plus_di - minus_di) / denom if denom > 0 else D(0))
        adx_expected = sum(dxs[:period], D(0)) / p
        for dx in dxs[period:]:
            adx_expected = adx_expected - adx_expected / p + dx / p

        result = buf.adx(period)
        assert result is not None
        assert abs(result - adx_expected) < D("0.05")

    def test_adx_low_for_ranging_price(self):
        """Oscillating prices with no directional bias should produce low ADX."""
        buf = PriceBuffer()
        # Alternate up/down 1 tick — no net directional movement
        prices = [100 + (1 if i % 2 == 0 else -1) for i in range(25)]
        _fill_buffer(buf, prices)
        adx = buf.adx(5)
        assert adx is not None
        assert adx < _D("30")

    def test_adx_high_for_strong_trend(self):
        """Consistent directional movement should produce high ADX."""
        buf = PriceBuffer()
        prices = [100 + i * 3 for i in range(30)]  # strong steady uptrend
        _fill_buffer(buf, prices)
        adx = buf.adx(5)
        assert adx is not None
        assert adx > _D("50")


class TestAdverseDrift:
    def test_drift_zero_with_empty_buffer(self):
        buf = PriceBuffer()
        assert buf.adverse_drift_30s(1000.0) == _D("0")

    def test_drift_zero_with_single_sample(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("100"))
        assert buf.adverse_drift_30s(1000.0) == _D("0")

    def test_drift_zero_for_constant_price(self):
        buf = PriceBuffer()
        for i in range(10):
            buf.add_sample(970.0 + i * 5, _D("100"))
        drift = buf.adverse_drift_30s(1015.0)
        assert drift == _D("0")

    def test_drift_positive_for_price_change(self):
        buf = PriceBuffer()
        buf.add_sample(960.0, _D("100"))
        buf.add_sample(970.0, _D("100"))
        buf.add_sample(980.0, _D("100"))
        buf.add_sample(995.0, _D("105"))
        drift = buf.adverse_drift_30s(995.0)
        assert drift > _D("0")

    def test_drift_monotonic_increase_detected(self):
        buf = PriceBuffer()
        for i in range(10):
            buf.add_sample(960.0 + i * 5, _D(str(100 + i)))
        drift = buf.adverse_drift_30s(1005.0)
        assert drift > _D("0")

    def test_smooth_drift_initializes_to_raw(self):
        buf = PriceBuffer()
        buf.add_sample(960.0, _D("100"))
        buf.add_sample(995.0, _D("105"))
        raw = buf.adverse_drift_30s(995.0)
        smooth = buf.adverse_drift_smooth(995.0, _D("0.25"))
        assert smooth == raw

    def test_smooth_drift_converges(self):
        buf = PriceBuffer()
        for i in range(20):
            buf.add_sample(960.0 + i * 5, _D("100"))
        for _ in range(10):
            buf.adverse_drift_smooth(1060.0, _D("0.25"))
        smooth = buf.adverse_drift_smooth(1060.0, _D("0.25"))
        assert smooth >= _D("0")


# ------------------------------------------------------------------
# NaN/Inf rejection tests
# ------------------------------------------------------------------

class TestNaNInfRejection:
    def test_add_sample_nan_rejected(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("NaN"))
        assert len(buf.bars) == 0

    def test_add_sample_inf_rejected(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("Infinity"))
        assert len(buf.bars) == 0

    def test_add_sample_neg_inf_rejected(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("-Infinity"))
        assert len(buf.bars) == 0

    def test_add_sample_zero_rejected(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("0"))
        assert len(buf.bars) == 0

    def test_add_sample_negative_rejected(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("-100"))
        assert len(buf.bars) == 0

    def test_valid_sample_after_nan_accepted(self):
        buf = PriceBuffer()
        buf.add_sample(1000.0, _D("NaN"))
        buf.add_sample(1001.0, _D("100"))
        assert len(buf.bars) == 1
        assert buf.bars[0].close == _D("100")

    def test_seed_bars_nan_ohlc_skipped(self):
        buf = PriceBuffer()
        bars = [
            MinuteBar(ts_minute=1000, open=_D("NaN"), high=_D("100"), low=_D("99"), close=_D("100")),
            MinuteBar(ts_minute=1060, open=_D("100"), high=_D("102"), low=_D("99"), close=_D("101")),
        ]
        seeded = buf.seed_bars(bars)
        assert seeded == 1  # only the valid bar

    def test_seed_samples_nan_skipped(self):
        buf = PriceBuffer()
        samples = [
            (1000.0, _D("NaN")),
            (1001.0, _D("100")),
            (1002.0, _D("Infinity")),
        ]
        seeded = buf.seed_samples(samples)
        assert seeded == 1


# ------------------------------------------------------------------
# Indicator cache correctness contract
# ------------------------------------------------------------------

# These prices produce non-trivial indicator values (trend, mean-reversion,
# varying volatility) and are long enough for all indicator minimum-bar
# requirements.
_TRENDING_PRICES = [100 + i * 0.7 + (i % 5) * 0.3 for i in range(80)]
_OSCILLATING_PRICES = [100 + (3 if i % 2 == 0 else -2) + i * 0.05 for i in range(80)]
_VOLATILE_PRICES = [100 + (i % 7 - 3) * 2 + i * 0.1 for i in range(80)]


def _make_bars_from_prices(prices: list[float]) -> list[MinuteBar]:
    """Build MinuteBars with synthetic H/L from close ±1."""
    bars = []
    for i, p in enumerate(prices):
        c = _D(str(p))
        bars.append(MinuteBar(
            ts_minute=i * 60,
            open=c - _D("0.3"),
            high=c + _D("1"),
            low=c - _D("1"),
            close=c,
        ))
    return bars


def _ref_sma(closes: list[Decimal], period: int) -> Decimal:
    return sum(closes[-period:], _D("0")) / _D(str(period))


def _ref_stddev(closes: list[Decimal], period: int) -> Decimal:
    from math import sqrt
    window = closes[-period:]
    mean = sum(window, _D("0")) / _D(str(period))
    variance = sum(((c - mean) ** 2 for c in window), _D("0")) / _D(str(period))
    return _D(str(sqrt(float(variance)))) if variance > _D("0") else _D("0")


class TestIndicatorCacheContract:
    """Verify every cached indicator returns values identical to the uncached
    reference computation.

    The contract: caching is a pure performance optimisation — it must never
    alter the numerical result. Each test builds the same bar history two ways
    (seeded and live-fed) and compares the PriceBuffer indicator against the
    standalone ``controllers.common.indicators`` reference or an inline
    reference computation.
    """

    # -- RSI ---------------------------------------------------------------

    def test_rsi_matches_reference_on_seeded_bars(self):
        bars = _make_bars_from_prices(_TRENDING_PRICES)
        buf = PriceBuffer()
        buf.seed_bars(bars)
        closes = [b.close for b in bars]
        for period in (5, 14, 20):
            expected = _ind.rsi(closes, period)
            result = buf.rsi(period)
            assert _close_enough(result, expected), f"RSI({period}) mismatch: {result} != {expected}"

    def test_rsi_matches_reference_on_live_fed_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _OSCILLATING_PRICES)
        closes = buf.closes
        for period in (5, 14):
            expected = _ind.rsi(closes, period)
            result = buf.rsi(period)
            assert _close_enough(result, expected), f"RSI({period}) mismatch after live feed"

    def test_rsi_cached_call_returns_same_value(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        first = buf.rsi(14)
        second = buf.rsi(14)
        assert first == second
        assert first is second

    def test_rsi_updates_after_new_bar(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES[:40])
        rsi_before = buf.rsi(14)
        _fill_buffer(buf, [200, 205, 210], start_ts=1000.0 + 40 * 60)
        rsi_after = buf.rsi(14)
        assert rsi_before != rsi_after

    def test_rsi_none_when_insufficient_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100] * 5)
        assert buf.rsi(14) is None
        assert buf.rsi(14) is None  # cached None path

    def test_rsi_100_for_all_gains(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100 + i for i in range(20)])
        result = buf.rsi(14)
        assert result is not None
        assert result == _D("100")

    # -- ADX ---------------------------------------------------------------

    def test_adx_matches_reference_on_seeded_bars(self):
        bars = _make_bars_from_prices(_TRENDING_PRICES)
        buf = PriceBuffer()
        buf.seed_bars(bars)
        bars_hlc = [(b.high, b.low, b.close) for b in bars]
        # ADX uses a windowed Wilder smooth (6×period bars) which may diverge
        # slightly from the full-history reference when history is long.
        adx_tol = _D("1.0")
        for period in (5, 14):
            expected = _ind.adx(bars_hlc, period)
            result = buf.adx(period)
            assert _close_enough(result, expected, adx_tol), f"ADX({period}) mismatch: {result} != {expected}"

    def test_adx_matches_reference_on_live_fed_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _VOLATILE_PRICES)
        bars_hlc = [(b.high, b.low, b.close) for b in buf.bars]
        adx_tol = _D("1.0")
        for period in (5, 14):
            expected = _ind.adx(bars_hlc, period)
            result = buf.adx(period)
            assert _close_enough(result, expected, adx_tol), f"ADX({period}) mismatch after live feed"

    def test_adx_cached_call_returns_same_value(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        first = buf.adx(14)
        second = buf.adx(14)
        assert first == second
        assert first is second

    def test_adx_updates_after_new_bar(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES[:40])
        adx_before = buf.adx(5)
        _fill_buffer(buf, [50, 45, 40], start_ts=1000.0 + 40 * 60)
        adx_after = buf.adx(5)
        assert adx_before != adx_after

    def test_adx_none_when_insufficient_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100 + i for i in range(10)])
        assert buf.adx(5) is None
        assert buf.adx(5) is None  # cached None path

    # -- SMA ---------------------------------------------------------------

    def test_sma_matches_reference_on_seeded_bars(self):
        bars = _make_bars_from_prices(_OSCILLATING_PRICES)
        buf = PriceBuffer()
        buf.seed_bars(bars)
        closes = [b.close for b in bars]
        for period in (5, 10, 20, 50):
            expected = _ref_sma(closes, period)
            result = buf.sma(period)
            assert _close_enough(result, expected), f"SMA({period}) mismatch: {result} != {expected}"

    def test_sma_matches_reference_on_live_fed_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        closes = buf.closes
        for period in (5, 20):
            expected = _ref_sma(closes, period)
            result = buf.sma(period)
            assert _close_enough(result, expected)

    def test_sma_cached_call_returns_same_value(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        first = buf.sma(20)
        second = buf.sma(20)
        assert first == second

    def test_sma_updates_after_new_bar(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES[:40])
        sma_before = buf.sma(10)
        _fill_buffer(buf, [500], start_ts=1000.0 + 40 * 60)
        sma_after = buf.sma(10)
        assert sma_before != sma_after

    def test_sma_none_when_insufficient_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100] * 3)
        assert buf.sma(10) is None
        assert buf.sma(10) is None  # cached None path

    # -- Stddev ------------------------------------------------------------

    def test_stddev_matches_reference_on_seeded_bars(self):
        bars = _make_bars_from_prices(_VOLATILE_PRICES)
        buf = PriceBuffer()
        buf.seed_bars(bars)
        closes = [b.close for b in bars]
        for period in (5, 10, 20):
            expected = _ref_stddev(closes, period)
            result = buf.stddev(period)
            assert _close_enough(result, expected), f"Stddev({period}) mismatch: {result} != {expected}"

    def test_stddev_matches_reference_on_live_fed_bars(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _OSCILLATING_PRICES)
        closes = buf.closes
        for period in (5, 20):
            expected = _ref_stddev(closes, period)
            result = buf.stddev(period)
            assert _close_enough(result, expected)

    def test_stddev_cached_call_returns_same_value(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        first = buf.stddev(20)
        second = buf.stddev(20)
        assert first == second

    def test_stddev_updates_after_new_bar(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES[:40])
        sd_before = buf.stddev(10)
        _fill_buffer(buf, [500], start_ts=1000.0 + 40 * 60)
        sd_after = buf.stddev(10)
        assert sd_before != sd_after

    def test_stddev_zero_for_constant_series(self):
        buf = PriceBuffer()
        _fill_buffer(buf, [100.0] * 30)
        assert buf.stddev(10) == _D("0")

    # -- Bollinger Bands ---------------------------------------------------

    def test_bollinger_matches_reference_on_seeded_bars(self):
        bars = _make_bars_from_prices(_OSCILLATING_PRICES)
        buf = PriceBuffer()
        buf.seed_bars(bars)
        closes = [b.close for b in bars]
        for period in (10, 20):
            basis = _ref_sma(closes, period)
            std = _ref_stddev(closes, period)
            expected = (basis - _D("2") * std, basis, basis + _D("2") * std)
            result = buf.bollinger_bands(period)
            assert result is not None
            for r, e in zip(result, expected, strict=True):
                assert _close_enough(r, e, _D("0.05")), f"BB({period}) mismatch: {r} != {e}"

    def test_bollinger_cached_indirectly_via_sma_stddev(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        bb1 = buf.bollinger_bands(20)
        bb2 = buf.bollinger_bands(20)
        assert bb1 == bb2

    def test_bollinger_updates_after_new_bar(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES[:40])
        bb_before = buf.bollinger_bands(10)
        _fill_buffer(buf, [500], start_ts=1000.0 + 40 * 60)
        bb_after = buf.bollinger_bands(10)
        assert bb_before != bb_after

    # -- Closes property ---------------------------------------------------

    def test_closes_matches_bar_closes(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        expected = [b.close for b in buf.bars]
        assert buf.closes == expected

    def test_closes_cached_returns_same_object(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        first = buf.closes
        second = buf.closes
        assert first is second

    def test_closes_updates_after_new_bar(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES[:20])
        closes_before = list(buf.closes)
        _fill_buffer(buf, [999], start_ts=1000.0 + 20 * 60)
        closes_after = buf.closes
        assert len(closes_after) > len(closes_before)
        assert closes_after[-1] == _D("999")

    # -- Seeded vs live-fed equivalence ------------------------------------

    def test_all_indicators_identical_seeded_vs_live(self):
        """The strongest contract: seeded and live-fed buffers with the same
        price series must produce indicator values within float tolerance for
        every indicator at every period tested."""
        prices = _TRENDING_PRICES

        live = PriceBuffer()
        _fill_buffer(live, prices, start_ts=0.0, interval_s=60.0)

        seeded = PriceBuffer()
        seeded.seed_bars([
            MinuteBar(ts_minute=b.ts_minute, open=b.open, high=b.high, low=b.low, close=b.close)
            for b in live.bars
        ])

        for period in (5, 14, 20):
            assert _close_enough(live.sma(period), seeded.sma(period)), f"SMA({period}) seeded≠live"
            assert _close_enough(live.stddev(period), seeded.stddev(period)), f"Stddev({period}) seeded≠live"
            assert _close_enough(live.rsi(period), seeded.rsi(period)), f"RSI({period}) seeded≠live"
            lb, bb, ub = live.bollinger_bands(period) or (None, None, None)
            ls, bs, us = seeded.bollinger_bands(period) or (None, None, None)
            assert _close_enough(lb, ls, _D("0.05")), f"BB({period}) lower seeded≠live"
            assert _close_enough(bb, bs, _D("0.05")), f"BB({period}) basis seeded≠live"
            assert _close_enough(ub, us, _D("0.05")), f"BB({period}) upper seeded≠live"
        for period in (5, 14):
            assert _close_enough(live.adx(period), seeded.adx(period), _D("1.0")), f"ADX({period}) seeded≠live"

    # -- Cache invalidation after reset ------------------------------------

    def test_all_caches_cleared_after_seed_reset(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _TRENDING_PRICES)
        buf.rsi(14)
        buf.adx(5)
        buf.sma(10)
        buf.stddev(10)
        _ = buf.closes

        new_bars = _make_bars_from_prices(_OSCILLATING_PRICES)
        buf.seed_bars(new_bars, reset=True)

        closes_after = [b.close for b in new_bars]
        assert _close_enough(buf.rsi(14), _ind.rsi(closes_after, 14))
        bars_hlc = [(b.high, b.low, b.close) for b in new_bars]
        assert _close_enough(buf.adx(5), _ind.adx(bars_hlc, 5), _D("1.0"))
        assert _close_enough(buf.sma(10), _ref_sma(closes_after, 10))
        assert _close_enough(buf.stddev(10), _ref_stddev(closes_after, 10))

    # -- Multiple periods cached independently -----------------------------

    def test_different_periods_cached_independently(self):
        buf = PriceBuffer()
        _fill_buffer(buf, _VOLATILE_PRICES)
        closes = buf.closes

        rsi5 = buf.rsi(5)
        rsi14 = buf.rsi(14)
        assert rsi5 != rsi14
        assert _close_enough(rsi5, _ind.rsi(closes, 5))
        assert _close_enough(rsi14, _ind.rsi(closes, 14))

        sma5 = buf.sma(5)
        sma20 = buf.sma(20)
        assert sma5 != sma20
        assert _close_enough(sma5, _ref_sma(closes, 5))
        assert _close_enough(sma20, _ref_sma(closes, 20))

    # -- Incremental growth: add bars one at a time and verify each step ---

    def test_indicators_correct_at_every_step_during_growth(self):
        """Feed prices one at a time and verify indicators match the reference
        at each step where they become computable (within float tolerance)."""
        buf = PriceBuffer()
        period = 5
        adx_period = 3  # needs 7 bars minimum

        for i, p in enumerate(_TRENDING_PRICES[:40]):
            buf.add_sample(1000.0 + i * 60, _D(str(p)))
            n = len(buf.bars)

            if n >= period + 1:
                closes = buf.closes
                expected_rsi = _ind.rsi(closes, period)
                assert _close_enough(buf.rsi(period), expected_rsi), f"RSI mismatch at bar {n}"

            if n >= period:
                closes = buf.closes
                expected_sma = _ref_sma(closes, period)
                assert _close_enough(buf.sma(period), expected_sma), f"SMA mismatch at bar {n}"

                expected_sd = _ref_stddev(closes, period)
                assert _close_enough(buf.stddev(period), expected_sd), f"Stddev mismatch at bar {n}"

            if n >= adx_period * 2 + 1:
                bars_hlc = [(b.high, b.low, b.close) for b in buf.bars]
                expected_adx = _ind.adx(bars_hlc, adx_period)
                assert _close_enough(buf.adx(adx_period), expected_adx, _D("1.0")), f"ADX mismatch at bar {n}"


class TestAppendBar:
    """Tests for PriceBuffer.append_bar() — incremental OHLCV bar injection."""

    def test_append_to_empty_buffer(self):
        buf = PriceBuffer()
        bar = MinuteBar(ts_minute=60, open=_D("100"), high=_D("105"), low=_D("98"), close=_D("102"))
        buf.append_bar(bar)
        assert len(buf.bars) == 1
        assert buf.bars[0].high == _D("105")
        assert buf.bars[0].low == _D("98")

    def test_append_preserves_ohlcv(self):
        buf = PriceBuffer()
        bar1 = MinuteBar(ts_minute=60, open=_D("100"), high=_D("110"), low=_D("95"), close=_D("105"))
        bar2 = MinuteBar(ts_minute=120, open=_D("105"), high=_D("115"), low=_D("100"), close=_D("112"))
        buf.append_bar(bar1)
        buf.append_bar(bar2)
        assert len(buf.bars) == 2
        assert buf.bars[1].high == _D("115")
        assert buf.bars[1].low == _D("100")

    def test_append_dedup_same_timestamp(self):
        buf = PriceBuffer()
        bar = MinuteBar(ts_minute=60, open=_D("100"), high=_D("105"), low=_D("98"), close=_D("102"))
        buf.append_bar(bar)
        buf.append_bar(bar)
        assert len(buf.bars) == 1

    def test_append_skips_out_of_order(self):
        buf = PriceBuffer()
        bar1 = MinuteBar(ts_minute=120, open=_D("100"), high=_D("105"), low=_D("98"), close=_D("102"))
        bar2 = MinuteBar(ts_minute=60, open=_D("99"), high=_D("104"), low=_D("97"), close=_D("101"))
        buf.append_bar(bar1)
        buf.append_bar(bar2)
        assert len(buf.bars) == 1

    def test_append_gap_fills(self):
        buf = PriceBuffer()
        bar1 = MinuteBar(ts_minute=60, open=_D("100"), high=_D("105"), low=_D("98"), close=_D("102"))
        bar3 = MinuteBar(ts_minute=180, open=_D("103"), high=_D("108"), low=_D("101"), close=_D("106"))
        buf.append_bar(bar1)
        buf.append_bar(bar3)
        assert len(buf.bars) == 3
        gap = buf.bars[1]
        assert gap.ts_minute == 120
        assert gap.open == _D("102")
        assert gap.high == _D("102")
        assert gap.low == _D("102")
        assert gap.close == _D("102")

    def test_append_skips_invalid_ohlc(self):
        buf = PriceBuffer()
        bad = MinuteBar(ts_minute=60, open=_D("100"), high=_D("0"), low=_D("98"), close=_D("102"))
        buf.append_bar(bad)
        assert len(buf.bars) == 0

    def test_append_matches_seed_bars_indicators(self):
        """append_bar one-by-one must produce identical indicators to seed_bars."""
        bars = [
            MinuteBar(
                ts_minute=60 * (i + 1),
                open=_D(str(100 + i)),
                high=_D(str(105 + i)),
                low=_D(str(95 + i)),
                close=_D(str(102 + i)),
            )
            for i in range(60)
        ]

        buf_seed = PriceBuffer()
        buf_seed.seed_bars(bars, reset=True)

        buf_append = PriceBuffer()
        for bar in bars:
            buf_append.append_bar(bar)

        assert len(buf_seed.bars) == len(buf_append.bars)
        assert _close_enough(buf_seed.ema(20), buf_append.ema(20))
        assert _close_enough(buf_seed.atr(14), buf_append.atr(14))
        assert _close_enough(buf_seed.rsi(14), buf_append.rsi(14))
        assert _close_enough(buf_seed.adx(14), buf_append.adx(14))
        assert _close_enough(buf_seed.sma(20), buf_append.sma(20))

    def test_append_after_seed_continues_indicators(self):
        """Warmup via seed_bars, then append_bar — indicators should remain correct."""
        warmup_bars = [
            MinuteBar(
                ts_minute=60 * (i + 1),
                open=_D(str(100 + i)),
                high=_D(str(105 + i)),
                low=_D(str(95 + i)),
                close=_D(str(102 + i)),
            )
            for i in range(40)
        ]
        extra_bars = [
            MinuteBar(
                ts_minute=60 * (i + 41),
                open=_D(str(140 + i)),
                high=_D(str(145 + i)),
                low=_D(str(135 + i)),
                close=_D(str(142 + i)),
            )
            for i in range(20)
        ]

        buf_ref = PriceBuffer()
        buf_ref.seed_bars(warmup_bars + extra_bars, reset=True)

        buf_test = PriceBuffer()
        buf_test.seed_bars(warmup_bars, reset=True)
        for bar in extra_bars:
            buf_test.append_bar(bar)

        assert len(buf_ref.bars) == len(buf_test.bars)
        assert _close_enough(buf_ref.ema(20), buf_test.ema(20))
        assert _close_enough(buf_ref.atr(14), buf_test.atr(14))
        assert _close_enough(buf_ref.rsi(14), buf_test.rsi(14))
        assert _close_enough(buf_ref.sma(20), buf_test.sma(20))

    def test_atr_nonzero_with_real_ohlcv(self):
        """ATR from OHLCV bars with range must be > 0 (the core problem this fixes)."""
        buf = PriceBuffer()
        for i in range(30):
            bar = MinuteBar(
                ts_minute=60 * (i + 1),
                open=_D(str(50000 + i * 10)),
                high=_D(str(50050 + i * 10)),
                low=_D(str(49950 + i * 10)),
                close=_D(str(50010 + i * 10)),
            )
            buf.append_bar(bar)
        atr_val = buf.atr(14)
        assert atr_val is not None
        assert atr_val > _D("0"), f"ATR should be > 0 with real H/L range, got {atr_val}"
