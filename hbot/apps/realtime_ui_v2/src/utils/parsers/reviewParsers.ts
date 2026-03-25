import { z } from "zod";

import type { DailyReviewPayload, JournalReviewPayload, WeeklyReviewPayload } from "../../types/realtime";

import { numberLikeSchema, parseWithSchema, stringArraySchema } from "./marketParsers";
import { gateTimelineEntrySchema, uiFillSchema } from "./telemetryParsers";

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
