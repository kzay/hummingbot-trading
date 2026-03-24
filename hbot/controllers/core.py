"""Shared runtime primitives for the v2.4 controller family.

Houses data classes and utility functions imported by multiple controller
sub-modules.  Extracted from the legacy main runtime module to break circular
imports between regime_detector, spread_engine, risk_policy, and the main
controller.

Canonical import path: ``controllers.runtime.runtime_types``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def clip(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Clamp *value* to the inclusive range [low, high].

    NaN/Inf inputs are clamped to *low* (fail-safe).
    """
    if value.is_nan() or value.is_infinite():
        return low
    return min(high, max(low, value))


@dataclass(frozen=True)
class RegimeSpec:
    spread_min: Decimal
    spread_max: Decimal
    levels_min: int
    levels_max: int
    refresh_s: int
    target_base_pct: Decimal
    quote_size_pct_min: Decimal
    quote_size_pct_max: Decimal
    one_sided: str  # "off" | "buy_only" | "sell_only"
    fill_factor: Decimal = Decimal("0.40")

    @property
    def quote_size_pct(self) -> Decimal:
        """Single effective sizing pct — average of min/max for backward compat."""
        return (self.quote_size_pct_min + self.quote_size_pct_max) / Decimal("2")


@dataclass
class RuntimeLevelState:
    buy_spreads: list[Decimal]
    sell_spreads: list[Decimal]
    buy_amounts_pct: list[Decimal]
    sell_amounts_pct: list[Decimal]
    total_amount_quote: Decimal
    executor_refresh_time: int
    cooldown_time: int


@dataclass(frozen=True)
class QuoteGeometry:
    base_spread_pct: Decimal
    spread_floor_pct: Decimal
    reservation_price_adjustment_pct: Decimal
    inventory_urgency: Decimal
    inventory_skew: Decimal
    alpha_skew: Decimal


@dataclass(frozen=True)
class SpreadEdgeState:
    band_pct: Decimal
    spread_pct: Decimal
    net_edge: Decimal
    skew: Decimal
    adverse_drift: Decimal
    smooth_drift: Decimal
    drift_spread_mult: Decimal
    turnover_x: Decimal
    min_edge_threshold: Decimal
    edge_resume_threshold: Decimal
    fill_factor: Decimal
    quote_geometry: QuoteGeometry


@dataclass(frozen=True)
class MarketConditions:
    is_high_vol: bool
    bid_p: Decimal
    ask_p: Decimal
    market_spread_pct: Decimal
    best_bid_size: Decimal
    best_ask_size: Decimal
    connector_ready: bool
    order_book_stale: bool
    market_spread_too_small: bool
    side_spread_floor: Decimal
