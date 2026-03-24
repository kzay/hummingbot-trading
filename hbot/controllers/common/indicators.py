"""Pure indicator functions shared across strategy lanes.

All functions are stateless, operate on plain Python sequences, and return
``None`` (or ``Decimal("0")`` where documented) when there is insufficient
data.  Strategy-specific bar builders (e.g. ``PriceBuffer``) delegate here
rather than maintaining their own copies of the algorithm.

Naming conventions
------------------
- ``closes``  – ``List[Decimal]`` of bar close prices, oldest first.
- ``BarHLC``  – ``Tuple[Decimal, Decimal, Decimal]`` of (high, low, close),
  used by ATR and ADX which require intrabar range data.

Algorithm choices (all documented explicitly)
---------------------------------------------
- EMA: seeded from SMA of the first ``period`` closes, then standard
  exponential smoothing ``alpha = 2 / (period + 1)``.
- ATR: seeded from the simple mean of the first ``period`` True Ranges, then
  Wilder's recursive smooth ``ATR_i = ATR_{i-1} - ATR_{i-1}/N + TR_i/N``.
- RSI: Cutler's RSI — simple average of gains and losses over ``period``
  changes, **not** Wilder's recursive smooth.  This is intentional: Cutler's
  RSI is more responsive for mean-reversion signal detection.  If callers need
  Wilder RSI they should implement it on top of this module.
- ADX: full Wilder implementation — Wilder-smoothed ATR/+DM/-DM, then ADX
  seeded from the mean of the first ``period`` DX values and recursively
  smoothed: ``ADX_i = ADX_{i-1} - ADX_{i-1}/N + DX_i/N``.
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from math import sqrt
import itertools

# (high, low, close) triple used by ATR and ADX.
BarHLC = tuple[Decimal, Decimal, Decimal]

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Simple building blocks
# ---------------------------------------------------------------------------

def sma(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """Simple moving average of the last ``period`` closes."""
    if period <= 0 or len(closes) < period:
        return None
    window = list(closes)[-period:]
    return sum(window, _ZERO) / Decimal(period)


def stddev(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """Population standard deviation of the last ``period`` closes."""
    if period <= 0 or len(closes) < period:
        return None
    window = list(closes)[-period:]
    mean = sum(window, _ZERO) / Decimal(period)
    variance = sum(((c - mean) ** 2 for c in window), _ZERO) / Decimal(period)
    return Decimal(str(sqrt(float(variance)))) if variance > _ZERO else _ZERO


def ema(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """Exponential moving average seeded from SMA of the first ``period`` closes.

    ``alpha = 2 / (period + 1)`` — standard EMA multiplier.  Requires at
    least ``period`` bars.  Returns ``None`` when insufficient data.
    """
    if period <= 0 or len(closes) < period:
        return None
    data = list(closes)
    alpha = _TWO / Decimal(period + 1)
    one_minus = _ONE - alpha
    # Seed from SMA of the first period values, then apply EMA over the rest.
    ema_val = sum(data[:period], _ZERO) / Decimal(period)
    for close in data[period:]:
        ema_val = alpha * close + one_minus * ema_val
    return ema_val


def bollinger_bands(
    closes: Sequence[Decimal],
    period: int = 20,
    stddev_mult: Decimal = _TWO,
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Return ``(lower, basis, upper)`` Bollinger Bands.

    ``basis`` is the SMA of the last ``period`` closes.  Band width is
    ``stddev_mult`` × population standard deviation.
    """
    basis = sma(closes, period)
    std = stddev(closes, period)
    if basis is None or std is None:
        return None
    width = std * stddev_mult
    return basis - width, basis, basis + width


def rsi(closes: Sequence[Decimal], period: int = 14) -> Decimal | None:
    """Cutler's RSI — simple average of gains and losses over ``period`` bars.

    Requires ``period + 1`` closes (to produce ``period`` price changes).
    Returns 100 when there are no down moves and ``None`` when data is
    insufficient.

    Note: This is Cutler's RSI (SMA-based), not Wilder's RSI.  It is more
    responsive than Wilder's for short periods and is preferred for
    mean-reversion signal detection in this codebase.
    """
    if period <= 0 or len(closes) < period + 1:
        return None
    window = list(closes)[-(period + 1):]
    gains = _ZERO
    losses = _ZERO
    for prev, cur in itertools.pairwise(window):
        delta = cur - prev
        if delta > _ZERO:
            gains += delta
        elif delta < _ZERO:
            losses -= delta  # abs(delta)
    avg_gain = gains / Decimal(period)
    avg_loss = losses / Decimal(period)
    if avg_loss <= _ZERO:
        return _HUNDRED
    rs = avg_gain / avg_loss
    return _HUNDRED - (_HUNDRED / (_ONE + rs))


# ---------------------------------------------------------------------------
# Range-based indicators (require H/L/C)
# ---------------------------------------------------------------------------

def _true_ranges(bars: Sequence[BarHLC]) -> list[Decimal]:
    """Compute True Range for each bar pair (bars[i-1], bars[i])."""
    trs: list[Decimal] = []
    for i in range(1, len(bars)):
        high, low, _ = bars[i]
        _, _, prev_close = bars[i - 1]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return trs


def atr(bars: Sequence[BarHLC], period: int) -> Decimal | None:
    """Average True Range using Wilder's recursive smooth.

    Seeded from the simple mean of the first ``period`` True Ranges, then
    ``ATR_i = ATR_{i-1} - ATR_{i-1}/N + TR_i/N`` for each subsequent bar.
    Requires at least ``period + 1`` bars.
    """
    if period <= 0 or len(bars) < period + 1:
        return None
    trs = _true_ranges(bars)
    if len(trs) < period:
        return None
    p = Decimal(period)
    atr_val = sum(trs[:period], _ZERO) / p
    for tr in trs[period:]:
        atr_val = atr_val - (atr_val / p) + tr / p
    return atr_val


def adx(bars: Sequence[BarHLC], period: int) -> Decimal | None:
    """Average Directional Index — full Wilder implementation.

    Requires at least ``period * 2 + 1`` bars:
    - ``period`` bars to seed the Wilder ATR/+DM/-DM accumulators,
    - ``period`` post-seed bar transitions to build the first ``period`` DX
      values that seed the initial ADX,
    - Any additional bars are consumed by recursive Wilder ADX smoothing:
      ``ADX_i = ADX_{i-1} - ADX_{i-1}/N + DX_i/N``.

    Returns ``None`` when data is insufficient.
    """
    if period <= 0 or len(bars) < period * 2 + 1:
        return None

    trs: list[Decimal] = []
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    for i in range(1, len(bars)):
        high, low, _ = bars[i]
        prev_high, prev_low, prev_close = bars[i - 1]
        up_move = high - prev_high
        down_move = prev_low - low
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        plus_dm.append(up_move if up_move > down_move and up_move > _ZERO else _ZERO)
        minus_dm.append(down_move if down_move > up_move and down_move > _ZERO else _ZERO)

    p = Decimal(period)
    # Seed Wilder accumulators from first ``period`` bar transitions.
    atr_w = sum(trs[:period], _ZERO)
    plus_w = sum(plus_dm[:period], _ZERO)
    minus_w = sum(minus_dm[:period], _ZERO)

    # Compute DX for each subsequent bar using Wilder-smoothed ATR/+DM/-DM.
    dxs: list[Decimal] = []
    for idx in range(period, len(trs)):
        atr_w = atr_w - (atr_w / p) + trs[idx]
        plus_w = plus_w - (plus_w / p) + plus_dm[idx]
        minus_w = minus_w - (minus_w / p) + minus_dm[idx]
        if atr_w <= _ZERO:
            dxs.append(_ZERO)
            continue
        plus_di = _HUNDRED * (plus_w / atr_w)
        minus_di = _HUNDRED * (minus_w / atr_w)
        denom = plus_di + minus_di
        dxs.append((_HUNDRED * abs(plus_di - minus_di) / denom) if denom > _ZERO else _ZERO)

    if len(dxs) < period:
        return None

    # Seed ADX from mean of first ``period`` DX values, then Wilder-smooth.
    adx_val = sum(dxs[:period], _ZERO) / p
    for dx in dxs[period:]:
        adx_val = adx_val - (adx_val / p) + (dx / p)
    return adx_val
