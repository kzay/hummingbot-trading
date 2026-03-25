import { z } from "zod";

import type {
  RestStatePayload,
  SummaryAccount,
  SummaryActivity,
  SummaryAlert,
  SummarySystem,
  UiFill,
  UiOrder,
  UiPosition,
  WsEventMessage,
  WsInboundMessage,
  WsKeepaliveMessage,
  WsSnapshotMessage,
} from "../../types/realtime";

import {
  keySchema,
  nullableNumberLikeSchema,
  numberLikeSchema,
  parseWithSchema,
  rawCandleSchema,
  uiDepthSchema,
  uiMarketSchema,
  unknownRecordSchema,
} from "./marketParsers";

export const uiPositionSchema: z.ZodType<UiPosition> = z
  .object({
    quantity: numberLikeSchema.optional(),
    side: z.string().optional(),
    avg_entry_price: numberLikeSchema.optional(),
    unrealized_pnl: numberLikeSchema.optional(),
    source_ts_ms: numberLikeSchema.optional(),
    trading_pair: z.string().optional(),
  })
  .passthrough();

export const uiOrderSchema: z.ZodType<UiOrder> = z
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

export const uiFillSchema: z.ZodType<UiFill> = z
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

export const gateTimelineEntrySchema = z
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
    unrealized_pnl_quote: numberLikeSchema.optional(),
    equity_quote: numberLikeSchema.optional(),
    equity_open_quote: numberLikeSchema.optional(),
    equity_delta_open_quote: numberLikeSchema.optional(),
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

const HIGH_FREQ_FAST_PATH_TYPES = new Set(["market_quote", "market_depth_snapshot"]);

export function parseWsInboundMessage(value: unknown): WsInboundMessage {
  if (
    value != null &&
    typeof value === "object" &&
    "type" in value &&
    (value as Record<string, unknown>).type === "event"
  ) {
    const eventType = (value as Record<string, unknown>).event_type;
    if (typeof eventType === "string" && HIGH_FREQ_FAST_PATH_TYPES.has(eventType)) {
      return value as WsEventMessage;
    }
  }
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

export type HealthPayload = z.infer<typeof healthPayloadSchema>;
export type InstancesPayload = z.infer<typeof instancesPayloadSchema>;
export type InstanceStatusRow = z.infer<typeof instanceStatusRowSchema>;
