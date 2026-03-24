export type ConnectionStatus = "idle" | "connecting" | "connected" | "reconnecting" | "error" | "closed";

export interface UiMarket {
  mid_price?: number | string;
  last_trade_price?: number | string;
  best_bid?: number | string;
  best_ask?: number | string;
  trading_pair?: string;
  ts?: number | string;
  timestamp_ms?: number | string;
  [key: string]: unknown;
}

export interface UiDepthLevel {
  price?: number | string;
  size?: number | string;
}

export interface UiDepth {
  bids?: UiDepthLevel[];
  asks?: UiDepthLevel[];
  best_bid?: number | string;
  best_ask?: number | string;
  trading_pair?: string;
  ts?: number | string;
  timestamp_ms?: number | string;
  [key: string]: unknown;
}

export interface UiPosition {
  quantity?: number | string;
  side?: string;
  avg_entry_price?: number | string;
  unrealized_pnl?: number | string;
  source_ts_ms?: number | string;
  trading_pair?: string;
  [key: string]: unknown;
}

export interface UiOrder {
  order_id?: string;
  client_order_id?: string;
  side?: string;
  price?: number | string | null;
  amount?: number | string | null;
  quantity?: number | string | null;
  amount_base?: number | string | null;
  state?: string;
  is_estimated?: boolean;
  estimate_source?: string;
  trading_pair?: string;
  price_hint_source?: string;
  created_ts_ms?: number | string | null;
  updated_ts_ms?: number | string | null;
}

export interface UiFill {
  order_id?: string;
  timestamp_ms?: number | string;
  ts?: string;
  side?: string;
  price?: number | string;
  amount_base?: number | string;
  amount?: number | string;
  notional_quote?: number | string;
  fee_quote?: number | string;
  realized_pnl_quote?: number | string;
  is_maker?: boolean;
}

export interface ActivityWindow {
  fill_count?: number;
  buy_count?: number;
  sell_count?: number;
  maker_count?: number;
  maker_ratio?: number;
  volume_base?: number;
  notional_quote?: number;
  realized_pnl_quote?: number;
  avg_fill_size?: number;
  avg_fill_price?: number;
  fees_quote?: number;
  [key: string]: unknown;
}

export interface SummaryActivity {
  fills_total?: number;
  latest_fill_ts_ms?: number;
  realized_pnl_total_quote?: number;
  window_15m?: ActivityWindow;
  window_1h?: ActivityWindow;
  [key: string]: unknown;
}

export interface SummaryAlert {
  severity?: string;
  title?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface SummarySystem {
  fallback_active?: boolean;
  latest_fill_ts_ms?: number;
  latest_market_ts_ms?: number;
  position_source_ts_ms?: number;
  stream_age_ms?: number | null;
  [key: string]: unknown;
}

export interface SummaryAccount {
  equity_quote?: number | string;
  quote_balance?: number | string;
  equity_open_quote?: number | string;
  equity_peak_quote?: number | string;
  realized_pnl_quote?: number | string;
  controller_state?: string;
  regime?: string;
  pnl_governor_active?: boolean;
  pnl_governor_reason?: string;
  risk_reasons?: string;
  daily_loss_pct?: number | string;
  max_daily_loss_pct_hard?: number | string;
  drawdown_pct?: number | string;
  max_drawdown_pct_hard?: number | string;
  order_book_stale?: boolean;
  snapshot_ts?: number | string;
  orders_active?: number | string;
  quoting_status?: string;
  quoting_reason?: string;
  quote_gates?: Array<{ key?: string; label?: string; status?: string; detail?: string }>;
  bot_gates?: BotGateGroup[];
  [key: string]: unknown;
}

export interface BotGateGroup {
  bot_id: string;
  strategy_type: string;
  gates: Array<{ key?: string; label?: string; status?: string; detail?: string }>;
}

export interface SummaryPayload {
  system?: SummarySystem;
  account?: SummaryAccount;
  activity?: SummaryActivity;
  alerts?: SummaryAlert[];
}

export interface StreamStatePayload {
  market?: UiMarket;
  depth?: UiDepth;
  position?: UiPosition;
  open_orders?: UiOrder[];
  fills?: UiFill[];
  fills_total?: number;
  key?: {
    instance_name?: string;
    controller_id?: string;
    trading_pair?: string;
  };
}

export interface SnapshotStatePayload {
  mode?: string;
  source?: string;
  key?: {
    instance_name?: string;
    controller_id?: string;
    trading_pair?: string;
  };
  stream?: StreamStatePayload;
  fallback?: {
    open_orders?: UiOrder[];
    fills?: UiFill[];
    fills_total?: number;
    position?: UiPosition;
    minute?: {
      mid?: number | string;
      [key: string]: unknown;
    };
  };
  summary?: SummaryPayload;
}

export interface WsSnapshotMessage {
  type: "snapshot";
  ts_ms?: number;
  instance_name?: string;
  controller_id?: string;
  trading_pair?: string;
  key?: {
    instance_name?: string;
    controller_id?: string;
    trading_pair?: string;
  };
  state?: SnapshotStatePayload;
  candles?: Array<{
    bucket_ms?: number | string;
    open?: number | string;
    high?: number | string;
    low?: number | string;
    close?: number | string;
  }>;
}

export interface WsEventEnvelope {
  event_type?: string;
  controller_id?: string;
  instance_name?: string;
  trading_pair?: string;
}

export interface WsEventMessage {
  type: "event";
  ts_ms?: number;
  stream?: string;
  instance_name?: string;
  controller_id?: string;
  trading_pair?: string;
  key?: {
    instance_name?: string;
    controller_id?: string;
    trading_pair?: string;
  };
  event_type?: string;
  event?: WsEventEnvelope | UiFill | Record<string, unknown>;
}

export interface WsKeepaliveMessage {
  type: "keepalive";
  ts_ms?: number;
}

export type WsInboundMessage = WsSnapshotMessage | WsEventMessage | WsKeepaliveMessage | Record<string, unknown>;

export interface RestStatePayload {
  mode?: string;
  source?: string;
  key?: {
    instance_name?: string;
    controller_id?: string;
    trading_pair?: string;
  };
  stream?: StreamStatePayload;
  fallback?: {
    open_orders?: UiOrder[];
    fills?: UiFill[];
    fills_total?: number;
    position?: UiPosition;
    minute?: {
      mid?: number | string;
      [key: string]: unknown;
    };
  };
  summary?: SummaryPayload;
}

export interface UiCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface RuntimeEvent {
  eventType: string;
  tsMs: number;
}

export interface PayloadRecord {
  id: string;
  receivedAtMs: number;
  messageType: string;
  eventType: string;
  instanceName: string;
  payload: unknown;
}

export interface GateTimelineEntry {
  start_ts?: number | string;
  start_ts_ms?: number | string;
  end_ts?: number | string;
  end_ts_ms?: number | string;
  duration_seconds?: number | string;
  quoting_status?: string;
  quoting_reason?: string;
  orders_active?: number | string;
  controller_state?: string;
  regime?: string;
  risk_reasons?: string;
  [key: string]: unknown;
}

export interface DailyReviewPayload {
  day?: string;
  trading_pair?: string;
  source?: string;
  narrative?: string;
  summary?: {
    equity_open_quote?: number;
    equity_close_quote?: number;
    equity_high_quote?: number;
    equity_low_quote?: number;
    quote_balance_end_quote?: number;
    realized_pnl_day_quote?: number;
    unrealized_pnl_end_quote?: number;
    fill_count?: number;
    buy_count?: number;
    sell_count?: number;
    maker_ratio?: number;
    notional_quote?: number;
    fees_quote?: number;
    controller_state_end?: string;
    regime_end?: string;
    risk_reasons_end?: string;
    minute_points?: number;
    [key: string]: unknown;
  };
  hourly?: Array<{
    hour_ts_ms?: number;
    fill_count?: number;
    buy_count?: number;
    sell_count?: number;
    maker_ratio?: number;
    notional_quote?: number;
    realized_pnl_quote?: number;
    [key: string]: unknown;
  }>;
  equity_curve?: Array<{
    ts_ms?: number | string;
    equity_quote?: number | string;
    mid_price?: number | string;
    state?: string;
    regime?: string;
    [key: string]: unknown;
  }>;
  fills?: UiFill[];
  gate_timeline?: GateTimelineEntry[];
  [key: string]: unknown;
}

export interface WeeklyReviewPayload {
  narrative?: string;
  summary?: {
    period_start?: string;
    period_end?: string;
    n_days?: number;
    days_with_data?: number;
    total_net_pnl_quote?: number;
    mean_daily_pnl_quote?: number;
    mean_daily_net_pnl_bps?: number;
    sharpe_annualized?: number;
    win_rate?: number;
    winning_days?: number;
    losing_days?: number;
    max_single_day_drawdown_pct?: number;
    hard_stop_days?: number;
    total_fills?: number;
    spread_capture_dominant_source?: boolean;
    dominant_source?: string;
    dominant_regime?: string;
    gate_pass?: boolean;
    gate_failed_criteria?: string[];
    warnings?: string[];
    [key: string]: unknown;
  };
  days?: Array<{
    date?: string;
    net_pnl_quote?: number;
    net_pnl_bps?: number;
    drawdown_pct?: number;
    fills?: number;
    turnover_x?: number;
    dominant_regime?: string;
    [key: string]: unknown;
  }>;
  regime_breakdown?: Record<string, number>;
  [key: string]: unknown;
}

export interface JournalTrade {
  trade_id?: string;
  entry_ts?: number | string;
  exit_ts?: number | string;
  side?: string;
  quantity?: number;
  avg_entry_price?: number;
  avg_exit_price?: number;
  hold_seconds?: number;
  entry_regime?: string;
  exit_regime?: string;
  entry_state?: string;
  exit_state?: string;
  mfe_quote?: number;
  mae_quote?: number;
  risk_reasons_seen?: string[];
  fees_quote?: number;
  exit_reason_label?: string;
  pnl_governor_seen?: boolean;
  order_book_stale_seen?: boolean;
  context_source?: string;
  realized_pnl_quote?: number;
  fill_count?: number;
  maker_ratio?: number;
  fills?: Array<{
    ts?: number | string;
    role?: string;
    side?: string;
    amount_base?: number;
    price?: number;
    notional_quote?: number;
    fee_quote?: number;
    realized_pnl_quote?: number;
    [key: string]: unknown;
  }>;
  path_points?: Array<{
    ts?: number | string;
    mid?: number;
    equity_quote?: number;
    state?: string;
    regime?: string;
    [key: string]: unknown;
  }>;
  path_summary?: {
    mid_open?: number;
    mid_close?: number;
    mid_high?: number;
    mid_low?: number;
    equity_open_quote?: number;
    equity_close_quote?: number;
    point_count?: number;
    [key: string]: unknown;
  };
  gate_timeline?: GateTimelineEntry[];
  [key: string]: unknown;
}

export interface JournalReviewPayload {
  start_day?: string;
  end_day?: string;
  trading_pair?: string;
  narrative?: string;
  summary?: {
    trade_count?: number;
    winning_trades?: number;
    losing_trades?: number;
    win_rate?: number;
    realized_pnl_quote_total?: number;
    fees_quote_total?: number;
    avg_realized_pnl_quote?: number;
    avg_hold_seconds?: number;
    avg_win_quote?: number;
    avg_loss_quote?: number;
    avg_mfe_quote?: number;
    avg_mae_quote?: number;
    start_ts?: number | string;
    end_ts?: number | string;
    entry_regime_breakdown?: Record<string, number>;
    exit_reason_breakdown?: Record<string, number>;
    [key: string]: unknown;
  };
  trades?: JournalTrade[];
  [key: string]: unknown;
}
