"""Shared fixtures for ICT indicator tests."""
from __future__ import annotations

from decimal import Decimal

_D = Decimal


def make_candle(
    open_: str, high: str, low: str, close: str, volume: str = "100"
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    return _D(open_), _D(high), _D(low), _D(close), _D(volume)


def make_uptrend(
    n: int, start: str = "100", step: str = "1"
) -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Generate n ascending candles (bullish bodies)."""
    candles = []
    base = _D(start)
    s = _D(step)
    for i in range(n):
        o = base + s * i
        c = o + s
        h = c + s / 2
        l = o - s / 4
        candles.append((o, h, l, c, _D("100")))
    return candles


def make_downtrend(
    n: int, start: str = "200", step: str = "1"
) -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Generate n descending candles (bearish bodies)."""
    candles = []
    base = _D(start)
    s = _D(step)
    for i in range(n):
        o = base - s * i
        c = o - s
        h = o + s / 4
        l = c - s / 2
        candles.append((o, h, l, c, _D("100")))
    return candles


def make_range(
    n: int, center: str = "100", amplitude: str = "5"
) -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Generate n candles oscillating around center."""
    candles = []
    c_val = _D(center)
    amp = _D(amplitude)
    for i in range(n):
        direction = 1 if i % 2 == 0 else -1
        o = c_val
        close = c_val + amp * direction * (i % 3 + 1) / 3
        h = max(o, close) + amp / 4
        l = min(o, close) - amp / 4
        candles.append((o, h, l, close, _D("100")))
    return candles


def swing_series() -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Synthetic series that produces clear alternating swings.

    Pattern: 5 bars up, 5 bars down, repeated.
    With swing_length=2, swings should be detectable.
    """
    candles = []
    base = _D("100")
    for cycle in range(4):
        offset = base + _D(cycle) * _D("2")
        for i in range(5):
            o = offset + _D(i)
            c = o + _D("1")
            h = c + _D("0.5")
            l = o - _D("0.25")
            candles.append((o, h, l, c, _D("100")))
        for i in range(5):
            o = offset + _D("5") - _D(i)
            c = o - _D("1")
            h = o + _D("0.25")
            l = c - _D("0.5")
            candles.append((o, h, l, c, _D("100")))
    return candles


def fvg_bullish_series() -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """3 candles that form a clear bullish FVG.

    bar0: high=102
    bar1: any
    bar2: low=103  -> gap: bar0.high(102) < bar2.low(103) = bullish FVG
    """
    return [
        make_candle("100", "102", "99", "101"),   # bar 0
        make_candle("101", "104", "100", "103"),   # bar 1
        make_candle("103", "106", "103", "105"),   # bar 2 -> FVG: 102 < 103
    ]


def fvg_bearish_series() -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """3 candles that form a clear bearish FVG.

    bar0: low=98
    bar1: any
    bar2: high=97  -> gap: bar0.low(98) > bar2.high(97) = bearish FVG
    """
    return [
        make_candle("100", "101", "98", "99"),     # bar 0
        make_candle("99", "99", "96", "97"),        # bar 1
        make_candle("97", "97", "95", "96"),         # bar 2 -> FVG: 98 > 97
    ]
