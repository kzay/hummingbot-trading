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


class TestSMA:
    def test_matches_decimal(self, price_series):
        closes_dec = [Decimal(str(p)) for p in price_series]
        closes_pd = pd.Series(price_series)

        ref = ref_ind.sma(closes_dec, 20)
        ml = ml_ind.sma(closes_pd, 20).iloc[-1]

        assert ref is not None
        assert abs(float(ref) - ml) / float(ref) < TOLERANCE


class TestEMA:
    def test_matches_decimal(self, price_series):
        closes_dec = [Decimal(str(p)) for p in price_series]
        closes_pd = pd.Series(price_series)

        ref = ref_ind.ema(closes_dec, 20)
        ml = ml_ind.ema(closes_pd, 20).iloc[-1]

        assert ref is not None
        assert abs(float(ref) - ml) / float(ref) < TOLERANCE


class TestRSI:
    def test_matches_decimal(self, price_series):
        closes_dec = [Decimal(str(p)) for p in price_series]
        closes_pd = pd.Series(price_series)

        ref = ref_ind.rsi(closes_dec, 14)
        ml = ml_ind.rsi(closes_pd, 14).iloc[-1]

        assert ref is not None
        assert abs(float(ref) - ml) < 1.0  # RSI values [0-100], within 1pt


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


class TestStddev:
    def test_matches_decimal(self, price_series):
        closes_dec = [Decimal(str(p)) for p in price_series]
        closes_pd = pd.Series(price_series)

        ref = ref_ind.stddev(closes_dec, 20)
        ml = ml_ind.stddev(closes_pd, 20).iloc[-1]

        assert ref is not None
        assert abs(float(ref) - ml) / max(float(ref), 1e-10) < TOLERANCE
