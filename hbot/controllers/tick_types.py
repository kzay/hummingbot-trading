"""Typed data contracts for tick-level telemetry snapshots.

``TickSnapshot`` is the return type of ``_build_tick_snapshot()`` in
``TelemetryMixin``.  It captures the full controller state at each tick
for the ``TickEmitter`` CSV/JSONL logger and Redis telemetry publisher.

All ``pct`` fields are in [0, 1] scale.  ``bps`` fields are basis points.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class TickSnapshot(TypedDict, total=False):
    """Controller state snapshot emitted by _build_tick_snapshot each tick."""

    # -- Runtime identity --
    runtime_family: str
    variant: str
    bot_mode: str
    is_paper: bool
    connector_name: str
    trading_pair: str

    # -- Spread geometry --
    spread_multiplier: Decimal
    spread_floor_pct: Decimal
    base_spread_pct: Decimal
    reservation_price_adjustment_pct: Decimal
    inventory_skew_pct: Decimal
    alpha_skew_pct: Decimal
    inventory_urgency_pct: Decimal
    spread_competitiveness_cap_active: bool
    spread_competitiveness_cap_side_pct: Decimal

    # -- Adaptive controls --
    adaptive_effective_min_edge_pct: Decimal
    adaptive_fill_age_s: Decimal
    adaptive_market_spread_bps_ewma: Decimal
    adaptive_band_pct_ewma: Decimal
    adaptive_market_floor_pct: Decimal
    adaptive_vol_ratio: Decimal

    # -- PnL governor --
    pnl_governor_active: bool
    pnl_governor_day_progress: Decimal
    pnl_governor_target_pnl_pct: Decimal
    pnl_governor_target_pnl_quote: Decimal
    pnl_governor_expected_pnl_quote: Decimal
    pnl_governor_actual_pnl_quote: Decimal
    pnl_governor_deficit_ratio: Decimal
    pnl_governor_edge_relax_bps: Decimal
    pnl_governor_size_mult: Decimal
    pnl_governor_size_boost_active: bool
    pnl_governor_activation_reason: str
    pnl_governor_size_boost_reason: str
    pnl_governor_activation_reason_counts: str
    pnl_governor_size_boost_reason_counts: str
    pnl_governor_target_mode: str
    pnl_governor_target_source: str
    pnl_governor_target_equity_open_quote: Decimal
    pnl_governor_target_effective_pct: Decimal
    pnl_governor_size_mult_applied: Decimal

    # -- Guard / execution state --
    soft_pause_edge: bool
    edge_gate_blocked: bool
    selective_quote_state: str
    selective_quote_score: Decimal
    selective_quote_reason: str
    selective_quote_adverse_ratio: Decimal
    selective_quote_slippage_p95_bps: Decimal
    alpha_policy_state: str
    alpha_policy_reason: str
    alpha_maker_score: Decimal
    alpha_aggressive_score: Decimal
    alpha_cross_allowed: bool
    adverse_fill_soft_pause_active: bool
    edge_confidence_soft_pause_active: bool
    slippage_soft_pause_active: bool

    # -- Daily accounting --
    fills_count_today: int
    fees_paid_today_quote: Decimal
    traded_notional_today: Decimal
    daily_equity_open: Decimal | None
    realized_pnl_today: Decimal
    net_realized_pnl_today: Decimal

    # -- Paper engine --
    paper_fill_count: int
    paper_reject_count: int
    paper_avg_queue_delay_ms: Decimal

    # -- External signals --
    external_soft_pause: bool
    external_pause_reason: str
    external_model_version: str
    external_intent_reason: str
    external_daily_pnl_target_pct_override: Decimal
    external_daily_pnl_target_pct_override_expires_ts: float

    # -- Fees --
    fee_source: str
    maker_fee_pct: Decimal
    taker_fee_pct: Decimal

    # -- Connector --
    balance_read_failed: bool
    ws_reconnect_count: int
    connector_status: str

    # -- Position --
    is_perp: bool
    funding_rate: Decimal
    funding_cost_today_quote: Decimal
    margin_ratio: Decimal
    regime_source: str
    avg_entry_price: Decimal
    avg_entry_price_long: Decimal
    avg_entry_price_short: Decimal
    position_base: Decimal
    position_gross_base: Decimal
    position_long_base: Decimal
    position_short_base: Decimal
    position_drift_pct: Decimal

    # -- Derisk --
    derisk_force_taker_min_base: Decimal
    derisk_force_taker_expectancy_guard_blocked: bool
    derisk_force_taker_expectancy_guard_reason: str
    derisk_force_taker_expectancy_mean_quote: Decimal
    derisk_force_taker_expectancy_taker_fills: int

    # -- Fill edge --
    fill_edge_ewma: Decimal | None
    adverse_fill_active: bool
    adverse_skip_count: int

    # -- Microstructure --
    ob_imbalance: Decimal
    kelly_size_active: bool
    kelly_order_quote: Decimal
    ml_regime_override: str

    # -- Profiling --
    indicator_duration_ms: float
    connector_io_duration_ms: float

    # -- Config limits (included for dashboards) --
    min_base_pct: Decimal
    max_base_pct: Decimal
    max_total_notional_quote: Decimal
    max_daily_turnover_x_hard: Decimal
    max_daily_loss_pct_hard: Decimal
    max_drawdown_pct_hard: Decimal
    margin_ratio_soft_pause_pct: Decimal
    margin_ratio_hard_stop_pct: Decimal
    position_drift_soft_pause_pct: Decimal
