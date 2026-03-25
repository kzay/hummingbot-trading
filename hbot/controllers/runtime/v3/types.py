"""Immutable snapshot types for the v3 trading desk.

Every type here is a frozen dataclass — strategies receive these as
read-only views of market state.  The KernelDataSurface assembles them
once per tick from the existing kernel internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


_ZERO = Decimal("0")


# ── Indicator snapshot ───────────────────────────────────────────────

@dataclass(frozen=True)
class IndicatorSnapshot:
    """Pre-computed technical indicators from PriceBuffer."""

    ema: dict[int, Decimal] = field(default_factory=dict)
    """EMA values keyed by period (e.g. {20: Decimal("65123.4")})."""

    atr: dict[int, Decimal] = field(default_factory=dict)
    """ATR values keyed by period."""

    rsi: dict[int, Decimal] = field(default_factory=dict)
    """RSI values keyed by period."""

    adx: dict[int, Decimal] = field(default_factory=dict)
    """ADX values keyed by period."""

    bb_lower: Decimal = _ZERO
    bb_basis: Decimal = _ZERO
    bb_upper: Decimal = _ZERO
    bb_period: int = 20

    macd_line: Decimal = _ZERO
    macd_signal: Decimal = _ZERO
    macd_histogram: Decimal = _ZERO

    band_pct: Decimal = _ZERO
    """Volatility band as ATR / close — used for regime detection."""

    bars_available: int = 0
    """Number of bars in PriceBuffer (for warmup checks)."""


# ── Order book snapshot ──────────────────────────────────────────────

@dataclass(frozen=True)
class OrderBookSnapshot:
    """L1 + depth snapshot of the order book."""

    best_bid: Decimal = _ZERO
    best_ask: Decimal = _ZERO
    spread_pct: Decimal = _ZERO
    best_bid_size: Decimal = _ZERO
    best_ask_size: Decimal = _ZERO
    imbalance: Decimal = _ZERO
    """Bid/ask depth imbalance ratio in [-1, 1]."""

    depth_bids: tuple[tuple[Decimal, Decimal], ...] = ()
    """Order book bid levels as (price, size) tuples."""

    depth_asks: tuple[tuple[Decimal, Decimal], ...] = ()
    """Order book ask levels as (price, size) tuples."""

    stale: bool = False
    """True if order book data is considered stale."""


# ── Position snapshot ────────────────────────────────────────────────

@dataclass(frozen=True)
class PositionSnapshot:
    """Current position state."""

    base_amount: Decimal = _ZERO
    quote_balance: Decimal = _ZERO
    net_base_pct: Decimal = _ZERO
    gross_base_pct: Decimal = _ZERO
    avg_entry_price: Decimal = _ZERO
    is_perp: bool = False
    leverage: int = 1


# ── Equity snapshot ──────────────────────────────────────────────────

@dataclass(frozen=True)
class EquitySnapshot:
    """Equity and P&L metrics."""

    equity_quote: Decimal = _ZERO
    daily_open_equity: Decimal = _ZERO
    daily_peak_equity: Decimal = _ZERO
    daily_pnl_quote: Decimal = _ZERO
    daily_loss_pct: Decimal = _ZERO
    max_drawdown_pct: Decimal = _ZERO
    daily_turnover_x: Decimal = _ZERO


# ── Trade flow snapshot ──────────────────────────────────────────────

@dataclass(frozen=True)
class TradeFlowSnapshot:
    """Recent trade flow data for microstructure analysis."""

    cvd: Decimal = _ZERO
    """Cumulative volume delta."""

    delta_volume: Decimal = _ZERO
    recent_delta: Decimal = _ZERO
    absorption_long: bool = False
    absorption_short: bool = False
    delta_trap_long: bool = False
    delta_trap_short: bool = False
    stacked_buy_count: int = 0
    stacked_sell_count: int = 0
    delta_spike_ratio: Decimal = _ZERO
    trade_count: int = 0
    trade_age_ms: int = 0
    stale: bool = False


# ── Regime snapshot ──────────────────────────────────────────────────

@dataclass(frozen=True)
class RegimeSnapshot:
    """Detected market regime."""

    name: str = "neutral_low_vol"
    band_pct: Decimal = _ZERO
    ema_value: Decimal = _ZERO
    atr_value: Decimal = _ZERO

    spread_min: Decimal = _ZERO
    spread_max: Decimal = _ZERO
    levels_min: int = 1
    levels_max: int = 3
    target_base_pct: Decimal = _ZERO
    one_sided: str = "off"
    fill_factor: Decimal = Decimal("0.40")
    refresh_s: int = 30


# ── Funding snapshot (perp only) ─────────────────────────────────────

@dataclass(frozen=True)
class FundingSnapshot:
    """Perpetual funding rate data."""

    funding_rate: Decimal = _ZERO
    next_funding_time_ms: int = 0
    mark_price: Decimal = _ZERO


# ── ML snapshot ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class MlSnapshot:
    """ML model outputs if available."""

    features: dict[str, Any] = field(default_factory=dict)
    model_version: str = ""
    confidence: Decimal = _ZERO
    predicted_return: Decimal = _ZERO
    regime_override: str = ""


# ── Top-level market snapshot ────────────────────────────────────────

@dataclass(frozen=True)
class MarketSnapshot:
    """Complete tick-level market state passed to strategy signal sources.

    Assembled once per tick by KernelDataSurface.  Immutable — strategies
    cannot modify it.
    """

    timestamp_ms: int = 0
    mid: Decimal = _ZERO
    indicators: IndicatorSnapshot = field(default_factory=IndicatorSnapshot)
    order_book: OrderBookSnapshot = field(default_factory=OrderBookSnapshot)
    position: PositionSnapshot = field(default_factory=PositionSnapshot)
    equity: EquitySnapshot = field(default_factory=EquitySnapshot)
    regime: RegimeSnapshot = field(default_factory=RegimeSnapshot)
    trade_flow: TradeFlowSnapshot | None = None
    funding: FundingSnapshot | None = None
    ml: MlSnapshot | None = None
    config: dict[str, Any] = field(default_factory=dict)
    """Strategy configuration (read-only copy)."""


__all__ = [
    "EquitySnapshot",
    "FundingSnapshot",
    "IndicatorSnapshot",
    "MarketSnapshot",
    "MlSnapshot",
    "OrderBookSnapshot",
    "PositionSnapshot",
    "RegimeSnapshot",
    "TradeFlowSnapshot",
]
