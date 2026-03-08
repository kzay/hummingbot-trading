"""Typed data contracts for the EPP v2.4 controller family.

``ProcessedState`` is the primary output of ``update_processed_data()``
and the data contract consumed by the strategy runner, metrics exporter,
Redis bus publisher, and CSV logger.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


PROCESSED_STATE_SCHEMA_VERSION: int = 10
"""Increment whenever a field is added, removed, or changes semantics.
Consumers should check this on deserialization and drop/log on mismatch."""


class ProcessedState(TypedDict, total=False):
    """Snapshot of controller state produced every tick cycle.

    All price/pct values are Decimal.  ``pct`` fields are in [0, 1] scale
    (e.g. 0.003 = 0.3 %).  ``bps`` fields are basis points (1 bps = 0.01 %).
    """

    # -- Schema --
    schema_version: int
    """Schema version of this ProcessedState. Compare with PROCESSED_STATE_SCHEMA_VERSION."""

    # -- Reference pricing --
    reference_price: Decimal
    """Mid price used as reference for order placement."""
    spread_multiplier: Decimal
    """Multiplier applied to spread (>1 when adverse fill protection is active)."""
    mid: Decimal
    """Raw mid price from connector."""

    # -- Regime --
    regime: str
    """Detected market regime: neutral_low_vol | up | down | high_vol_shock."""
    regime_source: str
    """How the regime was determined: price_buffer | external_override."""
    ml_regime_override: str
    """External ML model regime override (empty string if none)."""

    # -- Inventory --
    target_base_pct: Decimal
    """Target base allocation ratio [0..1]."""
    base_pct: Decimal
    """Current base allocation ratio [0..1]."""
    target_net_base_pct: Decimal
    """Perps: signed net exposure target as fraction of equity. Spot: equals target_base_pct."""
    net_base_pct: Decimal
    """Perps: signed net exposure as fraction of equity. Spot: equals base_pct."""
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
    base_spread_pct: Decimal
    """Base spread selected before drift/adverse/vol wideners are applied."""
    net_edge_pct: Decimal
    """Estimated net edge after fees/slippage/drift."""
    net_edge_gate_pct: Decimal
    """Edge value used by edge gate (may be smoothed)."""
    net_edge_ewma_pct: Decimal
    """EWMA-smoothed net edge for debugging edge gate stability."""
    adaptive_effective_min_edge_pct: Decimal
    """Adaptive min edge threshold currently enforced (post history-based adjustments)."""
    adaptive_fill_age_s: Decimal
    """Seconds since last fill used by adaptation feedback controller."""
    adaptive_market_spread_bps_ewma: Decimal
    """EWMA of observed market spread in bps for ticker-specific adaptation."""
    adaptive_band_pct_ewma: Decimal
    """EWMA of volatility band used by adaptive spread/edge controls."""
    adaptive_market_floor_pct: Decimal
    """Adaptive market-derived spread floor contribution (pct)."""
    adaptive_vol_ratio: Decimal
    """Normalized volatility ratio used for adaptive spread widening [0..1]."""
    pnl_governor_active: bool
    """True when daily PnL governor is actively relaxing edge threshold."""
    pnl_governor_day_progress: Decimal
    """UTC day progress in [0..1] used by the PnL governor target trajectory."""
    pnl_governor_target_pnl_pct: Decimal
    """Configured daily target in pct of opening equity (0 means quote target fallback)."""
    pnl_governor_target_pnl_quote: Decimal
    """Configured daily PnL target in quote units."""
    pnl_governor_expected_pnl_quote: Decimal
    """Expected PnL at current day progress according to the governor trajectory."""
    pnl_governor_actual_pnl_quote: Decimal
    """Current marked-to-market day PnL used by the governor."""
    pnl_governor_deficit_ratio: Decimal
    """Normalized deficit ratio in [0..1] when behind target (0 otherwise)."""
    pnl_governor_edge_relax_bps: Decimal
    """Current edge-threshold relaxation applied by the PnL governor (bps)."""
    pnl_governor_size_mult: Decimal
    """Dynamic sizing multiplier from the governor (1.0 when inactive)."""
    pnl_governor_size_boost_active: bool
    """True when dynamic size boost is active and >1 multiplier is applied."""
    pnl_governor_target_mode: str
    """How target is resolved: pct_equity | quote_legacy | disabled."""
    pnl_governor_target_source: str
    """Config source used for target resolution."""
    pnl_governor_target_equity_open_quote: Decimal
    """Opening equity used to convert pct target into quote target."""
    pnl_governor_target_effective_pct: Decimal
    """Effective daily target as pct of opening equity (0 when disabled)."""
    pnl_governor_size_mult_applied: Decimal
    """Final sizing multiplier applied to runtime quote sizing after clamps."""
    pnl_governor_activation_reason: str
    """Per-tick governor activation reason code (active or explicit non-activation branch)."""
    pnl_governor_size_boost_reason: str
    """Per-tick size boost reason code (active or explicit non-activation branch)."""
    pnl_governor_activation_reason_counts: str
    """JSON map of cumulative activation-reason counters for current runtime/day."""
    pnl_governor_size_boost_reason_counts: str
    """JSON map of cumulative size-boost reason counters for current runtime/day."""
    skew: Decimal
    """Inventory skew applied to buy/sell spread asymmetry."""
    reservation_price_adjustment_pct: Decimal
    """Signed reservation-price shift from combined inventory and alpha biases."""
    inventory_urgency_pct: Decimal
    """Normalized inventory urgency [0..1] for quote steering and unwind decisions."""
    inventory_skew_pct: Decimal
    """Signed inventory-driven component of reservation-price shift."""
    alpha_skew_pct: Decimal
    """Signed alpha-driven component of reservation-price shift."""
    adverse_drift_30s: Decimal
    """Raw absolute mid price drift over the last 30 seconds (used for regime detection)."""
    adverse_drift_smooth_30s: Decimal
    """EWMA-smoothed adverse drift used for cost model and edge gate (less spiky than raw)."""
    drift_spread_mult: Decimal
    """Spread multiplier applied due to drift spike (1.0 = no widening, >1 = widened)."""
    fill_edge_ewma_bps: Decimal
    """EWMA of realized fill edge in basis points (0 if no fills yet)."""

    # -- Market microstructure --
    market_spread_pct: Decimal
    """Best ask - best bid as fraction of mid."""
    market_spread_bps: Decimal
    """Market spread in basis points."""
    best_bid_price: Decimal
    """Price at best bid."""
    best_ask_price: Decimal
    """Price at best ask."""
    best_bid_size: Decimal
    """Size at best bid."""
    best_ask_size: Decimal
    """Size at best ask."""
    ob_imbalance: Decimal
    """Order book imbalance [-1, +1]. Positive = more bids (buy pressure)."""
    spread_competitiveness_cap_active: bool
    """True when quote side spreads are clipped by market competitiveness cap."""
    spread_competitiveness_cap_side_pct: Decimal
    """Per-side spread cap used by competitiveness logic."""
    order_book_stale: bool
    """True if the order book data is considered stale."""

    # -- Guard / state --
    state: str
    """OpsGuard state: running | soft_pause | hard_stop."""
    soft_pause_edge: bool
    """True if edge gate is currently blocking execution."""
    edge_gate_blocked: bool
    """True if edge gate is in blocked state."""
    selective_quote_state: str
    """Backward-compatible selective quote state: inactive | reduced | blocked."""
    selective_quote_score: Decimal
    """Backward-compatible selective quote score [0..1]."""
    selective_quote_reason: str
    """Backward-compatible selective quote reason string."""
    selective_quote_adverse_ratio: Decimal
    """Adverse-fill contribution to the selective quote score."""
    selective_quote_slippage_p95_bps: Decimal
    """Recent positive slippage p95 used by selective quote quality logic."""
    alpha_policy_state: str
    """Forward-looking policy state: no_trade | maker_two_sided | maker_bias_* | aggressive_*."""
    alpha_policy_reason: str
    """Primary reason branch for alpha policy state."""
    alpha_maker_score: Decimal
    """Normalized maker-entry score [0..1]."""
    alpha_aggressive_score: Decimal
    """Normalized aggressive-entry score [0..1]."""
    alpha_cross_allowed: bool
    """True when bounded aggressive entry is permitted."""
    quote_side_mode: str
    """Resolved side mode applied to runtime quotes."""
    quote_side_reason: str
    """Reason for the resolved quote side mode."""
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

    # -- Adverse fill protection --
    adverse_fill_active: bool
    """True if adverse fill spread widening is active."""
    adverse_skip_count: int
    """Number of ticks skipped due to adverse fill detection."""

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
    realized_pnl_today_quote: Decimal
    """Realized PnL today from closed positions (perps)."""
    net_realized_pnl_today_quote: Decimal
    """Realized PnL net of funding cost today (realized - funding_cost_today_quote)."""

    # -- Perpetual-specific --
    is_perpetual: bool
    """True if the connector is a perpetual futures connector."""
    funding_rate: Decimal
    """Current funding rate (perps only, 0 for spot)."""
    funding_cost_today_quote: Decimal
    """Cumulative funding cost paid today in quote (perps only)."""
    margin_ratio: Decimal
    """Current margin ratio (perps only, 1 for spot)."""
    avg_entry_price: Decimal
    """Average entry price for the current position (perps)."""
    avg_entry_price_long: Decimal
    """Average entry price for the long leg when hedge mode is active."""
    avg_entry_price_short: Decimal
    """Average entry price for the short leg when hedge mode is active."""
    position_base: Decimal
    """Current position size in base (signed for perps)."""
    position_gross_base: Decimal
    """Current gross open base across long and short legs."""
    position_long_base: Decimal
    """Current long-leg size in base."""
    position_short_base: Decimal
    """Current short-leg size in base."""
    position_drift_pct: Decimal
    """Position drift as fraction of equity (perps)."""

    # -- Kelly sizing --
    kelly_size_active: bool
    """True if Kelly criterion sizing is active (enough observations)."""
    kelly_order_quote: Decimal
    """Kelly-optimal order size in quote (0 if Kelly not active)."""

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

    # -- Connectivity --
    ws_reconnect_count: int
    """Number of WebSocket reconnections since startup."""
    connector_status: str
    """Human-readable connector status summary."""

    # -- Internal profiling (prefixed with _) --
    _tick_duration_ms: float
    """Wall-clock duration of the last update_processed_data tick."""
    _indicator_duration_ms: float
    """Wall-clock duration of indicator computation within the tick."""
    _connector_io_duration_ms: float
    """Wall-clock duration of connector I/O within the tick."""
