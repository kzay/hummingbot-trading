import { z } from "zod";

import type {
  DailyReviewPayload,
  JournalReviewPayload,
  PayloadRecord,
  RestStatePayload,
  SummaryAccount,
  SummaryActivity,
  SummaryAlert,
  SummarySystem,
  UiCandle,
  UiDepth,
  UiDepthLevel,
  UiFill,
  UiMarket,
  UiOrder,
  UiPosition,
  WeeklyReviewPayload,
  WsEventMessage,
  WsInboundMessage,
  WsKeepaliveMessage,
  WsSnapshotMessage,
} from "../types/realtime";

const numberLikeSchema = z.union([z.number(), z.string()]);
const nullableNumberLikeSchema = z.union([z.number(), z.string(), z.null()]);
const stringArraySchema = z.array(z.string());
const unknownRecordSchema = z.record(z.string(), z.unknown());

const keySchema = z
  .object({
    instance_name: z.string().optional(),
    instance: z.string().optional(),
    controller_id: z.string().optional(),
    controller: z.string().optional(),
    trading_pair: z.string().optional(),
    pair: z.string().optional(),
  })
  .passthrough();

const uiDepthLevelSchema: z.ZodType<UiDepthLevel> = z
  .object({
    price: numberLikeSchema.optional(),
    size: numberLikeSchema.optional(),
  })
  .passthrough();

const uiMarketSchema: z.ZodType<UiMarket> = z
  .object({
    mid_price: numberLikeSchema.optional(),
    best_bid: numberLikeSchema.optional(),
    best_ask: numberLikeSchema.optional(),
    trading_pair: z.string().optional(),
    ts: z.string().optional(),
    timestamp_ms: numberLikeSchema.optional(),
  })
  .passthrough();

const uiDepthSchema: z.ZodType<UiDepth> = z
  .object({
    bids: z.array(uiDepthLevelSchema).optional(),
    asks: z.array(uiDepthLevelSchema).optional(),
    best_bid: numberLikeSchema.optional(),
    best_ask: numberLikeSchema.optional(),
    trading_pair: z.string().optional(),
    ts: z.string().optional(),
    timestamp_ms: numberLikeSchema.optional(),
  })
  .passthrough();

const uiPositionSchema: z.ZodType<UiPosition> = z
  .object({
    quantity: numberLikeSchema.optional(),
    side: z.string().optional(),
    avg_entry_price: numberLikeSchema.optional(),
    unrealized_pnl: numberLikeSchema.optional(),
    source_ts_ms: numberLikeSchema.optional(),
    trading_pair: z.string().optional(),
  })
  .passthrough();

const uiOrderSchema: z.ZodType<UiOrder> = z
  .object({
    order_id: z.string().optional(),
    client_order_id: z.string().optional(),
    side: z.string().optional(),
    price: nullableNumberLikeSchema.optional(),
    amount: nullableNumberLikeSchema.optional(),
    quantity: nullableNumberLikeSchema.optional(),
    amount_base: nullableNumberLikeSchema.optional(),
    state: z.string().optional(),
    is_estimated: z.boolean().optional(),
    estimate_source: z.string().optional(),
    trading_pair: z.string().optional(),
    price_hint_source: z.string().optional(),
    created_ts_ms: nullableNumberLikeSchema.optional(),
    updated_ts_ms: nullableNumberLikeSchema.optional(),
  })
  .passthrough();

const uiFillSchema: z.ZodType<UiFill> = z
  .object({
    order_id: z.string().optional(),
    timestamp_ms: numberLikeSchema.optional(),
    ts: z.string().optional(),
    side: z.string().optional(),
    price: numberLikeSchema.optional(),
    amount_base: numberLikeSchema.optional(),
    amount: numberLikeSchema.optional(),
    notional_quote: numberLikeSchema.optional(),
    fee_quote: numberLikeSchema.optional(),
    realized_pnl_quote: numberLikeSchema.optional(),
    is_maker: z.boolean().optional(),
  })
  .passthrough();

const summaryActivitySchema: z.ZodType<SummaryActivity> = z
  .object({
    fills_total: z.number().optional(),
    latest_fill_ts_ms: z.number().optional(),
    realized_pnl_total_quote: z.number().optional(),
    window_15m: unknownRecordSchema.optional(),
    window_1h: unknownRecordSchema.optional(),
  })
  .passthrough();

const summaryAlertSchema: z.ZodType<SummaryAlert> = z
  .object({
    severity: z.string().optional(),
    title: z.string().optional(),
    detail: z.string().optional(),
  })
  .passthrough();

const summarySystemSchema: z.ZodType<SummarySystem> = z
  .object({
    fallback_active: z.boolean().optional(),
    latest_fill_ts_ms: z.number().optional(),
    latest_market_ts_ms: z.number().optional(),
    position_source_ts_ms: z.number().optional(),
    stream_age_ms: z.number().nullable().optional(),
  })
  .passthrough();

const summaryAccountSchema: z.ZodType<SummaryAccount> = z
  .object({
    equity_quote: numberLikeSchema.optional(),
    quote_balance: numberLikeSchema.optional(),
    equity_open_quote: numberLikeSchema.optional(),
    equity_peak_quote: numberLikeSchema.optional(),
    realized_pnl_quote: numberLikeSchema.optional(),
    controller_state: z.string().optional(),
    regime: z.string().optional(),
    pnl_governor_active: z.boolean().optional(),
    pnl_governor_reason: z.string().optional(),
    risk_reasons: z.string().optional(),
    daily_loss_pct: numberLikeSchema.optional(),
    max_daily_loss_pct_hard: numberLikeSchema.optional(),
    drawdown_pct: numberLikeSchema.optional(),
    max_drawdown_pct_hard: numberLikeSchema.optional(),
    order_book_stale: z.boolean().optional(),
    snapshot_ts: numberLikeSchema.optional(),
    orders_active: numberLikeSchema.optional(),
    quoting_status: z.string().optional(),
    quoting_reason: z.string().optional(),
    quote_gates: z
      .array(
        z
          .object({
            key: z.string().optional(),
            label: z.string().optional(),
            status: z.string().optional(),
            detail: z.string().optional(),
          })
          .passthrough(),
      )
      .optional(),
  })
  .passthrough();

const summaryPayloadSchema = z
  .object({
    system: summarySystemSchema.optional(),
    account: summaryAccountSchema.optional(),
    activity: summaryActivitySchema.optional(),
    alerts: z.array(summaryAlertSchema).optional(),
  })
  .passthrough();

const candleSchema: z.ZodType<UiCandle> = z.object({
  time: z.number(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
});

const rawCandleSchema = z
  .object({
    bucket_ms: numberLikeSchema.optional(),
    open: numberLikeSchema.optional(),
    high: numberLikeSchema.optional(),
    low: numberLikeSchema.optional(),
    close: numberLikeSchema.optional(),
  })
  .passthrough();

const streamStatePayloadSchema = z
  .object({
    market: uiMarketSchema.optional(),
    depth: uiDepthSchema.optional(),
    position: uiPositionSchema.optional(),
    open_orders: z.array(uiOrderSchema).optional(),
    fills: z.array(uiFillSchema).optional(),
    fills_total: z.number().optional(),
    key: keySchema.optional(),
  })
  .passthrough();

const fallbackStatePayloadSchema = z
  .object({
    open_orders: z.array(uiOrderSchema).optional(),
    fills: z.array(uiFillSchema).optional(),
    fills_total: z.number().optional(),
    position: uiPositionSchema.optional(),
    minute: z
      .object({
        mid: numberLikeSchema.optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

const snapshotStatePayloadSchema: z.ZodType<RestStatePayload> = z
  .object({
    mode: z.string().optional(),
    source: z.string().optional(),
    key: keySchema.optional(),
    stream: streamStatePayloadSchema.optional(),
    fallback: fallbackStatePayloadSchema.optional(),
    summary: summaryPayloadSchema.optional(),
  })
  .passthrough();

const wsEventEnvelopeSchema = z
  .object({
    event_type: z.string().optional(),
    controller_id: z.string().optional(),
    instance_name: z.string().optional(),
    trading_pair: z.string().optional(),
  })
  .passthrough();

const wsSnapshotMessageSchema: z.ZodType<WsSnapshotMessage> = z
  .object({
    type: z.literal("snapshot"),
    ts_ms: z.number().optional(),
    instance_name: z.string().optional(),
    controller_id: z.string().optional(),
    trading_pair: z.string().optional(),
    key: keySchema.optional(),
    state: snapshotStatePayloadSchema.optional(),
    candles: z.array(rawCandleSchema).optional(),
  })
  .passthrough();

const wsEventMessageSchema: z.ZodType<WsEventMessage> = z
  .object({
    type: z.literal("event"),
    ts_ms: z.number().optional(),
    stream: z.string().optional(),
    instance_name: z.string().optional(),
    controller_id: z.string().optional(),
    trading_pair: z.string().optional(),
    key: keySchema.optional(),
    event_type: z.string().optional(),
    event: z.union([wsEventEnvelopeSchema, uiFillSchema, unknownRecordSchema]).optional(),
  })
  .passthrough();

const wsKeepaliveMessageSchema: z.ZodType<WsKeepaliveMessage> = z
  .object({
    type: z.literal("keepalive"),
    ts_ms: z.number().optional(),
  })
  .passthrough();

const gateTimelineEntrySchema = z
  .object({
    start_ts: numberLikeSchema.optional(),
    start_ts_ms: numberLikeSchema.optional(),
    end_ts: numberLikeSchema.optional(),
    end_ts_ms: numberLikeSchema.optional(),
    duration_seconds: numberLikeSchema.optional(),
    quoting_status: z.string().optional(),
    quoting_reason: z.string().optional(),
    orders_active: numberLikeSchema.optional(),
    controller_state: z.string().optional(),
    regime: z.string().optional(),
    risk_reasons: z.string().optional(),
  })
  .passthrough();

const dailyReviewPayloadSchema: z.ZodType<DailyReviewPayload> = z
  .object({
    day: z.string().optional(),
    trading_pair: z.string().optional(),
    source: z.string().optional(),
    narrative: z.string().optional(),
    summary: z
      .object({
        equity_open_quote: z.number().optional(),
        equity_close_quote: z.number().optional(),
        equity_high_quote: z.number().optional(),
        equity_low_quote: z.number().optional(),
        quote_balance_end_quote: z.number().optional(),
        realized_pnl_day_quote: z.number().optional(),
        unrealized_pnl_end_quote: z.number().optional(),
        fill_count: z.number().optional(),
        buy_count: z.number().optional(),
        sell_count: z.number().optional(),
        maker_ratio: z.number().optional(),
        notional_quote: z.number().optional(),
        fees_quote: z.number().optional(),
        controller_state_end: z.string().optional(),
        regime_end: z.string().optional(),
        risk_reasons_end: z.string().optional(),
        minute_points: z.number().optional(),
      })
      .passthrough()
      .optional(),
    hourly: z
      .array(
        z
          .object({
            hour_ts_ms: z.number().optional(),
            fill_count: z.number().optional(),
            buy_count: z.number().optional(),
            sell_count: z.number().optional(),
            maker_ratio: z.number().optional(),
            notional_quote: z.number().optional(),
            realized_pnl_quote: z.number().optional(),
          })
          .passthrough(),
      )
      .optional(),
    equity_curve: z
      .array(
        z
          .object({
            ts_ms: numberLikeSchema.optional(),
            equity_quote: numberLikeSchema.optional(),
            mid_price: numberLikeSchema.optional(),
            state: z.string().optional(),
            regime: z.string().optional(),
          })
          .passthrough(),
      )
      .optional(),
    fills: z.array(uiFillSchema).optional(),
    gate_timeline: z.array(gateTimelineEntrySchema).optional(),
  })
  .passthrough();

const weeklyReviewPayloadSchema: z.ZodType<WeeklyReviewPayload> = z
  .object({
    narrative: z.string().optional(),
    summary: z
      .object({
        period_start: z.string().optional(),
        period_end: z.string().optional(),
        n_days: z.number().optional(),
        days_with_data: z.number().optional(),
        total_net_pnl_quote: z.number().optional(),
        mean_daily_pnl_quote: z.number().optional(),
        mean_daily_net_pnl_bps: z.number().optional(),
        sharpe_annualized: z.number().optional(),
        win_rate: z.number().optional(),
        winning_days: z.number().optional(),
        losing_days: z.number().optional(),
        max_single_day_drawdown_pct: z.number().optional(),
        hard_stop_days: z.number().optional(),
        total_fills: z.number().optional(),
        spread_capture_dominant_source: z.boolean().optional(),
        dominant_source: z.string().optional(),
        dominant_regime: z.string().optional(),
        gate_pass: z.boolean().optional(),
        gate_failed_criteria: stringArraySchema.optional(),
        warnings: stringArraySchema.optional(),
      })
      .passthrough()
      .optional(),
    days: z
      .array(
        z
          .object({
            date: z.string().optional(),
            net_pnl_quote: z.number().optional(),
            net_pnl_bps: z.number().optional(),
            drawdown_pct: z.number().optional(),
            fills: z.number().optional(),
            turnover_x: z.number().optional(),
            dominant_regime: z.string().optional(),
          })
          .passthrough(),
      )
      .optional(),
    regime_breakdown: z.record(z.string(), z.number()).optional(),
  })
  .passthrough();

const journalTradeSchema = z
  .object({
    trade_id: z.string().optional(),
    entry_ts: numberLikeSchema.optional(),
    exit_ts: numberLikeSchema.optional(),
    side: z.string().optional(),
    quantity: z.number().optional(),
    avg_entry_price: z.number().optional(),
    avg_exit_price: z.number().optional(),
    hold_seconds: z.number().optional(),
    entry_regime: z.string().optional(),
    exit_regime: z.string().optional(),
    entry_state: z.string().optional(),
    exit_state: z.string().optional(),
    mfe_quote: z.number().optional(),
    mae_quote: z.number().optional(),
    risk_reasons_seen: stringArraySchema.optional(),
    fees_quote: z.number().optional(),
    exit_reason_label: z.string().optional(),
    pnl_governor_seen: z.boolean().optional(),
    order_book_stale_seen: z.boolean().optional(),
    context_source: z.string().optional(),
    realized_pnl_quote: z.number().optional(),
    fill_count: z.number().optional(),
    maker_ratio: z.number().optional(),
    fills: z
      .array(
        z
          .object({
            ts: numberLikeSchema.optional(),
            role: z.string().optional(),
            side: z.string().optional(),
            amount_base: z.number().optional(),
            price: z.number().optional(),
            notional_quote: z.number().optional(),
            fee_quote: z.number().optional(),
            realized_pnl_quote: z.number().optional(),
          })
          .passthrough(),
      )
      .optional(),
    path_points: z
      .array(
        z
          .object({
            ts: numberLikeSchema.optional(),
            mid: z.number().optional(),
            equity_quote: z.number().optional(),
            state: z.string().optional(),
            regime: z.string().optional(),
          })
          .passthrough(),
      )
      .optional(),
    path_summary: z
      .object({
        mid_open: z.number().optional(),
        mid_close: z.number().optional(),
        mid_high: z.number().optional(),
        mid_low: z.number().optional(),
        equity_open_quote: z.number().optional(),
        equity_close_quote: z.number().optional(),
        point_count: z.number().optional(),
      })
      .passthrough()
      .optional(),
    gate_timeline: z.array(gateTimelineEntrySchema).optional(),
  })
  .passthrough();

const journalReviewPayloadSchema: z.ZodType<JournalReviewPayload> = z
  .object({
    start_day: z.string().optional(),
    end_day: z.string().optional(),
    trading_pair: z.string().optional(),
    narrative: z.string().optional(),
    summary: z
      .object({
        trade_count: z.number().optional(),
        winning_trades: z.number().optional(),
        losing_trades: z.number().optional(),
        win_rate: z.number().optional(),
        realized_pnl_quote_total: z.number().optional(),
        fees_quote_total: z.number().optional(),
        avg_realized_pnl_quote: z.number().optional(),
        avg_hold_seconds: z.number().optional(),
        avg_win_quote: z.number().optional(),
        avg_loss_quote: z.number().optional(),
        avg_mfe_quote: z.number().optional(),
        avg_mae_quote: z.number().optional(),
        start_ts: numberLikeSchema.optional(),
        end_ts: numberLikeSchema.optional(),
        entry_regime_breakdown: z.record(z.string(), z.number()).optional(),
        exit_reason_breakdown: z.record(z.string(), z.number()).optional(),
      })
      .passthrough()
      .optional(),
    trades: z.array(journalTradeSchema).optional(),
  })
  .passthrough();

const healthPayloadSchema = z
  .object({
    status: z.string().optional(),
    mode: z.string().optional(),
    redis_available: z.boolean().optional(),
    db_enabled: z.boolean().optional(),
    db_available: z.boolean().optional(),
    stream_age_ms: z.number().nullable().optional(),
    fallback_active: z.boolean().optional(),
    metrics: z.record(z.string(), z.number()).optional(),
  })
  .passthrough();

const instanceStatusRowSchema = z
  .object({
    instance_name: z.string().optional(),
    freshness: z.string().optional(),
    stream_age_ms: nullableNumberLikeSchema.optional(),
    trading_pair: z.string().optional(),
    quoting_status: z.string().optional(),
    realized_pnl_quote: numberLikeSchema.optional(),
    equity_quote: numberLikeSchema.optional(),
    source_label: z.string().optional(),
    controller_id: z.string().optional(),
    orders_active: numberLikeSchema.optional(),
  })
  .passthrough();

const instancesPayloadSchema = z
  .object({
    instances: z.array(z.string()).optional(),
    statuses: z.array(instanceStatusRowSchema).optional(),
    sources: z
      .object({
        stream: z.array(z.string()).optional(),
        artifacts: z.array(z.string()).optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

const historyQualitySchema = z
  .object({
    status: z.string().optional(),
    freshness_ms: z.number().optional(),
    max_gap_s: z.number().optional(),
    coverage_ratio: z.number().optional(),
    source_used: z.string().optional(),
    degraded_reason: z.string().optional(),
    bars_returned: z.number().optional(),
    bars_requested: z.number().optional(),
  })
  .passthrough();

const historyParitySchema = z
  .object({
    bucket_count_legacy: z.number().optional(),
    bucket_count_shared: z.number().optional(),
    missing_in_shared: z.number().optional(),
    missing_in_legacy: z.number().optional(),
    mismatched_buckets: z.number().optional(),
    max_abs_close_delta: z.number().optional(),
  })
  .passthrough();

const historyPayloadSchema = z
  .object({
    mode: z.string().optional(),
    source: z.string().optional(),
    trading_pair: z.string().optional(),
    db_available: z.boolean().optional(),
    csv_failover_used: z.boolean().optional(),
    source_chain: z.array(z.string()).optional(),
    quality: historyQualitySchema.optional(),
    candles: z.array(rawCandleSchema).optional(),
    shadow: z
      .object({
        mode: z.string().optional(),
        provider: z
          .object({
            source: z.string().optional(),
            source_chain: z.array(z.string()).optional(),
            quality: historyQualitySchema.optional(),
          })
          .passthrough()
          .optional(),
        parity: historyParitySchema.optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

function formatIssuePath(path: PropertyKey[]): string {
  return path.length ? path.join(".") : "root";
}

function buildSchemaError(label: string, error: z.ZodError): Error {
  const issue = error.issues[0];
  if (!issue) {
    return new Error(`${label} payload did not match the expected schema`);
  }
  return new Error(`${label} payload invalid at ${formatIssuePath(issue.path)}: ${issue.message}`);
}

export function parseWithSchema<T>(schema: z.ZodType<T>, value: unknown, label: string): T {
  const result = schema.safeParse(value);
  if (!result.success) {
    throw buildSchemaError(label, result.error);
  }
  return result.data;
}

export async function parseJsonResponse<T>(response: Response, schema: z.ZodType<T>, label: string): Promise<T> {
  const raw = await response.json();
  return parseWithSchema(schema, raw, label);
}

export function parseWsInboundMessage(value: unknown): WsInboundMessage {
  return parseWithSchema(z.union([wsSnapshotMessageSchema, wsEventMessageSchema, wsKeepaliveMessageSchema]), value, "websocket");
}

export function parseRestStatePayload(value: unknown): RestStatePayload {
  return parseWithSchema(snapshotStatePayloadSchema, value, "state");
}

export function parseHealthPayload(value: unknown) {
  return parseWithSchema(healthPayloadSchema, value, "health");
}

export function parseInstancesPayload(value: unknown) {
  return parseWithSchema(instancesPayloadSchema, value, "instances");
}

export function parseHistoryPayload(value: unknown) {
  return parseWithSchema(historyPayloadSchema, value, "history");
}

export function parseDailyReviewResponse(value: unknown): { source?: string; review?: DailyReviewPayload; mode?: string } {
  return parseWithSchema(
    z
      .object({
        source: z.string().optional(),
        review: dailyReviewPayloadSchema.optional(),
        mode: z.string().optional(),
      })
      .passthrough(),
    value,
    "daily review",
  );
}

export function parseWeeklyReviewResponse(value: unknown): { source?: string; review?: WeeklyReviewPayload; mode?: string } {
  return parseWithSchema(
    z
      .object({
        source: z.string().optional(),
        review: weeklyReviewPayloadSchema.optional(),
        mode: z.string().optional(),
      })
      .passthrough(),
    value,
    "weekly review",
  );
}

export function parseJournalReviewResponse(value: unknown): { source?: string; review?: JournalReviewPayload; mode?: string } {
  return parseWithSchema(
    z
      .object({
        source: z.string().optional(),
        review: journalReviewPayloadSchema.optional(),
        mode: z.string().optional(),
      })
      .passthrough(),
    value,
    "journal review",
  );
}

export type HealthPayload = z.infer<typeof healthPayloadSchema>;
export type HistoryPayload = z.infer<typeof historyPayloadSchema>;
export type InstancesPayload = z.infer<typeof instancesPayloadSchema>;
export type InstanceStatusRow = z.infer<typeof instanceStatusRowSchema>;
export type ParsedPayloadRecord = PayloadRecord;
export { candleSchema };
