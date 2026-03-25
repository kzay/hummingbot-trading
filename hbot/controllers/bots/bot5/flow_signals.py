"""Bot5 IFT/JOTA — pure flow signal functions.

Stateless signal computation for institutional flow detection.
No framework imports — only standard library and decimal.
"""

from __future__ import annotations

from decimal import Decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NEG_ONE = Decimal("-1")
_FLOW_EPS = Decimal("0.05")


def _clip(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def compute_flow_conviction(
    *,
    imbalance: Decimal,
    mid: Decimal,
    ema_val: Decimal,
    imbalance_threshold: Decimal = Decimal("0.18"),
    trend_threshold_pct: Decimal = Decimal("0.0008"),
) -> tuple[Decimal, Decimal, str, bool]:
    """Compute flow conviction from OB imbalance and trend displacement.

    Returns:
        (conviction, signed_signal, direction, aligned)
    """
    imbalance = _clip(imbalance, _NEG_ONE, _ONE)
    imbalance_threshold = max(Decimal("0.05"), imbalance_threshold)
    trend_threshold = max(Decimal("0.0001"), trend_threshold_pct)

    # Trend displacement
    if ema_val <= _ZERO or mid <= _ZERO:
        trend_displacement_pct = _ZERO
    else:
        trend_displacement_pct = (mid - ema_val) / ema_val

    trend_signal = _clip(trend_displacement_pct / trend_threshold, _NEG_ONE, _ONE)

    # Component strengths
    imbalance_strength = _clip(abs(imbalance) / imbalance_threshold, _ZERO, _ONE)
    trend_strength = _clip(abs(trend_displacement_pct) / trend_threshold, _ZERO, _ONE)

    # Alignment check
    aligned = (
        abs(imbalance) > _FLOW_EPS
        and abs(trend_signal) > _FLOW_EPS
        and (imbalance > _ZERO) == (trend_signal > _ZERO)
    )

    # Conviction: weighted sum
    conviction = _clip(
        imbalance_strength * Decimal("0.55")
        + trend_strength * Decimal("0.35")
        + (Decimal("0.10") if aligned else _ZERO),
        _ZERO,
        _ONE,
    )

    # Signed signal for direction
    signed_signal = _clip(
        imbalance * Decimal("0.65") + trend_signal * Decimal("0.35"),
        _NEG_ONE,
        _ONE,
    )

    # Direction
    if signed_signal >= _FLOW_EPS:
        direction = "buy"
    elif signed_signal <= -_FLOW_EPS:
        direction = "sell"
    else:
        direction = "off"

    return conviction, signed_signal, direction, aligned


def check_bias_active(
    *,
    direction: str,
    conviction: Decimal,
    bias_threshold: Decimal = Decimal("0.55"),
    selective_blocked: bool = False,
    edge_blocked: bool = False,
    high_vol_locked: bool = False,
) -> bool:
    """Check if flow bias should be active."""
    threshold = _clip(bias_threshold, Decimal("0.25"), _ONE)
    return (
        direction != "off"
        and conviction >= threshold
        and not selective_blocked
        and not edge_blocked
        and not high_vol_locked
    )


def check_directional_allowed(
    *,
    bias_active: bool,
    conviction: Decimal,
    direction: str,
    regime_name: str,
    directional_threshold: Decimal = Decimal("0.75"),
    bias_threshold: Decimal = Decimal("0.55"),
) -> bool:
    """Check if full directional mode is allowed."""
    threshold = _clip(directional_threshold, bias_threshold, _ONE)
    directional_regime = regime_name in ("up", "down", "neutral_low_vol")
    regime_aligned = not (
        (regime_name == "up" and direction == "sell")
        or (regime_name == "down" and direction == "buy")
    )
    return (
        bias_active
        and directional_regime
        and regime_aligned
        and conviction >= threshold
    )


def compute_target_net_base_pct(
    *,
    direction: str,
    conviction: Decimal,
    bias_active: bool,
    is_perp: bool,
    target_base_pct: Decimal = Decimal("0.08"),
    max_base_pct: Decimal = Decimal("0.50"),
) -> Decimal:
    """Compute signed target net base pct."""
    if not is_perp or not bias_active:
        return _ZERO
    target_abs = _clip(target_base_pct * conviction, _ZERO, max_base_pct)
    return target_abs if direction == "buy" else -target_abs


__all__ = [
    "check_bias_active",
    "check_directional_allowed",
    "compute_flow_conviction",
    "compute_target_net_base_pct",
]
