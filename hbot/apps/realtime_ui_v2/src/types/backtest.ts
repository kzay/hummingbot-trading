export interface BacktestPreset {
  id: string;
  label: string;
  strategy: string;
  pair: string;
  resolution: string;
  initial_equity: number;
  start_date: string;
  end_date: string;
  mode?: string;
}

export type BacktestJobStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out";

export interface BacktestEquityPoint {
  date: string;
  equity: string;
  drawdown_pct: string;
  daily_return_pct: string;
}

export interface BacktestResultSummary {
  total_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_duration_days: number;
  cagr_pct: number;
  fill_count: number;
  order_count: number;
  total_ticks: number;
  win_rate: number;
  profit_factor: number;
  total_fees: string;
  maker_fill_ratio: number;
  fee_drag_pct: number;
  avg_slippage_bps: number;
  spread_capture_efficiency: number;
  inventory_half_life_minutes: number;
  run_duration_s: number;
  warnings: string[];
  equity_curve: BacktestEquityPoint[];
  config: Record<string, unknown>;
  fill_disclaimer?: string;
}

export interface BacktestJob {
  id: string;
  preset_id: string;
  overrides?: Record<string, unknown>;
  status: BacktestJobStatus;
  progress_pct: number;
  created_at: string;
  updated_at?: string;
  result_summary: BacktestResultSummary | null;
  error: string | null;
}
