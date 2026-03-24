"""Pure signal functions for the bot7 pullback strategy.

Every function here is stateless: takes indicator values in, returns a
decision out.  No ``self``, no state, no Hummingbot / runtime imports.
Both the production controller and the backtest adapter import these
to guarantee identical signal logic.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from decimal import Decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")


def _clip(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ── Pullback zone ────────────────────────────────────────────────────────


def effective_zone_pct(
    mid: Decimal,
    atr: Decimal | None,
    zone_pct: Decimal = Decimal("0.0015"),
    zone_atr_mult: Decimal = Decimal("0.25"),
) -> Decimal:
    """Adaptive pullback zone width: max(static floor, ATR-derived)."""
    if atr is None or mid <= _ZERO:
        return zone_pct
    atr_pct = (atr * zone_atr_mult) / mid
    return max(zone_pct, atr_pct)


def detect_pullback_zone(
    mid: Decimal,
    bb_lower: Decimal,
    bb_basis: Decimal,
    bb_upper: Decimal,
    atr: Decimal | None = None,
    zone_pct: Decimal = Decimal("0.0015"),
    band_floor_pct: Decimal = Decimal("0.0010"),
    zone_atr_mult: Decimal = Decimal("0.25"),
) -> tuple[bool, bool]:
    """Check if price is in the pullback zone near BB basis.

    Returns ``(long_zone, short_zone)``.
    """
    if mid <= _ZERO or bb_basis <= _ZERO:
        return False, False
    zpct = effective_zone_pct(mid, atr, zone_pct, zone_atr_mult)
    long_ceil = max(_ZERO, bb_basis * (_ONE + zpct))
    long_floor = max(_ZERO, bb_lower * (_ONE + band_floor_pct))
    short_floor = max(_ZERO, bb_basis * (_ONE - zpct))
    short_ceil = max(_ZERO, bb_upper * (_ONE - band_floor_pct))
    long_zone = long_floor <= mid <= long_ceil
    short_zone = short_floor <= mid <= short_ceil
    return long_zone, short_zone


# ── Gate checks ──────────────────────────────────────────────────────────


def check_rsi_gate(
    rsi: Decimal,
    side: str,
    rsi_long_min: Decimal = Decimal("35"),
    rsi_long_max: Decimal = Decimal("55"),
    rsi_short_min: Decimal = Decimal("45"),
    rsi_short_max: Decimal = Decimal("65"),
) -> bool:
    """Return True if RSI is within the entry window for *side*."""
    if side == "buy":
        return rsi_long_min <= rsi <= rsi_long_max
    elif side == "sell":
        return rsi_short_min <= rsi <= rsi_short_max
    return False


def check_adx_gate(
    adx: Decimal,
    adx_min: Decimal = Decimal("22"),
    adx_max: Decimal = Decimal("40"),
) -> bool:
    return adx_min <= adx <= adx_max


# ── Trend quality ────────────────────────────────────────────────────────


def check_basis_slope(
    closes: Sequence[Decimal],
    side: str,
    bb_period: int = 20,
    lookback: int = 5,
    min_slope_pct: Decimal = Decimal("0.0002"),
) -> tuple[bool, Decimal]:
    """Check BB basis (SMA) slope confirms the trade direction.

    *closes* should be the recent bar close prices ordered oldest-to-newest.
    Returns ``(gate_passed, slope_pct)``.
    """
    needed = bb_period + lookback
    if len(closes) < needed:
        return True, _ZERO
    current = closes[-bb_period:]
    past = closes[-(bb_period + lookback):-lookback]
    current_sma = sum(current, _ZERO) / Decimal(len(current))
    past_sma = sum(past, _ZERO) / Decimal(len(past))
    if past_sma <= _ZERO:
        return True, _ZERO
    slope_pct = (current_sma - past_sma) / past_sma
    if side == "buy":
        return slope_pct >= min_slope_pct, slope_pct
    elif side == "sell":
        return slope_pct <= -min_slope_pct, slope_pct
    return True, slope_pct


def check_trend_sma(
    mid: Decimal,
    sma_val: Decimal | None,
    side: str,
) -> bool:
    """Check mid is on correct side of the long-period SMA."""
    if sma_val is None:
        return True
    if side == "buy":
        return mid > sma_val
    elif side == "sell":
        return mid < sma_val
    return True


def aggregate_close_series(
    closes: Sequence[Decimal],
    factor: int,
) -> list[Decimal]:
    """Downsample 1m closes into an N-minute close series."""
    if factor <= 1:
        return list(closes)
    return [closes[idx] for idx in range(factor - 1, len(closes), factor)]


def check_htf_trend(
    closes: Sequence[Decimal],
    side: str,
    factor: int = 5,
    sma_period: int = 12,
    slope_bars: int = 3,
    min_slope_pct: Decimal = Decimal("0.0005"),
) -> tuple[bool, Decimal, Decimal | None]:
    """Check higher-timeframe close is aligned with SMA and slope.

    Returns ``(passed, slope_pct, htf_sma)``.
    """
    htf = aggregate_close_series(closes, factor)
    needed = max(sma_period + slope_bars, sma_period + 1)
    if len(htf) < needed:
        return True, _ZERO, None
    current = htf[-sma_period:]
    past = htf[-(sma_period + slope_bars):-slope_bars]
    htf_sma = sum(current, _ZERO) / Decimal(len(current))
    past_sma = sum(past, _ZERO) / Decimal(len(past))
    if htf_sma <= _ZERO or past_sma <= _ZERO:
        return True, _ZERO, htf_sma
    htf_close = htf[-1]
    slope_pct = (htf_sma - past_sma) / past_sma
    if side == "buy":
        return htf_close > htf_sma and slope_pct >= min_slope_pct, slope_pct, htf_sma
    if side == "sell":
        return htf_close < htf_sma and slope_pct <= -min_slope_pct, slope_pct, htf_sma
    return True, slope_pct, htf_sma


# ── Dynamic barriers ────────────────────────────────────────────────────


def compute_dynamic_barriers(
    mid: Decimal,
    atr: Decimal | None,
    sl_mult: Decimal = Decimal("1.5"),
    tp_mult: Decimal = Decimal("3.0"),
    sl_floor: Decimal = Decimal("0.003"),
    sl_cap: Decimal = Decimal("0.01"),
    tp_floor: Decimal = Decimal("0.006"),
    tp_cap: Decimal = Decimal("0.02"),
    probe_mode: bool = False,
    probe_sl_mult: Decimal = Decimal("0.75"),
) -> tuple[Decimal, Decimal]:
    """ATR-scaled SL/TP percentages, clamped to floor/cap.

    Returns ``(sl_pct, tp_pct)``.
    """
    if atr is None or mid <= _ZERO:
        return sl_floor, tp_floor
    sl_raw = sl_mult * atr / mid
    tp_raw = tp_mult * atr / mid
    if probe_mode:
        sl_raw = sl_raw * probe_sl_mult
    sl_pct = _clip(sl_raw, sl_floor, sl_cap)
    tp_pct = _clip(tp_raw, tp_floor, tp_cap)
    min_tp = sl_pct * Decimal("1.5")
    if tp_pct < min_tp:
        tp_pct = min_tp
    return sl_pct, tp_pct


# ── Grid sizing ──────────────────────────────────────────────────────────


def compute_grid_levels(
    signal_score: Decimal,
    max_legs: int = 3,
    probe_mode: bool = False,
    probe_legs: int = 1,
) -> int:
    """Compute number of grid levels from signal score."""
    if signal_score <= _ZERO:
        return 0
    levels = min(
        max_legs,
        max(1, int((signal_score * Decimal(max_legs)).to_integral_value(rounding="ROUND_CEILING"))),
    )
    if probe_mode:
        levels = min(levels, max(1, probe_legs))
    return levels


def compute_entry_spreads(
    mid: Decimal,
    bb_basis: Decimal,
    side: str,
    levels: int,
    spacing_pct: Decimal,
    entry_offset_pct: Decimal = Decimal("0.001"),
    floor_spacing: Decimal = Decimal("0.0015"),
    limit_entry: bool = True,
) -> list[Decimal]:
    """Compute the spread offsets for limit entry orders.

    Returns a list of ``Decimal`` spread percentages, one per level.
    """
    if levels <= 0 or side == "off":
        return []
    if limit_entry and bb_basis > _ZERO and mid > _ZERO:
        if side == "buy":
            target = bb_basis * (_ONE - entry_offset_pct)
            first = max((mid - target) / mid, floor_spacing)
        else:
            target = bb_basis * (_ONE + entry_offset_pct)
            first = max((target - mid) / mid, floor_spacing)
    else:
        first = spacing_pct
    spreads = [first] + [spacing_pct * Decimal(level + 1) for level in range(1, levels)]
    return spreads


# ── Session filter ───────────────────────────────────────────────────────


def in_quality_session(
    now_ts: float,
    quality_hours_utc: str = "1-4,8-16,20-23",
    session_filter_enabled: bool = True,
    low_quality_size_mult: Decimal = Decimal("0.5"),
) -> tuple[bool, Decimal]:
    """Check if current time is within quality trading hours.

    Returns ``(in_quality, size_multiplier)``.
    """
    if not session_filter_enabled:
        return True, _ONE
    utc_hour = _dt.datetime.fromtimestamp(now_ts, tz=_dt.UTC).hour
    in_quality = False
    for segment in quality_hours_utc.split(","):
        segment = segment.strip()
        if not segment:
            continue
        if "-" in segment:
            parts = segment.split("-", 1)
            try:
                lo, hi = int(parts[0]), int(parts[1])
                if lo <= utc_hour <= hi:
                    in_quality = True
                    break
            except (ValueError, IndexError):
                continue
        else:
            try:
                if utc_hour == int(segment):
                    in_quality = True
                    break
            except ValueError:
                continue
    if in_quality:
        return True, _ONE
    return False, low_quality_size_mult


# ── Funding bias ─────────────────────────────────────────────────────────


def funding_bias(
    rate: Decimal,
    long_threshold: Decimal = Decimal("-0.0003"),
    short_threshold: Decimal = Decimal("0.0003"),
) -> str:
    """Classify funding rate into ``"long"`` / ``"short"`` / ``"neutral"``."""
    if rate <= long_threshold:
        return "long"
    if rate >= short_threshold:
        return "short"
    return "neutral"


# ── Trend confidence ─────────────────────────────────────────────────────


def compute_trend_confidence(
    side: str,
    adx: Decimal,
    basis_slope: Decimal,
    mid: Decimal,
    trend_sma: Decimal | None,
    adx_min: Decimal = Decimal("22"),
    adx_max: Decimal = Decimal("40"),
    min_slope_pct: Decimal = Decimal("0.0002"),
    confidence_min_mult: Decimal = Decimal("0.5"),
) -> Decimal:
    """Compute a [0, 1] trend confidence score from ADX, slope, SMA distance."""
    adx_range = adx_max - adx_min
    adx_norm = _clip((adx - adx_min) / adx_range, _ZERO, _ONE) if adx_range > _ZERO else _ZERO
    abs_slope = abs(basis_slope)
    slope_norm = (
        _clip((abs_slope - min_slope_pct) / (min_slope_pct * Decimal("2")), _ZERO, _ONE)
        if min_slope_pct > _ZERO
        else _ZERO
    )
    sma_norm = _ZERO
    if trend_sma is not None and trend_sma > _ZERO and mid > _ZERO:
        sma_dist = abs(mid - trend_sma) / mid
        sma_norm = _clip(sma_dist / Decimal("0.005"), _ZERO, _ONE)
    score = (adx_norm + slope_norm + sma_norm) / Decimal("3")
    return confidence_min_mult + score * (_ONE - confidence_min_mult)


# ── Adaptive grid spacing ───────────────────────────────────────────────


def compute_grid_spacing(
    bb_upper: Decimal,
    bb_lower: Decimal,
    mid: Decimal,
    atr: Decimal | None,
    bb_fraction: Decimal = Decimal("0.12"),
    atr_mult: Decimal = Decimal("0.50"),
    floor_pct: Decimal = Decimal("0.0015"),
    cap_pct: Decimal = Decimal("0.0100"),
) -> Decimal:
    """Compute adaptive grid spacing from BB width and ATR."""
    bb_width = (bb_upper - bb_lower) / mid if mid > _ZERO else _ZERO
    bb_spacing = bb_width * bb_fraction
    if atr is not None and mid > _ZERO:
        atr_spacing = atr * atr_mult / mid
        raw_spacing = min(bb_spacing, atr_spacing)
    else:
        raw_spacing = bb_spacing
    return _clip(raw_spacing if raw_spacing > _ZERO else _ZERO, floor_pct, cap_pct)


# ── Signal score ─────────────────────────────────────────────────────────


def compute_signal_score(
    side: str,
    absorption_long: bool,
    absorption_short: bool,
    delta_trap_long: bool,
    delta_trap_short: bool,
    depth_imbalance: Decimal,
    recent_delta: Decimal,
    funding_bias_str: str,
    imbalance_threshold: Decimal = Decimal("0.20"),
) -> Decimal:
    """Compute signal score from independent confirmation signals.

    Returns a value in [0, 1].
    """
    if side == "buy":
        secondary = depth_imbalance >= imbalance_threshold and recent_delta >= _ZERO
        funding_ok = funding_bias_str in ("long", "neutral")
        components = sum(1 for f in (absorption_long, delta_trap_long, secondary, funding_ok) if f)
    elif side == "sell":
        secondary = depth_imbalance <= -imbalance_threshold and recent_delta <= _ZERO
        funding_ok = funding_bias_str in ("short", "neutral")
        components = sum(1 for f in (absorption_short, delta_trap_short, secondary, funding_ok) if f)
    else:
        return _ZERO
    return _clip(Decimal(components) / Decimal("4"), _ZERO, _ONE)


# ── Position sizing ─────────────────────────────────────────────────────


def compute_target_exposure(
    side: str,
    grid_levels: int,
    per_leg_risk_pct: Decimal = Decimal("0.008"),
    total_cap_pct: Decimal = Decimal("0.025"),
    funding_risk_scale: Decimal = _ONE,
    probe_mode: bool = False,
    probe_size_mult: Decimal = Decimal("0.50"),
    hedge_ratio: Decimal = Decimal("0.30"),
) -> tuple[Decimal, Decimal]:
    """Compute target net base pct and hedge target.

    Returns ``(target_net_base_pct, hedge_target_base_pct)``.
    """
    target_abs = _clip(
        per_leg_risk_pct * Decimal(grid_levels) * funding_risk_scale,
        _ZERO,
        total_cap_pct,
    )
    if probe_mode:
        target_abs *= _clip(probe_size_mult, _ZERO, _ONE)
    target_net = target_abs if side == "buy" else (-target_abs if side == "sell" else _ZERO)
    hedge_target = abs(target_net) * hedge_ratio
    return target_net, hedge_target


# ── Multi-mode signal functions (Enhanced Pullback v2) ──────────────────


def detect_momentum_breakout(
    mid: Decimal,
    bb_upper: Decimal,
    bb_lower: Decimal,
    adx: Decimal,
    rsi: Decimal,
    atr: Decimal | None,
    adx_min: Decimal = Decimal("25"),
    rsi_long_threshold: Decimal = Decimal("55"),
    rsi_short_threshold: Decimal = Decimal("45"),
    breakout_atr_mult: Decimal = Decimal("0.3"),
) -> tuple[str, Decimal]:
    """Detect momentum breakout beyond Bollinger Bands.

    Returns ``(side, strength)`` where side is "buy"/"sell"/"off" and
    strength is [0, 1] representing how far beyond the band.
    """
    if mid <= _ZERO or bb_upper <= _ZERO or bb_lower <= _ZERO:
        return "off", _ZERO
    if adx < adx_min:
        return "off", _ZERO

    bb_width = bb_upper - bb_lower
    if bb_width <= _ZERO:
        return "off", _ZERO

    if mid > bb_upper and rsi > rsi_long_threshold:
        excess = (mid - bb_upper) / bb_width
        strength = _clip(excess, _ZERO, _ONE)
        return "buy", strength

    if mid < bb_lower and rsi < rsi_short_threshold:
        excess = (bb_lower - mid) / bb_width
        strength = _clip(excess, _ZERO, _ONE)
        return "sell", strength

    return "off", _ZERO


def detect_mean_reversion(
    mid: Decimal,
    bb_upper: Decimal,
    bb_lower: Decimal,
    bb_basis: Decimal,
    rsi: Decimal,
    adx: Decimal,
    adx_max: Decimal = Decimal("25"),
    rsi_oversold: Decimal = Decimal("30"),
    rsi_overbought: Decimal = Decimal("70"),
    band_touch_pct: Decimal = Decimal("0.001"),
) -> tuple[str, Decimal]:
    """Detect mean-reversion opportunity at BB extremes in low-trend regimes.

    Only triggers when ADX is *below* threshold (choppy/ranging market).
    Returns ``(side, strength)``.
    """
    if mid <= _ZERO or bb_basis <= _ZERO:
        return "off", _ZERO
    if adx > adx_max:
        return "off", _ZERO

    bb_width = bb_upper - bb_lower
    if bb_width <= _ZERO:
        return "off", _ZERO

    lower_zone = bb_lower * (_ONE + band_touch_pct)
    upper_zone = bb_upper * (_ONE - band_touch_pct)

    if mid <= lower_zone and rsi <= rsi_oversold:
        dist = (lower_zone - mid) / bb_width
        strength = _clip(Decimal("0.5") + dist, _ZERO, _ONE)
        return "buy", strength

    if mid >= upper_zone and rsi >= rsi_overbought:
        dist = (mid - upper_zone) / bb_width
        strength = _clip(Decimal("0.5") + dist, _ZERO, _ONE)
        return "sell", strength

    return "off", _ZERO


def compute_volatility_sizing_mult(
    atr: Decimal | None,
    mid: Decimal,
    target_vol_pct: Decimal = Decimal("0.005"),
    min_mult: Decimal = Decimal("0.3"),
    max_mult: Decimal = Decimal("2.0"),
) -> Decimal:
    """Inverse-volatility position sizing: size proportional to 1/realized_vol.

    When ATR% is low -> bigger positions; when ATR% is high -> smaller.
    Normalized to 1.0 at ``target_vol_pct``.
    """
    if atr is None or mid <= _ZERO or atr <= _ZERO:
        return _ONE
    atr_pct = atr / mid
    if atr_pct <= _ZERO:
        return max_mult
    raw = target_vol_pct / atr_pct
    return _clip(raw, min_mult, max_mult)


def compute_rsi_momentum_score(
    rsi: Decimal,
    side: str,
) -> Decimal:
    """Score [0, 1] for how strongly RSI confirms the signal direction."""
    if side == "buy":
        if rsi < Decimal("30"):
            return _ONE
        if rsi < Decimal("50"):
            return (_clip(Decimal("50") - rsi, _ZERO, Decimal("20"))) / Decimal("20")
        return _ZERO
    elif side == "sell":
        if rsi > Decimal("70"):
            return _ONE
        if rsi > Decimal("50"):
            return (_clip(rsi - Decimal("50"), _ZERO, Decimal("20"))) / Decimal("20")
        return _ZERO
    return _ZERO


def compute_multi_signal_score(
    pullback_active: bool,
    momentum_active: bool,
    momentum_strength: Decimal,
    meanrev_active: bool,
    meanrev_strength: Decimal,
    adx_norm: Decimal,
    rsi_score: Decimal,
    sma_confirms: bool,
    slope_confirms: bool,
) -> Decimal:
    """Compute an aggregate signal score from multiple independent signals.

    Returns [0, 1] — higher = stronger conviction.
    """
    score = _ZERO
    weights = _ZERO

    if pullback_active:
        pb_base = Decimal("0.6")
        if sma_confirms:
            pb_base += Decimal("0.15")
        if slope_confirms:
            pb_base += Decimal("0.15")
        pb_base += adx_norm * Decimal("0.1")
        score += pb_base * Decimal("3")
        weights += Decimal("3")

    if momentum_active:
        mo_base = Decimal("0.4") + momentum_strength * Decimal("0.4") + rsi_score * Decimal("0.2")
        score += mo_base * Decimal("2")
        weights += Decimal("2")

    if meanrev_active:
        mr_base = Decimal("0.5") + meanrev_strength * Decimal("0.3") + rsi_score * Decimal("0.2")
        score += mr_base * Decimal("2")
        weights += Decimal("2")

    if weights <= _ZERO:
        return _ZERO

    return _clip(score / weights, _ZERO, _ONE)
