import { z } from "zod";

import type { UiCandle, UiDepth, UiDepthLevel, UiMarket } from "../../types/realtime";

export const numberLikeSchema = z.union([z.number(), z.string()]);
export const nullableNumberLikeSchema = z.union([z.number(), z.string(), z.null()]);
export const stringArraySchema = z.array(z.string());
export const unknownRecordSchema = z.record(z.string(), z.unknown());

export const keySchema = z
  .object({
    instance_name: z.string().optional(),
    instance: z.string().optional(),
    controller_id: z.string().optional(),
    controller: z.string().optional(),
    trading_pair: z.string().optional(),
    pair: z.string().optional(),
  })
  .passthrough();

export const uiDepthLevelSchema: z.ZodType<UiDepthLevel> = z
  .object({
    price: numberLikeSchema.optional(),
    size: numberLikeSchema.optional(),
  })
  .passthrough();

export const uiMarketSchema: z.ZodType<UiMarket> = z
  .object({
    mid_price: numberLikeSchema.optional(),
    best_bid: numberLikeSchema.optional(),
    best_ask: numberLikeSchema.optional(),
    trading_pair: z.string().optional(),
    ts: z.string().optional(),
    timestamp_ms: numberLikeSchema.optional(),
  })
  .passthrough();

export const uiDepthSchema: z.ZodType<UiDepth> = z
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

export const candleSchema: z.ZodType<UiCandle> = z.object({
  time: z.number(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
});

export const rawCandleSchema = z
  .object({
    bucket_ms: numberLikeSchema.optional(),
    open: numberLikeSchema.optional(),
    high: numberLikeSchema.optional(),
    low: numberLikeSchema.optional(),
    close: numberLikeSchema.optional(),
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
  const result = z.safeParse(schema, value);
  if (!result.success) {
    throw buildSchemaError(label, result.error);
  }
  return result.data;
}

export async function parseJsonResponse<T>(response: Response, schema: z.ZodType<T>, label: string): Promise<T> {
  const raw = await response.json();
  return parseWithSchema(schema, raw, label);
}

export function parseHistoryPayload(value: unknown) {
  return parseWithSchema(historyPayloadSchema, value, "history");
}

export type HistoryPayload = z.infer<typeof historyPayloadSchema>;
