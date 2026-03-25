import { z } from "zod";
import type { BacktestJob, BacktestPreset, BacktestResultSummary } from "../types/backtest";
import { buildHeaders, fetchWithTimeout } from "./fetch";

const BacktestJobStatusSchema = z.enum([
  "pending", "running", "completed", "failed", "cancelled", "timed_out",
]);

const BacktestEquityPointSchema = z.object({
  date: z.string(),
  equity: z.string(),
  drawdown_pct: z.string(),
  daily_return_pct: z.string(),
});

const BacktestResultSummarySchema = z.object({
  total_return_pct: z.number(),
  sharpe_ratio: z.number(),
  sortino_ratio: z.number(),
  calmar_ratio: z.number(),
  max_drawdown_pct: z.number(),
  max_drawdown_duration_days: z.number(),
  cagr_pct: z.number(),
  fill_count: z.number(),
  order_count: z.number(),
  total_ticks: z.number(),
  win_rate: z.number(),
  profit_factor: z.number(),
  total_fees: z.string(),
  maker_fill_ratio: z.number(),
  fee_drag_pct: z.number(),
  avg_slippage_bps: z.number(),
  spread_capture_efficiency: z.number(),
  inventory_half_life_minutes: z.number(),
  run_duration_s: z.number(),
  warnings: z.array(z.string()),
  equity_curve: z.array(BacktestEquityPointSchema),
  config: z.record(z.string(), z.unknown()),
  fill_disclaimer: z.string().optional(),
});

const BacktestPresetSchema = z.object({
  id: z.string(),
  label: z.string(),
  strategy: z.string(),
  pair: z.string(),
  resolution: z.string(),
  initial_equity: z.number(),
  start_date: z.string(),
  end_date: z.string(),
  mode: z.string().optional(),
});

function url(apiBase: string, path: string): string {
  return `${apiBase.replace(/\/$/, "")}${path}`;
}

/** API historically returned ``job_id`` on POST create; normalize so polling and SSE use ``id``. */
export function normalizeBacktestJob(raw: Record<string, unknown>): BacktestJob {
  const id = String(raw.id ?? raw.job_id ?? "").trim();
  if (!id) {
    throw new Error("Invalid job response: missing id");
  }
  const statusResult = z.safeParse(BacktestJobStatusSchema, raw.status ?? "pending");
  const status = statusResult.success ? statusResult.data : "pending" as const;
  const resultRaw = raw.result_summary;
  let resultSummary: BacktestResultSummary | null = null;
  if (resultRaw != null && typeof resultRaw === "object") {
    const parsed = z.safeParse(BacktestResultSummarySchema, resultRaw);
    if (parsed.success) resultSummary = parsed.data;
  }
  return {
    id,
    preset_id: String(raw.preset_id ?? ""),
    overrides: (raw.overrides as Record<string, unknown>) ?? undefined,
    status,
    progress_pct: Number(raw.progress_pct ?? 0) || 0,
    created_at: String(raw.created_at ?? ""),
    updated_at: raw.updated_at != null ? String(raw.updated_at) : undefined,
    result_summary: resultSummary,
    error: raw.error != null ? String(raw.error) : null,
  };
}

export async function fetchPresets(
  apiBase: string,
  token: string,
): Promise<BacktestPreset[]> {
  const res = await fetchWithTimeout(url(apiBase, "/api/backtest/presets"), {
    headers: buildHeaders(token),
  });
  if (!res.ok) throw new Error(`Preset fetch failed: ${res.status}`);
  const data = await res.json();
  return z.parse(z.array(BacktestPresetSchema), data.presets ?? []) as BacktestPreset[];
}

export async function createJob(
  apiBase: string,
  token: string,
  presetId: string,
  overrides: Record<string, unknown>,
): Promise<BacktestJob> {
  const res = await fetchWithTimeout(url(apiBase, "/api/backtest/jobs"), {
    method: "POST",
    headers: buildHeaders(token),
    body: JSON.stringify({ preset_id: presetId, overrides }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Job creation failed: ${res.status}`);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  return normalizeBacktestJob(raw);
}

export async function fetchJobStatus(
  apiBase: string,
  token: string,
  jobId: string,
): Promise<BacktestJob> {
  const id = (jobId || "").trim();
  if (!id) {
    throw new Error("Missing backtest job id");
  }
  const res = await fetchWithTimeout(url(apiBase, `/api/backtest/jobs/${id}`), {
    headers: buildHeaders(token),
  });
  if (!res.ok) throw new Error(`Job status failed: ${res.status}`);
  const raw = (await res.json()) as Record<string, unknown>;
  return normalizeBacktestJob(raw);
}

export async function cancelJob(
  apiBase: string,
  token: string,
  jobId: string,
): Promise<void> {
  const res = await fetchWithTimeout(url(apiBase, `/api/backtest/jobs/${jobId}/cancel`), {
    method: "POST",
    headers: buildHeaders(token),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Cancel failed: ${res.status}`);
  }
}

export async function fetchJobHistory(
  apiBase: string,
  token: string,
  limit = 50,
): Promise<BacktestJob[]> {
  const res = await fetchWithTimeout(url(apiBase, `/api/backtest/jobs?limit=${limit}`), {
    headers: buildHeaders(token),
  });
  if (!res.ok) throw new Error(`Job history failed: ${res.status}`);
  const data = (await res.json()) as { jobs?: Record<string, unknown>[] };
  const jobs = data.jobs ?? [];
  const out: BacktestJob[] = [];
  for (const row of jobs) {
    try {
      out.push(normalizeBacktestJob(row));
    } catch {
      /* skip malformed rows */
    }
  }
  return out;
}

export function jobLogUrl(apiBase: string, jobId: string, token: string): string {
  const id = (jobId || "").trim();
  const base = url(apiBase, `/api/backtest/jobs/${id}/log`);
  return token.trim() ? `${base}?token=${encodeURIComponent(token.trim())}` : base;
}
