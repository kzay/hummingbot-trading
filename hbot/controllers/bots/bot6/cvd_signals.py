"""Bot6 CVD Divergence — pure signal functions.

Stateless signal computation for spot-vs-perp CVD divergence.
No framework imports — only standard library and decimal.
"""

from __future__ import annotations

from decimal import Decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")


def _clip(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def detect_trend(
    *,
    sma_fast: Decimal,
    sma_slow: Decimal,
    adx: Decimal,
    adx_threshold: Decimal = Decimal("18"),
    epsilon: Decimal = Decimal("0.0001"),
) -> str:
    """Detect trend direction from SMA crossover + ADX confirmation.

    Returns: 'long', 'short', or 'flat'
    """
    if adx < adx_threshold:
        return "flat"

    mid_approx = (sma_fast + sma_slow) / 2 if sma_slow > _ZERO else sma_fast
    if mid_approx <= _ZERO:
        return "flat"

    displacement = (sma_fast - sma_slow) / mid_approx
    if displacement > epsilon:
        return "long"
    elif displacement < -epsilon:
        return "short"
    return "flat"


def score_cvd_divergence(
    *,
    futures_cvd: Decimal,
    spot_cvd: Decimal,
    stacked_buy_count: int = 0,
    stacked_sell_count: int = 0,
    delta_spike_ratio: Decimal = _ZERO,
    trend_direction: str = "flat",
    adx: Decimal = _ZERO,
    adx_threshold: Decimal = Decimal("18"),
    divergence_threshold_pct: Decimal = Decimal("0.15"),
) -> tuple[int, int, Decimal]:
    """Score long and short conviction from CVD + trade features.

    Returns: (long_score, short_score, cvd_divergence_ratio)
    """
    long_score = 0
    short_score = 0

    # CVD divergence
    cvd_sum = abs(futures_cvd) + abs(spot_cvd)
    if cvd_sum > _ZERO:
        cvd_divergence_ratio = (futures_cvd - spot_cvd) / cvd_sum
    else:
        cvd_divergence_ratio = _ZERO

    if cvd_divergence_ratio > divergence_threshold_pct:
        long_score += 3
    elif cvd_divergence_ratio < -divergence_threshold_pct:
        short_score += 3

    # Stacked imbalance
    if stacked_buy_count >= 3:
        long_score += 1
    if stacked_sell_count >= 3:
        short_score += 1

    # Delta spike
    if delta_spike_ratio > Decimal("1.5"):
        long_score += 1
    elif delta_spike_ratio < Decimal("-1.5"):
        short_score += 1

    # Trend alignment
    if trend_direction == "long":
        long_score += 2
    elif trend_direction == "short":
        short_score += 2

    # ADX strength bonus
    if adx >= adx_threshold:
        if long_score > short_score:
            long_score += 1
        elif short_score > long_score:
            short_score += 1

    return long_score, short_score, cvd_divergence_ratio


def compute_dynamic_size_mult(
    *,
    divergence_strength: Decimal,
    floor_mult: Decimal = Decimal("0.80"),
    cap_mult: Decimal = Decimal("1.50"),
) -> Decimal:
    """Compute dynamic position size multiplier from divergence strength."""
    strength = _clip(divergence_strength, _ZERO, _ONE)
    return floor_mult + strength * (cap_mult - floor_mult)


def classify_funding_bias(
    funding_rate: Decimal,
    long_max: Decimal = Decimal("0.0005"),
    short_min: Decimal = Decimal("-0.0005"),
) -> str:
    """Classify funding rate bias."""
    if funding_rate > long_max:
        return "short"  # High funding favors shorts
    elif funding_rate < short_min:
        return "long"  # Negative funding favors longs
    return "neutral"


__all__ = [
    "classify_funding_bias",
    "compute_dynamic_size_mult",
    "detect_trend",
    "score_cvd_divergence",
]
