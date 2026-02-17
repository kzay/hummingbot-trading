"""
Technical Indicators — Pure Python
===================================

Reusable indicator functions (no ta-lib / numpy dependency).
Can be imported by any Hummingbot script strategy.

Classes:
    PriceCollector   — aggregates tick prices into synthetic OHLC candles
Functions:
    compute_rsi      — Wilder-smoothed Relative Strength Index
    compute_atr      — Wilder-smoothed Average True Range
    compute_ema      — Exponential Moving Average
    compute_sma      — Simple Moving Average
    compute_bollinger— Bollinger Bands (mid, upper, lower)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple


@dataclass
class Candle:
    """Single OHLC candle."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float


class PriceCollector:
    """
    Collects raw price ticks and aggregates them into fixed-interval
    OHLC candles.  Used by strategies that cannot rely on exchange
    candle feeds.

    Usage::

        pc = PriceCollector(candle_interval=60, max_candles=200)
        pc.add_tick(price=42000.0, ts=time.time())
        closes = pc.closes          # list of candle close prices
        candles = pc.all_candles    # list of Candle objects
    """

    def __init__(self, candle_interval: int = 60, max_candles: int = 200):
        self.candle_interval = candle_interval
        self.max_candles = max_candles
        self.candles: Deque[Candle] = deque(maxlen=max_candles)
        self._cur: Optional[Candle] = None
        self._start_ts: float = 0.0

    def add_tick(self, price: float, ts: float) -> None:
        """Record a price observation.  Candle boundaries are automatic."""
        if self._cur is None:
            self._open(price, ts)
            return
        if ts - self._start_ts >= self.candle_interval:
            self.candles.append(self._cur)
            self._open(price, ts)
        else:
            self._cur.high = max(self._cur.high, price)
            self._cur.low = min(self._cur.low, price)
            self._cur.close = price

    def _open(self, price: float, ts: float) -> None:
        self._cur = Candle(timestamp=ts, open=price, high=price,
                           low=price, close=price)
        self._start_ts = ts

    @property
    def closes(self) -> List[float]:
        out = [c.close for c in self.candles]
        if self._cur:
            out.append(self._cur.close)
        return out

    @property
    def all_candles(self) -> List[Candle]:
        out = list(self.candles)
        if self._cur:
            out.append(self._cur)
        return out

    @property
    def count(self) -> int:
        return len(self.candles) + (1 if self._cur else 0)


# ═══════════════════════════════════════════════════════════════════════════
#  Indicator Functions
# ═══════════════════════════════════════════════════════════════════════════

def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """
    Wilder-smoothed Relative Strength Index.

    Returns ``None`` if fewer than ``period + 1`` data points are available.
    """
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_g / avg_l))


def compute_atr(candles: List[Candle], period: int = 14) -> Optional[float]:
    """
    Wilder-smoothed Average True Range.

    Returns ``None`` if fewer than ``period + 1`` candles are available.
    """
    if len(candles) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(candles)):
        h, lo, pc = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def compute_ema(values: List[float], period: int) -> Optional[float]:
    """
    Exponential Moving Average of the last ``period`` values.

    Returns ``None`` if insufficient data.
    """
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def compute_sma(values: List[float], period: int) -> Optional[float]:
    """Simple Moving Average over the last ``period`` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def compute_bollinger(
    closes: List[float], period: int = 20, num_std: float = 2.0
) -> Optional[Tuple[float, float, float]]:
    """
    Bollinger Bands: ``(middle, upper, lower)``.

    Returns ``None`` if insufficient data.
    """
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = variance ** 0.5
    return (mid, mid + num_std * std, mid - num_std * std)
