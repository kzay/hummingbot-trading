from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FillStats:
    buys: int = 0
    sells: int = 0
    maker_fills: int = 0
    taker_fills: int = 0
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    total_fees: float = 0.0
    total_realized_pnl: float = 0.0
    # Cumulative sums (for delta()/windowed averages in Prometheus)
    fill_slippage_bps_sum: float = 0.0
    fill_slippage_bps_count: int = 0
    expected_spread_bps_sum: float = 0.0
    expected_spread_bps_count: int = 0
    adverse_drift_30s_bps_sum: float = 0.0
    adverse_drift_30s_bps_count: int = 0
    fee_bps_sum: float = 0.0
    fee_bps_count: int = 0
    avg_buy_price: float = 0.0
    avg_sell_price: float = 0.0
    last_fill_ts: str = ""
    last_fill_side: str = ""
    last_fill_price: float = 0.0
    last_fill_amount: float = 0.0
    last_fill_pnl: float = 0.0
    # FreqText table metrics (computed from full fills.csv scan)
    closed_pnl_total: float = 0.0         # sum realized_pnl_quote
    trades_total: int = 0                  # total row count
    trade_wins_total: int = 0              # rows with realized_pnl_quote > 0
    trade_losses_total: int = 0            # rows with realized_pnl_quote < 0
    trade_winrate: float = 0.0             # wins / (wins + losses)
    trade_expectancy_quote: float = 0.0    # mean nonzero realized_pnl
    trade_expectancy_rate_quote: float = 0.0  # avg_win*wr - avg_loss*(1-wr)
    trade_median_win_quote: float = 0.0    # median of positive realized_pnl
    trade_median_loss_quote: float = 0.0   # median of negative realized_pnl
    first_fill_timestamp_seconds: float = 0.0  # epoch of earliest fill
    last_fill_timestamp_seconds: float = 0.0   # epoch of latest fill
    fills_24h_count: int = 0
    realized_pnl_24h_quote: float = 0.0
    fills_5m_count: int = 0
    fills_1h_count: int = 0
    realized_pnl_1h_quote: float = 0.0


@dataclass
class PositionSnapshot:
    """One open position from paper_desk_v2.json."""
    instrument_id: str = ""
    pair: str = ""
    quantity_base: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl_quote: float = 0.0
    opened_at_seconds: float = 0.0
    total_fees_paid_quote: float = 0.0


@dataclass
class PortfolioSnapshot:
    """Aggregated portfolio data from paper_desk_v2.json."""
    open_pnl_quote: float = 0.0
    positions: list[PositionSnapshot] = field(default_factory=list)
    paper_margin_call_events_total: float = 0.0
    paper_liquidation_events_total: float = 0.0
    paper_liquidation_actions_total: float = 0.0
    paper_margin_level: str = "unknown"


@dataclass
class MinuteHistoryStats:
    """KPIs computed from the full minute.csv history."""
    equity_start_quote: float = 0.0          # equity_quote of first minute row
    realized_pnl_week_quote: float = 0.0     # 7-day day-boundary aggregation
    realized_pnl_month_quote: float = 0.0    # 30-day day-boundary aggregation
    derisk_stall_seconds: float = 0.0        # continuous derisk/hard-stop stall window
    derisk_stall_active: float = 0.0         # 1 when derisk stall is currently active


@dataclass
class MinuteFileScan:
    """Cheap single-pass minute.csv summary used on the scrape path."""
    last_row: dict[str, str] | None = None
    row_count: int = 0


@dataclass
class FillsFileSummary:
    """Single-pass fills.csv summary for the default scrape path."""
    row_count: int = 0
    fill_stats: FillStats = field(default_factory=FillStats)
    recent_fills: list[dict[str, object]] = field(default_factory=list)


@dataclass
class OpenOrderSnapshot:
    order_id: str = ""
    side: str = ""
    pair: str = ""
    price: float = 0.0
    amount_base: float = 0.0
    age_sec: float = 0.0


@dataclass
class BotSnapshot:
    bot_name: str
    variant: str
    bot_mode: str
    accounting_source: str
    exchange: str
    trading_pair: str
    state: str
    regime: str
    ts_epoch: float
    net_edge_pct: float
    net_edge_gate_pct: float
    spread_pct: float
    spread_floor_pct: float
    turnover_today_x: float
    orders_active: float
    maker_fee_pct: float
    taker_fee_pct: float
    soft_pause_edge: float
    fee_source: str
    equity_quote: float
    base_pct: float
    target_base_pct: float
    projected_total_quote: float
    daily_loss_pct: float
    drawdown_pct: float
    edge_pause_threshold_pct: float
    edge_resume_threshold_pct: float
    min_base_pct: float
    max_base_pct: float
    max_total_notional_quote: float
    max_daily_turnover_x_hard: float
    max_daily_loss_pct_hard: float
    max_drawdown_pct_hard: float
    margin_ratio_soft_pause_pct: float
    margin_ratio_hard_stop_pct: float
    position_drift_soft_pause_pct: float
    cancel_per_min: float
    risk_reasons: str
    daily_pnl_quote: float
    daily_fills_count: float
    fills_total: float
    recent_error_lines: float
    tick_duration_ms: float
    indicator_duration_ms: float
    connector_io_duration_ms: float
    position_drift_pct: float
    margin_ratio: float
    funding_rate: float
    funding_cost_today_quote: float
    realized_pnl_today_quote: float
    net_realized_pnl_today_quote: float
    ws_reconnect_count: float
    order_book_stale: float
    history_seed_status: str = "disabled"
    history_seed_reason: str = ""
    history_seed_source: str = ""
    history_seed_bars: float = 0.0
    history_seed_latency_ms: float = 0.0
    derisk_runtime_recovered: float = 0.0
    derisk_runtime_recovery_count: float = 0.0
    pnl_governor_target_effective_pct: float = 0.0
    pnl_governor_size_mult_applied: float = 1.0
    spread_competitiveness_cap_active: float = 0.0
    spread_competitiveness_cap_side_pct: float = 0.0
    pnl_governor_target_mode: str = "disabled"
    position_base: float = 0.0
    position_gross_base: float = 0.0
    position_long_base: float = 0.0
    position_short_base: float = 0.0
    avg_entry_price: float = 0.0
    avg_entry_price_long: float = 0.0
    avg_entry_price_short: float = 0.0
    bot1_signal_score: float = 0.0
    bot5_signal_score: float = 0.0
    bot6_signal_score: float = 0.0
    bot6_signal_score_active: float = 0.0
    bot6_cvd_divergence_ratio: float = 0.0
    bot6_delta_spike_ratio: float = 0.0
    bot7_signal_score: float = 0.0
    bot7_cvd: float = 0.0
    bot7_grid_levels: float = 0.0
    bot7_hedge_target_base_pct: float = 0.0
    market_spread_bps: float = 0.0
    best_bid_price: float = 0.0
    best_ask_price: float = 0.0
    mid_price: float = 0.0
    best_bid_size: float = 0.0
    best_ask_size: float = 0.0
    book_imbalance: float = 0.0
    fill_stats: FillStats | None = None
    portfolio: PortfolioSnapshot | None = None
    minute_history: MinuteHistoryStats | None = None
    derisk_stall_seconds: float = 0.0
    derisk_stall_active: float = 0.0
    minute_rows_total: float = 0.0
    minute_last_timestamp_seconds: float = 0.0
    minute_last_age_seconds: float = 0.0
    fills_last_timestamp_seconds: float = 0.0
    fills_last_age_seconds: float = 0.0
    open_orders_total: float = 0.0
    open_orders_buy: float = 0.0
    open_orders_sell: float = 0.0
    open_orders: list[OpenOrderSnapshot] = field(default_factory=list)
    recent_fills: list[dict[str, object]] = field(default_factory=list)
    order_failure_total: float = 0.0
