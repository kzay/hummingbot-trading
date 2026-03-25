"""Cross-validation of float-native indicators vs Decimal reference."""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from controllers.common import indicators as ref_ind
from controllers.common.indicators import BarHLC
from controllers.ml import _indicators as ml_ind

TOLERANCE = 1e-4


@pytest.fixture
def price_series() -> list[float]:
    np.random.seed(42)
    base = 50000.0
    returns = np.random.normal(0.0001, 0.003, 200)
    prices = [base]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return prices


@pytest.fixture
def hlc_bars(price_series) -> list[tuple[float, float, float]]:
    np.random.seed(42)
    bars = []
    for c in price_series:
        spread = c * 0.002
        h = c + abs(np.random.normal(0, spread))
        l = c - abs(np.random.normal(0, spread))
        bars.append((h, l, c))
    return bars


@pytest.mark.parametrize(
    "name, ref_fn, ml_fn, period, tol",
    [
        ("SMA", ref_ind.sma, ml_ind.sma, 20, TOLERANCE),
        ("EMA", ref_ind.ema, ml_ind.ema, 20, TOLERANCE),
        ("RSI", ref_ind.rsi, ml_ind.rsi, 14, 1.0),
        ("Stddev", ref_ind.stddev, ml_ind.stddev, 20, TOLERANCE),
    ],
    ids=["sma", "ema", "rsi", "stddev"],
)
class TestScalarIndicatorMatchesDecimal:
    def test_matches_decimal(self, price_series, name, ref_fn, ml_fn, period, tol):
        closes_dec = [Decimal(str(p)) for p in price_series]
        closes_pd = pd.Series(price_series)

        ref = ref_fn(closes_dec, period)
        ml = ml_fn(closes_pd, period).iloc[-1]

        assert ref is not None
        if tol >= 1.0:
            assert abs(float(ref) - ml) < tol, f"{name}: {ref} vs {ml}"
        else:
            assert abs(float(ref) - ml) / float(ref) < tol, f"{name}: {ref} vs {ml}"


class TestATR:
    def test_matches_decimal(self, hlc_bars):
        bars_dec: list[BarHLC] = [
            (Decimal(str(h)), Decimal(str(l)), Decimal(str(c)))
            for h, l, c in hlc_bars
        ]
        h_pd = pd.Series([b[0] for b in hlc_bars])
        l_pd = pd.Series([b[1] for b in hlc_bars])
        c_pd = pd.Series([b[2] for b in hlc_bars])

        ref = ref_ind.atr(bars_dec, 14)
        ml = ml_ind.atr(h_pd, l_pd, c_pd, 14).iloc[-1]

        assert ref is not None
        assert abs(float(ref) - ml) / float(ref) < TOLERANCE


class TestBollingerBands:
    def test_matches_decimal(self, price_series):
        closes_dec = [Decimal(str(p)) for p in price_series]
        closes_pd = pd.Series(price_series)

        ref = ref_ind.bollinger_bands(closes_dec, 20, Decimal("2"))
        lower_ml, basis_ml, upper_ml = ml_ind.bollinger_bands(closes_pd, 20, 2.0)

        assert ref is not None
        ref_lower, ref_basis, ref_upper = ref
        assert abs(float(ref_basis) - basis_ml.iloc[-1]) / float(ref_basis) < TOLERANCE
        assert abs(float(ref_lower) - lower_ml.iloc[-1]) / float(ref_lower) < TOLERANCE
        assert abs(float(ref_upper) - upper_ml.iloc[-1]) / float(ref_upper) < TOLERANCE


class TestWilliamsR:
    def test_output_range(self, hlc_bars):
        h = pd.Series([b[0] for b in hlc_bars])
        l = pd.Series([b[1] for b in hlc_bars])
        c = pd.Series([b[2] for b in hlc_bars])
        result = ml_ind.williams_r(h, l, c, 14)
        valid = result.dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 1.0).all()

    def test_warmup_nan(self, hlc_bars):
        h = pd.Series([b[0] for b in hlc_bars])
        l = pd.Series([b[1] for b in hlc_bars])
        c = pd.Series([b[2] for b in hlc_bars])
        result = ml_ind.williams_r(h, l, c, 14)
        assert result.iloc[:13].isna().all(), "First period-1 values must be NaN"
        assert result.iloc[13:].notna().all(), "Values from period onward must be valid"

    def test_at_period_high_equals_one(self):
        """Close always at the period high → W%R == 1.0."""
        n, period = 50, 10
        h = pd.Series([100.0] * n)
        l = pd.Series([90.0] * n)
        c = pd.Series([100.0] * n)
        result = ml_ind.williams_r(h, l, c, period)
        valid = result.dropna()
        assert np.allclose(valid.values, 1.0)

    def test_at_period_low_equals_zero(self):
        """Close always at the period low → W%R == 0.0."""
        n, period = 50, 10
        h = pd.Series([100.0] * n)
        l = pd.Series([90.0] * n)
        c = pd.Series([90.0] * n)
        result = ml_ind.williams_r(h, l, c, period)
        valid = result.dropna()
        assert np.allclose(valid.values, 0.0, atol=1e-9)

    def test_flat_range_returns_midpoint(self):
        """Flat price (HH == LL) should return 0.5 rather than NaN."""
        n, period = 20, 5
        h = pd.Series([100.0] * n)
        l = pd.Series([100.0] * n)
        c = pd.Series([100.0] * n)
        result = ml_ind.williams_r(h, l, c, period)
        valid = result.dropna()
        assert np.allclose(valid.values, 0.5)

    def test_midpoint_price(self):
        """Close at exact midpoint of range → W%R == 0.5."""
        n, period = 50, 10
        h = pd.Series([100.0] * n)
        l = pd.Series([90.0] * n)
        c = pd.Series([95.0] * n)
        result = ml_ind.williams_r(h, l, c, period)
        valid = result.dropna()
        assert np.allclose(valid.values, 0.5)
