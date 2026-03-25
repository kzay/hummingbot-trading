"""Unit tests for ta_signals signal primitives."""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.backtesting.ta_signals import (
    SIGNAL_REGISTRY,
    SignalResult,
    bb_breakout,
    bb_squeeze,
    ema_cross,
    ict_structure,
    macd_cross,
    macd_histogram,
    rsi_zone,
    stoch_rsi_cross,
    validate_signal_params,
    warmup_bars_for_signal,
)
from controllers.price_buffer import MinuteBar, PriceBuffer


def _make_buf(prices: list[float]) -> PriceBuffer:
    buf = PriceBuffer()
    bars = []
    for i, p in enumerate(prices):
        bars.append(MinuteBar(
            ts_minute=1000 + i * 60,
            open=Decimal(str(p)),
            high=Decimal(str(p * 1.002)),
            low=Decimal(str(p * 0.998)),
            close=Decimal(str(p)),
        ))
    buf.seed_bars(bars)
    return buf


# ---------------------------------------------------------------------------
# SignalResult
# ---------------------------------------------------------------------------

class TestSignalResult:
    def test_frozen(self):
        sr = SignalResult("long", 0.5)
        with pytest.raises(Exception):
            sr.direction = "short"  # type: ignore[misc]

    def test_strength_clamped(self):
        sr = SignalResult("long", 1.5)
        assert sr.strength <= 1.0
        sr2 = SignalResult("short", -0.3)
        assert sr2.strength >= 0.0


# ---------------------------------------------------------------------------
# ema_cross
# ---------------------------------------------------------------------------

class TestEmaCross:
    def test_neutral_when_insufficient(self):
        buf = _make_buf([100] * 5)
        assert ema_cross(buf, fast=8, slow=21).direction == "neutral"

    def test_bullish_crossover(self):
        prices = [100 - i * 0.5 for i in range(30)]
        prices += [prices[-1] + i * 2 for i in range(1, 15)]
        buf = _make_buf(prices)
        result = ema_cross(buf, fast=5, slow=15)
        assert result.direction in ("long", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_bearish_crossover(self):
        prices = [100 + i * 0.5 for i in range(30)]
        prices += [prices[-1] - i * 2 for i in range(1, 15)]
        buf = _make_buf(prices)
        result = ema_cross(buf, fast=5, slow=15)
        assert result.direction in ("short", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_constant_price_neutral(self):
        buf = _make_buf([100.0] * 50)
        result = ema_cross(buf, fast=5, slow=15)
        assert result.direction == "neutral"


# ---------------------------------------------------------------------------
# rsi_zone
# ---------------------------------------------------------------------------

class TestRsiZone:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 5)
        assert rsi_zone(buf, period=14).direction == "neutral"

    def test_oversold(self):
        prices = [100 - i * 0.8 for i in range(40)]
        buf = _make_buf(prices)
        result = rsi_zone(buf, period=14, overbought=70, oversold=30)
        assert result.direction == "long"
        assert 0.0 <= result.strength <= 1.0

    def test_overbought(self):
        prices = [100 + i * 0.8 for i in range(40)]
        buf = _make_buf(prices)
        result = rsi_zone(buf, period=14, overbought=70, oversold=30)
        assert result.direction == "short"
        assert 0.0 <= result.strength <= 1.0

    def test_neutral_zone(self):
        prices = [100 + (i % 3 - 1) * 0.1 for i in range(40)]
        buf = _make_buf(prices)
        result = rsi_zone(buf, period=14, overbought=70, oversold=30)
        assert result.direction == "neutral"


# ---------------------------------------------------------------------------
# macd_cross
# ---------------------------------------------------------------------------

class TestMacdCross:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 10)
        assert macd_cross(buf).direction == "neutral"

    def test_bullish_cross(self):
        prices = [100 - i * 0.3 for i in range(40)]
        prices += [prices[-1] + i * 1.5 for i in range(1, 20)]
        buf = _make_buf(prices)
        result = macd_cross(buf, fast=8, slow=21, signal=5)
        assert result.direction in ("long", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_bearish_cross(self):
        prices = [100 + i * 0.3 for i in range(40)]
        prices += [prices[-1] - i * 1.5 for i in range(1, 20)]
        buf = _make_buf(prices)
        result = macd_cross(buf, fast=8, slow=21, signal=5)
        assert result.direction in ("short", "neutral")
        assert 0.0 <= result.strength <= 1.0


# ---------------------------------------------------------------------------
# macd_histogram
# ---------------------------------------------------------------------------

class TestMacdHistogram:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 5)
        assert macd_histogram(buf).direction == "neutral"

    def test_positive_histogram(self):
        prices = [100 + i * 0.5 for i in range(60)]
        buf = _make_buf(prices)
        result = macd_histogram(buf, fast=12, slow=26, signal=9, threshold=0.0)
        assert result.direction in ("long", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_negative_histogram(self):
        prices = [100 - i * 0.5 for i in range(60)]
        buf = _make_buf(prices)
        result = macd_histogram(buf, fast=12, slow=26, signal=9, threshold=0.0)
        assert result.direction in ("short", "neutral")
        assert 0.0 <= result.strength <= 1.0


# ---------------------------------------------------------------------------
# bb_breakout
# ---------------------------------------------------------------------------

class TestBbBreakout:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 5)
        assert bb_breakout(buf, period=20).direction == "neutral"

    def test_upper_breakout(self):
        prices = [100.0] * 25 + [100 + i * 3 for i in range(1, 6)]
        buf = _make_buf(prices)
        result = bb_breakout(buf, period=20, stddev_mult=2.0)
        assert result.direction in ("long", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_lower_breakout(self):
        prices = [100.0] * 25 + [100 - i * 3 for i in range(1, 6)]
        buf = _make_buf(prices)
        result = bb_breakout(buf, period=20, stddev_mult=2.0)
        assert result.direction in ("short", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_inside_bands_neutral(self):
        prices = [100 + (i % 3 - 1) * 0.01 for i in range(30)]
        buf = _make_buf(prices)
        result = bb_breakout(buf, period=20, stddev_mult=2.0)
        assert result.direction == "neutral"


# ---------------------------------------------------------------------------
# bb_squeeze
# ---------------------------------------------------------------------------

class TestBbSqueeze:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 5)
        assert bb_squeeze(buf, period=20).direction == "neutral"

    def test_squeeze_detected(self):
        prices = [100.0 + i * 0.0001 for i in range(30)]
        buf = _make_buf(prices)
        result = bb_squeeze(buf, period=20, stddev_mult=2.0, squeeze_threshold=0.1)
        assert result.direction == "neutral"
        assert result.strength > 0.0

    def test_no_squeeze(self):
        prices = [100 + i * 2 for i in range(30)]
        buf = _make_buf(prices)
        result = bb_squeeze(buf, period=20, stddev_mult=2.0, squeeze_threshold=0.001)
        assert result.strength == 0.0


# ---------------------------------------------------------------------------
# stoch_rsi_cross
# ---------------------------------------------------------------------------

class TestStochRsiCross:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 10)
        assert stoch_rsi_cross(buf).direction == "neutral"

    def test_strength_bounded(self):
        prices = [100 + i * 0.2 + (i % 5) * 0.5 for i in range(100)]
        buf = _make_buf(prices)
        result = stoch_rsi_cross(buf, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3)
        assert 0.0 <= result.strength <= 1.0


# ---------------------------------------------------------------------------
# ict_structure
# ---------------------------------------------------------------------------

class TestIctStructure:
    def test_neutral_insufficient(self):
        buf = _make_buf([100] * 3)
        assert ict_structure(buf, lookback=10).direction == "neutral"

    def test_bullish_trend(self):
        prices = [100 + i * 0.5 for i in range(30)]
        buf = _make_buf(prices)
        result = ict_structure(buf, lookback=10)
        assert result.direction in ("long", "neutral")
        assert 0.0 <= result.strength <= 1.0

    def test_bearish_trend(self):
        prices = [200 - i * 0.5 for i in range(30)]
        buf = _make_buf(prices)
        result = ict_structure(buf, lookback=10)
        assert result.direction in ("short", "neutral")
        assert 0.0 <= result.strength <= 1.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_all_signals_registered(self):
        expected = {
            "ema_cross", "rsi_zone", "macd_cross", "macd_histogram",
            "bb_breakout", "bb_squeeze", "stoch_rsi_cross", "ict_structure",
        }
        assert set(SIGNAL_REGISTRY.keys()) == expected

    def test_validate_unknown_type(self):
        errs = validate_signal_params("nonexistent", {})
        assert len(errs) == 1
        assert "Unknown signal type" in errs[0]

    def test_validate_unknown_param(self):
        errs = validate_signal_params("ema_cross", {"bad_param": 5})
        assert len(errs) == 1
        assert "Unknown param" in errs[0]

    def test_validate_valid_params(self):
        errs = validate_signal_params("ema_cross", {"fast": 8, "slow": 21})
        assert errs == []

    def test_warmup_bars_ema_cross(self):
        assert warmup_bars_for_signal("ema_cross", {"fast": 50, "slow": 200}) == 201

    def test_warmup_bars_macd(self):
        assert warmup_bars_for_signal("macd_cross", {"fast": 12, "slow": 26, "signal": 9}) == 36

    def test_warmup_bars_stoch_rsi(self):
        wb = warmup_bars_for_signal("stoch_rsi_cross", {})
        assert wb > 30
