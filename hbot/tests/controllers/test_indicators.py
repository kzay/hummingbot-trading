"""Tests for controllers.common.indicators — pure indicator functions.

Each test class covers one function.  Tests verify:
- correct return value for known inputs (exact or within tolerance)
- None / zero sentinel when data is insufficient
- edge cases: constant series, rising series, falling series, alternating
- algorithm contracts (EMA SMA-seed, ATR Wilder-smooth, RSI Cutler's, ADX Wilder)
"""
from __future__ import annotations

from decimal import Decimal

from controllers.common.indicators import (
    BarHLC,
    adx,
    atr,
    bollinger_bands,
    ema,
    rsi,
    sma,
    stddev,
)

_D = Decimal


def _bars(prices: list) -> list[BarHLC]:
    """Build synthetic BarHLC tuples where high = price + 1, low = price - 1, close = price."""
    return [(_D(str(p + 1)), _D(str(p - 1)), _D(str(p))) for p in prices]


def _bars_flat(price: float, count: int) -> list[BarHLC]:
    p = _D(str(price))
    return [(p, p, p)] * count


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------

class TestSma:
    def test_exact_value_constant_series(self):
        closes = [_D("100")] * 10
        assert sma(closes, 5) == _D("100")

    def test_none_when_insufficient(self):
        assert sma([_D("1"), _D("2")], 5) is None

    def test_none_for_zero_period(self):
        assert sma([_D("1")] * 10, 0) is None

    def test_uses_last_n_only(self):
        # First 5 values are 0, last 5 are 10 — SMA(5) should be 10.
        closes = [_D("0")] * 5 + [_D("10")] * 5
        assert sma(closes, 5) == _D("10")

    def test_rising_series_is_between_first_and_last(self):
        closes = [_D(str(i)) for i in range(1, 21)]
        result = sma(closes, 10)
        assert result is not None
        assert _D("11") < result < _D("20")


# ---------------------------------------------------------------------------
# Stddev
# ---------------------------------------------------------------------------

class TestStddev:
    def test_zero_for_constant_series(self):
        closes = [_D("100")] * 20
        assert stddev(closes, 10) == _D("0")

    def test_none_when_insufficient(self):
        assert stddev([_D("1")] * 4, 10) is None

    def test_positive_for_varying_series(self):
        closes = [_D(str(i)) for i in range(1, 11)]
        result = stddev(closes, 10)
        assert result is not None
        assert result > _D("0")

    def test_known_value(self):
        # stddev([1,2,3,4,5]) population = sqrt(2) ≈ 1.4142
        closes = [_D(str(i)) for i in range(1, 6)]
        result = stddev(closes, 5)
        assert result is not None
        assert abs(result - _D("1.4142")) < _D("0.001")


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEma:
    def test_none_when_insufficient(self):
        assert ema([_D("1")] * 4, 5) is None

    def test_none_for_zero_period(self):
        assert ema([_D("1")] * 10, 0) is None

    def test_constant_series_equals_price(self):
        result = ema([_D("100")] * 30, 10)
        assert result is not None
        assert abs(result - _D("100")) < _D("0.001")

    def test_rising_series_lags_behind_last_close(self):
        closes = [_D(str(i)) for i in range(1, 31)]
        result = ema(closes, 10)
        assert result is not None
        assert result < closes[-1]
        assert result > closes[0]

    def test_sma_seed_not_first_value(self):
        # Verify EMA is seeded from SMA(period) of first period closes, not closes[0].
        # For period=3, closes=[1,2,3,4,5]:
        # seed = SMA([1,2,3]) = 2.0, alpha = 2/(3+1) = 0.5
        # after bar 4: 0.5*4 + 0.5*2 = 3.0
        # after bar 5: 0.5*5 + 0.5*3 = 4.0
        closes = [_D("1"), _D("2"), _D("3"), _D("4"), _D("5")]
        result = ema(closes, 3)
        assert result == _D("4")

    def test_period_1_returns_last_close(self):
        closes = [_D("50"), _D("60"), _D("70")]
        result = ema(closes, 1)
        assert result == _D("70")


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_none_when_insufficient(self):
        assert bollinger_bands([_D("100")] * 5, period=20) is None

    def test_constant_price_zero_width(self):
        bands = bollinger_bands([_D("100")] * 25, period=20)
        assert bands is not None
        lower, basis, upper = bands
        assert lower == _D("100")
        assert basis == _D("100")
        assert upper == _D("100")

    def test_basis_equals_sma(self):
        closes = [_D(str(i)) for i in range(1, 26)]
        result = bollinger_bands(closes, period=10)
        expected_basis = sma(closes, 10)
        assert result is not None
        assert abs(result[1] - expected_basis) < _D("0.001")

    def test_upper_above_lower(self):
        closes = [_D(str(100 + (i % 3) * 2)) for i in range(25)]
        bands = bollinger_bands(closes, period=10)
        assert bands is not None
        lower, _, upper = bands
        assert upper > lower

    def test_custom_stddev_multiplier(self):
        closes = [_D(str(i)) for i in range(1, 26)]
        b1 = bollinger_bands(closes, period=10, stddev_mult=_D("1"))
        b2 = bollinger_bands(closes, period=10, stddev_mult=_D("2"))
        assert b2 is not None and b1 is not None
        # Wider bands with larger multiplier.
        assert b2[2] - b2[0] > b1[2] - b1[0]


# ---------------------------------------------------------------------------
# RSI (Cutler's)
# ---------------------------------------------------------------------------

class TestRsi:
    def test_none_when_insufficient(self):
        assert rsi([_D("100")] * 5, period=14) is None

    def test_none_for_zero_period(self):
        assert rsi([_D("100")] * 20, period=0) is None

    def test_100_for_all_gains(self):
        closes = [_D(str(i)) for i in range(1, 20)]
        result = rsi(closes, period=14)
        assert result == _D("100")

    def test_above_50_for_rising_series(self):
        closes = [_D(str(100 + i)) for i in range(20)]
        result = rsi(closes, period=14)
        assert result is not None
        assert result > _D("50")

    def test_below_50_for_falling_series(self):
        closes = [_D(str(120 - i)) for i in range(20)]
        result = rsi(closes, period=14)
        assert result is not None
        assert result < _D("50")

    def test_50_for_equal_gains_and_losses(self):
        # Alternating +1/-1: avg_gain == avg_loss → RSI = 50
        closes = [_D("100")]
        for i in range(14):
            closes.append(closes[-1] + (_D("1") if i % 2 == 0 else _D("-1")))
        result = rsi(closes, period=14)
        assert result is not None
        assert abs(result - _D("50")) < _D("0.01")

    def test_known_value(self):
        # 7 gains of 1, 7 losses of 1: avg_gain = avg_loss = 1 → RSI = 50.
        closes = []
        v = _D("100")
        for i in range(15):
            closes.append(v)
            v += _D("1") if i % 2 == 0 else _D("-1")
        result = rsi(closes, period=14)
        assert result is not None
        assert abs(result - _D("50")) < _D("1")


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestAtr:
    def test_none_when_insufficient(self):
        assert atr(_bars_flat(100, 5), period=14) is None

    def test_none_for_zero_period(self):
        assert atr(_bars_flat(100, 20), period=0) is None

    def test_zero_for_flat_bars(self):
        result = atr(_bars_flat(100, 20), period=5)
        assert result is not None
        assert result == _D("0")

    def test_positive_for_volatile_bars(self):
        bars = _bars([100, 103, 98, 105, 97, 102, 99, 104, 96, 103, 97, 105, 98, 103, 96, 105], )
        result = atr(bars, period=5)
        assert result is not None
        assert result > _D("0")

    def test_wilder_smoothing_seeded_from_mean(self):
        # For period=2, 5 bars: seed from mean(TR[0:2]), then Wilder-smooth.
        # Use explicit bars where TR is known.
        bars: list[BarHLC] = [
            (_D("102"), _D("98"), _D("100")),  # bar 0
            (_D("104"), _D("100"), _D("102")),  # TR = max(4, |104-100|, |100-100|) = 4
            (_D("106"), _D("102"), _D("104")),  # TR = 4
            (_D("108"), _D("104"), _D("106")),  # TR = 4
            (_D("110"), _D("106"), _D("108")),  # TR = 4
        ]
        result = atr(bars, period=2)
        # All TRs = 4: seed = mean([4,4]) = 4, Wilder of constant = 4.
        assert result is not None
        assert result == _D("4")

    def test_atr_minimum_bars_boundary(self):
        # period=3 needs at least 4 bars.
        bars = _bars([100, 101, 102])      # 3 bars — one short
        assert atr(bars, period=3) is None
        bars = _bars([100, 101, 102, 103])  # 4 bars — exact minimum
        assert atr(bars, period=3) is not None


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------

class TestAdx:
    def test_none_when_insufficient(self):
        # period=5 needs 11 bars.
        assert adx(_bars([100 + i for i in range(10)]), period=5) is None

    def test_none_for_zero_period(self):
        assert adx(_bars([100 + i for i in range(20)]), period=0) is None

    def test_returns_value_at_minimum_bars(self):
        bars = _bars([100 + i for i in range(11)])
        result = adx(bars, period=5)
        assert result is not None
        assert result >= _D("0")

    def test_high_for_strong_trend(self):
        # Consistent uptrend: each bar 3 higher than the last.
        bars = _bars([100 + i * 3 for i in range(30)])
        result = adx(bars, period=5)
        assert result is not None
        assert result > _D("50")

    def test_low_for_ranging_market(self):
        # Alternating price: no net directional movement.
        prices = [100 + (1 if i % 2 == 0 else -1) for i in range(25)]
        result = adx(_bars(prices), period=5)
        assert result is not None
        assert result < _D("30")

    def test_wilder_smoothing_correctness(self):
        """ADX must match a manually computed Wilder SMMA of DX."""
        from decimal import Decimal as D
        period = 3
        bars: list[BarHLC] = [
            (D(str(101 + i)), D(str(99 + i)), D(str(100 + i)))
            for i in range(9)
        ]
        # Manually compute expected ADX.
        trs, pdm, mdm = [], [], []
        for i in range(1, len(bars)):
            h, l, _ = bars[i]
            ph, pl, pc = bars[i - 1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            up = h - ph
            dn = pl - l
            pdm.append(up if up > dn and up > 0 else D(0))
            mdm.append(dn if dn > up and dn > 0 else D(0))
        p = D(period)
        atr_w = sum(trs[:period], D(0))
        plus_w = sum(pdm[:period], D(0))
        minus_w = sum(mdm[:period], D(0))
        dxs = []
        for i in range(period, len(trs)):
            atr_w = atr_w - atr_w / p + trs[i]
            plus_w = plus_w - plus_w / p + pdm[i]
            minus_w = minus_w - minus_w / p + mdm[i]
            pdi = D(100) * (plus_w / atr_w) if atr_w > 0 else D(0)
            mdi = D(100) * (minus_w / atr_w) if atr_w > 0 else D(0)
            denom = pdi + mdi
            dxs.append(D(100) * abs(pdi - mdi) / denom if denom > 0 else D(0))
        expected = sum(dxs[:period], D(0)) / p
        for dx in dxs[period:]:
            expected = expected - expected / p + dx / p

        result = adx(bars, period)
        assert result is not None
        assert abs(result - expected) < D("0.001")

    def test_flat_bars_produce_zero_adx(self):
        # No TR variation at all → ATR → 0 → DX = 0 → ADX = 0.
        bars = _bars_flat(100, 20)
        result = adx(bars, period=5)
        assert result is not None
        assert result == _D("0")
