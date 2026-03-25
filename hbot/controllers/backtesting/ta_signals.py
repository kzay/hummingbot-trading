"""Stateless TA signal primitives for the ta_composite adapter.

Each primitive has signature ``(buf: PriceBuffer, **params) -> SignalResult``.
Primitives are registered in ``SIGNAL_REGISTRY`` for config-driven lookup.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal

from controllers.price_buffer import PriceBuffer

_ZERO = Decimal("0")


@dataclass(frozen=True)
class SignalResult:
    direction: Literal["long", "short", "neutral"]
    strength: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            object.__setattr__(
                self, "strength", max(0.0, min(1.0, self.strength)),
            )


_NEUTRAL = SignalResult("neutral", 0.0)


# ---------------------------------------------------------------------------
# Signal primitives
# ---------------------------------------------------------------------------

def ema_cross(buf: PriceBuffer, *, fast: int = 8, slow: int = 21) -> SignalResult:
    """Detect fast-EMA / slow-EMA crossover.

    Requires at least ``slow + 1`` bars to compare current vs previous state.
    Strength is proportional to the absolute EMA gap relative to price.
    """
    bars = buf.bars
    if len(bars) < slow + 1:
        return _NEUTRAL

    prev_buf_closes = [b.close for b in bars[:-1]]
    cur_fast = buf.ema(fast)
    cur_slow = buf.ema(slow)
    if cur_fast is None or cur_slow is None:
        return _NEUTRAL

    alpha_f = Decimal(2) / Decimal(fast + 1)
    alpha_s = Decimal(2) / Decimal(slow + 1)
    prev_fast = prev_buf_closes[0]
    prev_slow = prev_buf_closes[0]
    for c in prev_buf_closes[1:]:
        prev_fast = alpha_f * c + (Decimal(1) - alpha_f) * prev_fast
        prev_slow = alpha_s * c + (Decimal(1) - alpha_s) * prev_slow

    was_above = prev_fast > prev_slow
    was_equal = prev_fast == prev_slow
    is_above = cur_fast > cur_slow

    price = buf.latest_close()
    if price is None or price <= _ZERO:
        return _NEUTRAL

    gap = abs(cur_fast - cur_slow)
    strength = min(1.0, float(gap / price) * 100)

    if not was_above and is_above:
        return SignalResult("long", strength)
    if (was_above or was_equal) and not is_above and cur_fast != cur_slow:
        return SignalResult("short", strength)
    return _NEUTRAL


def rsi_zone(
    buf: PriceBuffer,
    *,
    period: int = 14,
    overbought: float = 70.0,
    oversold: float = 30.0,
) -> SignalResult:
    """Classify RSI into overbought / oversold / neutral zones."""
    rsi_val = buf.rsi(period)
    if rsi_val is None:
        return _NEUTRAL
    r = float(rsi_val)
    if r < oversold:
        strength = min(1.0, (oversold - r) / oversold) if oversold > 0 else 1.0
        return SignalResult("long", strength)
    if r > overbought:
        strength = min(1.0, (r - overbought) / (100.0 - overbought)) if overbought < 100 else 1.0
        return SignalResult("short", strength)
    return _NEUTRAL


def macd_cross(
    buf: PriceBuffer,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> SignalResult:
    """Detect MACD histogram sign change (line crossing signal)."""
    result = buf.macd(fast, slow, signal)
    if result is None:
        return _NEUTRAL
    _, _, histogram = result

    closes = buf.closes
    if len(closes) < max(fast, slow) + signal + 1:
        return _NEUTRAL

    prev_closes = closes[:-1]
    fa = 2.0 / (fast + 1)
    sa = 2.0 / (slow + 1)
    f_ema = float(prev_closes[0])
    s_ema = float(prev_closes[0])
    macd_series: list[float] = []
    for c in prev_closes:
        cf = float(c)
        f_ema = fa * cf + (1.0 - fa) * f_ema
        s_ema = sa * cf + (1.0 - sa) * s_ema
        macd_series.append(f_ema - s_ema)
    siga = 2.0 / (signal + 1)
    sig_e = macd_series[0]
    for v in macd_series[1:]:
        sig_e = siga * v + (1.0 - siga) * sig_e
    prev_hist = macd_series[-1] - sig_e

    cur_h = float(histogram)
    price = buf.latest_close()
    if price is None or price <= _ZERO:
        return _NEUTRAL
    strength = min(1.0, abs(cur_h) / float(price) * 100)

    if prev_hist <= 0 and cur_h > 0:
        return SignalResult("long", strength)
    if prev_hist >= 0 and cur_h < 0:
        return SignalResult("short", strength)
    return _NEUTRAL


def macd_histogram(
    buf: PriceBuffer,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    threshold: float = 0.0,
) -> SignalResult:
    """Detect strong MACD histogram momentum above threshold."""
    result = buf.macd(fast, slow, signal)
    if result is None:
        return _NEUTRAL
    _, _, hist = result
    h = float(hist)
    price = buf.latest_close()
    if price is None or price <= _ZERO:
        return _NEUTRAL
    norm = abs(h) / float(price) * 100
    if h > threshold:
        return SignalResult("long", min(1.0, norm))
    if h < -threshold:
        return SignalResult("short", min(1.0, norm))
    return _NEUTRAL


def bb_breakout(
    buf: PriceBuffer,
    *,
    period: int = 20,
    stddev_mult: float = 2.0,
) -> SignalResult:
    """Detect close price breaking outside Bollinger Bands."""
    bands = buf.bollinger_bands(period, Decimal(str(stddev_mult)))
    if bands is None:
        return _NEUTRAL
    lower, basis, upper = bands
    close = buf.latest_close()
    if close is None or basis <= _ZERO:
        return _NEUTRAL
    if close > upper:
        mag = float((close - upper) / basis)
        return SignalResult("long", min(1.0, mag * 100))
    if close < lower:
        mag = float((lower - close) / basis)
        return SignalResult("short", min(1.0, mag * 100))
    return _NEUTRAL


def bb_squeeze(
    buf: PriceBuffer,
    *,
    period: int = 20,
    stddev_mult: float = 2.0,
    squeeze_threshold: float = 0.02,
) -> SignalResult:
    """Detect narrow Bollinger bandwidth indicating imminent expansion."""
    bands = buf.bollinger_bands(period, Decimal(str(stddev_mult)))
    if bands is None:
        return _NEUTRAL
    lower, basis, upper = bands
    if basis <= _ZERO:
        return _NEUTRAL
    bandwidth = float((upper - lower) / basis)
    if bandwidth < squeeze_threshold:
        strength = min(1.0, 1.0 - bandwidth / squeeze_threshold)
        return SignalResult("neutral", strength)
    return _NEUTRAL


def stoch_rsi_cross(
    buf: PriceBuffer,
    *,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
    overbought: float = 80.0,
    oversold: float = 20.0,
) -> SignalResult:
    """Detect K/D crossover in extreme StochRSI zones.

    Uses the per-bar cache on PriceBuffer; for the *previous* bar value
    we recompute from closes[:-1] via the same algorithm as PriceBuffer.
    """
    cur = buf.stoch_rsi(rsi_period, stoch_period, k_smooth, d_smooth)
    if cur is None:
        return _NEUTRAL
    cur_k, cur_d = float(cur[0]), float(cur[1])

    closes = buf.closes
    min_bars = rsi_period + 1 + stoch_period + k_smooth + d_smooth - 2
    if len(closes) < min_bars + 1:
        return _NEUTRAL
    prev_closes = closes[:-1]

    prev_kd = _stoch_rsi_from_closes(prev_closes, rsi_period, stoch_period, k_smooth, d_smooth)
    if prev_kd is None:
        return _NEUTRAL
    prev_k, prev_d = prev_kd

    if prev_k <= prev_d and cur_k > cur_d and cur_k < oversold and cur_d < oversold:
        strength = min(1.0, (oversold - cur_k) / oversold) if oversold > 0 else 1.0
        return SignalResult("long", strength)
    if prev_k >= prev_d and cur_k < cur_d and cur_k > overbought and cur_d > overbought:
        strength = min(1.0, (cur_k - overbought) / (100.0 - overbought)) if overbought < 100 else 1.0
        return SignalResult("short", strength)
    return _NEUTRAL


def _stoch_rsi_from_closes(
    closes: list[Decimal],
    rsi_period: int,
    stoch_period: int,
    k_smooth: int,
    d_smooth: int,
) -> tuple[float, float] | None:
    """Replicate PriceBuffer.stoch_rsi logic on a plain close list."""
    n = len(closes)
    min_bars = rsi_period + 1 + stoch_period + k_smooth + d_smooth - 2
    if n < min_bars:
        return None
    rsi_series: list[float] = []
    for i in range(rsi_period + 1, n + 1):
        window = closes[i - rsi_period - 1: i]
        gains = 0.0
        losses = 0.0
        for j in range(1, len(window)):
            d = float(window[j]) - float(window[j - 1])
            if d > 0:
                gains += d
            elif d < 0:
                losses -= d
        ag = gains / rsi_period
        al = losses / rsi_period
        if al <= 0.0:
            rsi_series.append(100.0)
        else:
            rs = ag / al
            rsi_series.append(100.0 - 100.0 / (1.0 + rs))
    if len(rsi_series) < stoch_period:
        return None
    raw_k: list[float] = []
    for i in range(stoch_period - 1, len(rsi_series)):
        window = rsi_series[i - stoch_period + 1: i + 1]
        lo = min(window)
        hi = max(window)
        if hi == lo:
            raw_k.append(50.0)
        else:
            raw_k.append((rsi_series[i] - lo) / (hi - lo) * 100.0)
    if len(raw_k) < k_smooth:
        return None
    smoothed_k: list[float] = []
    for i in range(k_smooth - 1, len(raw_k)):
        smoothed_k.append(sum(raw_k[i - k_smooth + 1: i + 1]) / k_smooth)
    if len(smoothed_k) < d_smooth:
        return None
    d_vals: list[float] = []
    for i in range(d_smooth - 1, len(smoothed_k)):
        d_vals.append(sum(smoothed_k[i - d_smooth + 1: i + 1]) / d_smooth)
    return smoothed_k[-1], d_vals[-1]


def ict_structure(
    buf: PriceBuffer,
    *,
    lookback: int = 10,
) -> SignalResult:
    """Wrap ICT library structure detection for break-of-structure bias."""
    from controllers.common.ict.state import ICTConfig, ICTState

    bars = buf.bars
    if len(bars) < lookback + 2:
        return _NEUTRAL

    recent = bars[-lookback - 2:]
    ict = ICTState(ICTConfig(swing_length=max(3, lookback // 3)))
    for b in recent:
        ict.add_bar(b.open, b.high, b.low, b.close)

    trend = ict.trend
    if trend == 0:
        return _NEUTRAL
    strength = 0.5
    evt = ict.last_structure
    if evt is not None:
        price = buf.latest_close()
        if price and price > _ZERO:
            dist = abs(float(evt.level) - float(price)) / float(price)
            strength = min(1.0, 0.5 + dist * 10)
    if trend > 0:
        return SignalResult("long", strength)
    return SignalResult("short", strength)


# ---------------------------------------------------------------------------
# Signal registry
# ---------------------------------------------------------------------------

SignalFn = Callable[..., SignalResult]

SIGNAL_REGISTRY: dict[str, SignalFn] = {
    "ema_cross": ema_cross,
    "rsi_zone": rsi_zone,
    "macd_cross": macd_cross,
    "macd_histogram": macd_histogram,
    "bb_breakout": bb_breakout,
    "bb_squeeze": bb_squeeze,
    "stoch_rsi_cross": stoch_rsi_cross,
    "ict_structure": ict_structure,
}


def validate_signal_params(signal_type: str, params: dict[str, Any]) -> list[str]:
    """Validate params against the function signature. Returns error messages."""
    fn = SIGNAL_REGISTRY.get(signal_type)
    if fn is None:
        return [
            f"Unknown signal type {signal_type!r}. "
            f"Available: {sorted(SIGNAL_REGISTRY.keys())}"
        ]
    sig = inspect.signature(fn)
    errors: list[str] = []
    valid_params = {
        name
        for name, p in sig.parameters.items()
        if name != "buf" and p.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    }
    for key in params:
        if key not in valid_params:
            errors.append(
                f"Unknown param {key!r} for signal {signal_type!r}. "
                f"Valid: {sorted(valid_params)}"
            )
    return errors


def warmup_bars_for_signal(signal_type: str, params: dict[str, Any]) -> int:
    """Return the minimum number of bars a signal needs before it produces values."""
    if signal_type == "ema_cross":
        return max(params.get("fast", 8), params.get("slow", 21)) + 1
    if signal_type == "rsi_zone":
        return params.get("period", 14) + 2
    if signal_type in ("macd_cross", "macd_histogram"):
        return max(params.get("fast", 12), params.get("slow", 26)) + params.get("signal", 9) + 1
    if signal_type in ("bb_breakout", "bb_squeeze"):
        return params.get("period", 20) + 1
    if signal_type == "stoch_rsi_cross":
        rp = params.get("rsi_period", 14)
        sp = params.get("stoch_period", 14)
        ks = params.get("k_smooth", 3)
        ds = params.get("d_smooth", 3)
        return rp + 1 + sp + ks + ds - 2 + 1
    if signal_type == "ict_structure":
        return params.get("lookback", 10) + 3
    return 30
