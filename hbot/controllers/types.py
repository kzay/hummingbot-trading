"""Typed data contracts for the EPP v2.4 controller family.

``ProcessedState`` is the primary output of ``update_processed_data()``
and the data contract consumed by the strategy runner, metrics exporter,
Redis bus publisher, and CSV logger.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class ProcessedState(TypedDict, total=False):
    """Snapshot of controller state produced every tick cycle.

    All price/pct values are Decimal.  ``pct`` fields are in [0, 1] scale
    (e.g. 0.003 = 0.3 %).  ``bps`` fields are basis points (1 bps = 0.01 %).
    """

    # -- Reference pricing --
    reference_price: Decimal
    """Mid price used as reference for order placement."""
    spread_multiplier: Decimal
    """Multiplier applied to spread (always 1 in current version)."""
    mid: Decimal
    """Raw mid price from connector."""

    # -- Regime --
    regime: str
    """Detected market regime: neutral_low_vol | up | down | high_vol_shock."""

    # -- Inventory --
    target_base_pct: Decimal
    """Target base allocation ratio [0..1]."""
    base_pct: Decimal
    """Current base allocation ratio [0..1]."""
    base_balance: Decimal
    """Base asset balance."""
    quote_balance: Decimal
    """Quote asset balance."""
    equity_quote: Decimal
    """Total equity in quote terms (quote + base * mid)."""

    # -- Spread / edge --
    spread_pct: Decimal
    """Active spread percentage (half-spread on each side)."""
    spread_floor_pct: Decimal
    """Minimum spread that clears the edge gate."""
    net_edge_pct: Decimal
    """Estimated net edge after fees/slippage/drift."""
    skew: Decimal
    """Inventory skew applied to buy/sell spread asymmetry."""
    adverse_drift_30s: Decimal
    """Absolute mid price drift over the last 30 seconds."""

    # -- Market microstructure --
    market_spread_pct: Decimal
    """Best ask - best bid as fraction of mid."""
    market_spread_bps: Decimal
    """Market spread in basis points."""
    best_bid_size: Decimal
    """Size at best bid."""
    best_ask_size: Decimal
    """Size at best ask."""

    # -- Guard / state --
    state: str
    """OpsGuard state: running | soft_pause | hard_stop."""
    soft_pause_edge: bool
    """True if edge gate is currently blocking execution."""
    edge_gate_blocked: bool
    """True if edge gate is in blocked state."""
    edge_pause_threshold_pct: Decimal
    """Net edge below this triggers edge gate block."""
    edge_resume_threshold_pct: Decimal
    """Net edge above this releases edge gate block."""
    risk_hard_stop: bool
    """True if any risk policy triggered hard stop."""
    risk_reasons: str
    """Pipe-delimited list of active risk reasons."""
    balance_read_failed: bool
    """True if the last balance read from connector failed."""

    # -- Daily accounting --
    turnover_x: Decimal
    """Daily traded notional / equity (turnover multiple)."""
    daily_loss_pct: Decimal
    """Daily loss as fraction of opening equity [0..1]."""
    drawdown_pct: Decimal
    """Drawdown from intraday peak [0..1]."""
    projected_total_quote: Decimal
    """Projected total order notional for current cycle."""
    fills_count_today: int
    """Number of fills since daily rollover."""
    fees_paid_today_quote: Decimal
    """Cumulative fees paid today in quote asset."""
    spread_capture_est_quote: Decimal
    """Estimated spread capture = turnover * spread * fill_factor."""
    pnl_quote: Decimal
    """Unrealized daily PnL (equity_now - equity_open)."""

    # -- Paper engine --
    paper_fill_count: int
    """Paper engine fills since startup."""
    paper_reject_count: int
    """Paper engine order rejections since startup."""
    paper_avg_queue_delay_ms: Decimal
    """Average simulated queue delay in milliseconds."""

    # -- External signals --
    external_soft_pause: bool
    """True if an external intent has paused this controller."""
    external_pause_reason: str
    """Reason string from the external pause intent."""
    external_model_version: str
    """Model version from the most recent external intent."""
    external_intent_reason: str
    """Reason from the most recent external intent."""

    # -- Fees --
    fee_source: str
    """How fees were resolved: api:exchange | project:path | manual | manual_fallback."""
    maker_fee_pct: Decimal
    """Effective maker fee as decimal (e.g. 0.001 = 0.1%)."""
    taker_fee_pct: Decimal
    """Effective taker fee as decimal."""
