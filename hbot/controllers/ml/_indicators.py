"""Float-native, vectorized indicator implementations for the ML pipeline.

All functions operate on numpy arrays or pandas Series with float64 dtype.
They mirror the algorithms in ``controllers/common/indicators.py`` (which
uses ``Decimal``) but are optimised for batch computation on large datasets.

Do NOT import ``controllers.common.indicators`` here — the Decimal and float
worlds are intentionally separate.  Correctness is validated by cross-checking
in tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Simple building blocks
# ---------------------------------------------------------------------------


def sma(values: pd.Series, period: int) -> pd.Series:
    """Rolling simple moving average."""
    return values.rolling(window=period, min_periods=period).mean()


def ema(values: pd.Series, period: int) -> pd.Series:
    """Exponential moving average, seeded from SMA of the first *period* values.

    ``alpha = 2 / (period + 1)`` — standard EMA multiplier.
    """
    return values.ewm(span=period, adjust=False, min_periods=period).mean()


def stddev(values: pd.Series, period: int) -> pd.Series:
    """Rolling population standard deviation."""
    return values.rolling(window=period, min_periods=period).std(ddof=0)


def bollinger_bands(
    closes: pd.Series,
    period: int = 20,
    stddev_mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return ``(lower, basis, upper)`` Bollinger Bands."""
    basis = sma(closes, period)
    std = stddev(closes, period)
    width = std * stddev_mult
    return basis - width, basis, basis + width


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Cutler's RSI (SMA-based), matching the Decimal reference."""
    delta = closes.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    result = result.where(avg_loss > 0.0, 100.0)
    return result


# ---------------------------------------------------------------------------
# Range-based indicators (require H/L/C)
# ---------------------------------------------------------------------------


def true_range(
    high: pd.Series, low: pd.Series, close: pd.Series,
) -> pd.Series:
    """True Range for each bar (NaN for the first bar)."""
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int,
) -> pd.Series:
    """Average True Range using Wilder's recursive smooth.

    Seeded from the simple mean of the first *period* True Ranges.
    """
    tr = true_range(high, low, close)
    # Wilder's smooth: alpha = 1/period
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def williams_r(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int,
) -> pd.Series:
    """Williams %R normalized to [0, 1] over a rolling *period*-bar window.

    0 = close equals the period low  (maximum oversold),
    1 = close equals the period high (maximum overbought).

    This is a positive-orientation rescaling of the traditional W%R
    (raw W%R = −100 × (HH − C) / (HH − LL)).  Leading ``period − 1``
    values are NaN, matching the warmup behaviour of the other indicators
    in this module.  Flat-range bars (HH == LL) return 0.5.
    """
    hh = high.rolling(window=period, min_periods=period).max()
    ll = low.rolling(window=period, min_periods=period).min()
    rng = hh - ll
    raw = (close - ll) / rng
    # Flat-range bars: rng == 0 but not NaN (warmup) → midpoint
    is_flat = (rng == 0) & rng.notna()
    return raw.where(~is_flat, 0.5)


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int,
) -> pd.Series:
    """Average Directional Index — full Wilder implementation."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    alpha = 1.0 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_w = pd.Series(plus_dm, index=high.index).ewm(
        alpha=alpha, adjust=False, min_periods=period
    ).mean()
    minus_w = pd.Series(minus_dm, index=high.index).ewm(
        alpha=alpha, adjust=False, min_periods=period
    ).mean()

    plus_di = 100.0 * (plus_w / atr_w)
    minus_di = 100.0 * (minus_w / atr_w)
    denom = plus_di + minus_di
    dx = np.where(denom > 0, 100.0 * (plus_di - minus_di).abs() / denom, 0.0)

    adx_val = pd.Series(dx, index=high.index).ewm(
        alpha=alpha, adjust=False, min_periods=period,
    ).mean()
    return adx_val
