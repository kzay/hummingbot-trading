import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { ColorType, LineSeries, createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";

import { Panel } from "./Panel";
import { useBacktestData } from "../hooks/useBacktestData";
import type {
  BacktestEquityPoint,
  BacktestJob,
  BacktestJobStatus,
  BacktestResultSummary,
} from "../types/backtest";
import { jobLogUrl } from "../utils/backtestApi";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtNum(v: number | undefined | null, decimals = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(decimals);
}

function statusColor(s: BacktestJobStatus): string {
  switch (s) {
    case "completed": return "var(--clr-up, #26a69a)";
    case "running": return "var(--clr-warn, #ffa726)";
    case "failed":
    case "timed_out": return "var(--clr-dn, #ef5350)";
    case "cancelled": return "var(--clr-muted, #777)";
    default: return "var(--clr-muted, #777)";
  }
}

// ---------------------------------------------------------------------------
// Metric card
// ---------------------------------------------------------------------------

function MetricCard({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="bt-metric-card" style={warn ? { borderColor: "var(--clr-warn, #ffa726)" } : undefined}>
      <div className="bt-metric-label">{label}</div>
      <div className="bt-metric-value">{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Equity curve chart
// ---------------------------------------------------------------------------

function EquityCurveChart({ points }: { points: BacktestEquityPoint[] }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line", Time> | null>(null);

  useEffect(() => {
    if (!rootRef.current) return;
    const chart = createChart(rootRef.current, {
      width: rootRef.current.clientWidth,
      height: 220,
      layout: {
        background: { type: ColorType.Solid, color: "#1e1e2e" },
        textColor: "#cdd6f4",
      },
      grid: { vertLines: { color: "#313244" }, horzLines: { color: "#313244" } },
      timeScale: { timeVisible: false },
      rightPriceScale: { borderColor: "#45475a" },
    });
    const series = chart.addSeries(LineSeries, {
      color: "#89b4fa",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      if (rootRef.current) chart.applyOptions({ width: rootRef.current.clientWidth });
    });
    ro.observe(rootRef.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !points.length) return;
    const data = points.map((p) => ({
      time: p.date as Time,
      value: parseFloat(p.equity),
    }));
    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  return <div ref={rootRef} style={{ width: "100%", minHeight: 220 }} />;
}

// ---------------------------------------------------------------------------
// SSE Log panel
// ---------------------------------------------------------------------------

function LogPanel({ apiBase, token, jobId, jobStatus }: {
  apiBase: string; token: string; jobId: string; jobStatus: BacktestJobStatus;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const preRef = useRef<HTMLPreElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const url = jobLogUrl(apiBase, jobId, token);
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("log", (e) => {
      try {
        const line = JSON.parse(e.data);
        setLines((prev) => [...prev, line]);
      } catch { /* skip */ }
    });
    es.addEventListener("done", () => es.close());
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return;
      es.close();
    };
    return () => es.close();
  }, [apiBase, token, jobId]);

  useEffect(() => {
    if (!["running", "pending"].includes(jobStatus) && esRef.current) {
      esRef.current.close();
    }
  }, [jobStatus]);

  useEffect(() => {
    if (autoScroll && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!preRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = preRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }, []);

  return (
    <div style={{ position: "relative" }}>
      <pre
        ref={preRef}
        onScroll={handleScroll}
        className="bt-log-panel"
      >
        {lines.length ? lines.join("\n") : "Waiting for log output…"}
      </pre>
      {!autoScroll && (
        <button
          className="bt-scroll-btn"
          onClick={() => {
            setAutoScroll(true);
            if (preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight;
          }}
        >
          ↓ Jump to bottom
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results panel
// ---------------------------------------------------------------------------

function ResultsPanel({ result }: { result: BacktestResultSummary }) {
  return (
    <div className="bt-results">
      <div className="bt-metrics-row">
        <MetricCard label="Return" value={`${fmtNum(result.total_return_pct)}%`} />
        <MetricCard label="Sharpe" value={fmtNum(result.sharpe_ratio)} />
        <MetricCard label="Sortino" value={fmtNum(result.sortino_ratio)} />
        <MetricCard label="Calmar" value={fmtNum(result.calmar_ratio)} />
        <MetricCard label="Max DD" value={`${fmtNum(result.max_drawdown_pct)}%`} warn={result.max_drawdown_pct > 10} />
        <MetricCard label="DD Duration" value={`${result.max_drawdown_duration_days}d`} />
        <MetricCard label="Win Rate" value={`${fmtNum(result.win_rate * 100)}%`} />
        <MetricCard label="Profit Factor" value={fmtNum(result.profit_factor)} />
        <MetricCard label="Fills" value={String(result.fill_count)} />
        <MetricCard label="Maker %" value={`${fmtNum(result.maker_fill_ratio * 100)}%`} />
        <MetricCard label="Fee Drag" value={`${fmtNum(result.fee_drag_pct)}%`} />
        <MetricCard label="Inv. Half-Life" value={`${fmtNum(result.inventory_half_life_minutes, 0)}m`} />
      </div>

      {result.equity_curve?.length > 0 && (
        <EquityCurveChart points={result.equity_curve} />
      )}

      {result.fill_disclaimer && (
        <div className="bt-fill-disclaimer">{result.fill_disclaimer}</div>
      )}

      {result.warnings?.length > 0 && (
        <div className="bt-warnings">
          {result.warnings.map((w, i) => (
            <div key={i} className="bt-warning-badge">{w}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Job history table
// ---------------------------------------------------------------------------

function JobHistoryTable({ jobs, onSelect }: {
  jobs: BacktestJob[];
  onSelect: (job: BacktestJob) => void;
}) {
  if (!jobs.length) return <div className="panel-empty">No past jobs</div>;

  return (
    <div className="bt-history-scroll">
      <table className="bt-history-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Preset</th>
            <th>Status</th>
            <th>Return</th>
            <th>Sharpe</th>
            <th>Max DD</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr
              key={j.id}
              onClick={() => onSelect(j)}
              style={{ cursor: "pointer" }}
            >
              <td>{j.created_at?.slice(0, 16).replace("T", " ")}</td>
              <td>{j.preset_id}</td>
              <td>
                <span className="bt-status-badge" style={{ background: statusColor(j.status) }}>
                  {j.status === "running" ? `${j.status} ${fmtNum(j.progress_pct, 0)}%` : j.status}
                </span>
              </td>
              <td>{j.result_summary ? `${fmtNum(j.result_summary.total_return_pct)}%` : "—"}</td>
              <td>{j.result_summary ? fmtNum(j.result_summary.sharpe_ratio) : "—"}</td>
              <td>{j.result_summary ? `${fmtNum(j.result_summary.max_drawdown_pct)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BacktestPage — main component
// ---------------------------------------------------------------------------

export function BacktestPage() {
  const {
    apiBase, apiToken,
    presets, selectedPreset, setSelectedPreset,
    overrides, setOverrides,
    currentJob, viewedResult, history,
    error, isRunning,
    handleRun, handleCancel, handleHistorySelect,
  } = useBacktestData();

  const progressPct = currentJob?.progress_pct ?? 0;
  const progressColor = currentJob?.status === "completed"
    ? "var(--clr-up, #26a69a)"
    : currentJob?.status === "failed" || currentJob?.status === "timed_out"
      ? "var(--clr-dn, #ef5350)"
      : "var(--clr-accent, #89b4fa)";

  return (
    <>
      {/* Run Panel */}
      <Panel title="Backtest" className="panel-span-12">
        <div className="bt-run-panel">
          <div className="bt-controls">
            <label>
              Preset
              <select
                value={selectedPreset}
                onChange={(e) => setSelectedPreset(e.target.value)}
                disabled={isRunning}
              >
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} — {p.pair} {p.resolution} ({p.mode === "replay" ? "replay" : "adapter"})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Equity
              <input
                type="number"
                value={overrides.initial_equity ?? ""}
                onChange={(e) => setOverrides((o) => ({ ...o, initial_equity: e.target.value }))}
                disabled={isRunning}
                min={50}
                max={100000}
              />
            </label>
            <label>
              Start
              <input
                type="date"
                value={overrides.start_date ?? ""}
                onChange={(e) => setOverrides((o) => ({ ...o, start_date: e.target.value }))}
                disabled={isRunning}
              />
            </label>
            <label>
              End
              <input
                type="date"
                value={overrides.end_date ?? ""}
                onChange={(e) => setOverrides((o) => ({ ...o, end_date: e.target.value }))}
                disabled={isRunning}
              />
            </label>
            <div className="bt-action-btns">
              <button className="bt-btn bt-btn-run" onClick={handleRun} disabled={isRunning || !selectedPreset}>
                Run
              </button>
              {isRunning && (
                <button className="bt-btn bt-btn-cancel" onClick={handleCancel}>Cancel</button>
              )}
            </div>
          </div>

          {/* Progress bar */}
          {currentJob && (
            <div className="bt-progress-wrap">
              <div className="bt-progress-bar">
                <div
                  className="bt-progress-fill"
                  style={{ width: `${progressPct}%`, background: progressColor }}
                />
              </div>
              <span className="bt-progress-label">
                <span className="bt-job-id" title="Job id">
                  {currentJob.id}
                </span>
                <span className="bt-job-sep"> · </span>
                {currentJob.status === "running"
                  ? `${fmtNum(progressPct, 0)}%`
                  : currentJob.status === "pending"
                    ? "starting…"
                    : currentJob.status}
              </span>
            </div>
          )}

          {error && <div className="panel-error" role="alert">{error}</div>}
        </div>
      </Panel>

      {/* Log + Results */}
      {currentJob && currentJob.id?.trim() && (
        <Panel title="Log" className="panel-span-6">
          <LogPanel
            key={currentJob.id}
            apiBase={apiBase}
            token={apiToken}
            jobId={currentJob.id}
            jobStatus={currentJob.status}
          />
        </Panel>
      )}
      {currentJob && !currentJob.id?.trim() && (
        <Panel title="Log" className="panel-span-6">
          <div className="panel-error" role="alert">
            Job id missing — use a hard refresh or redeploy realtime-ui-web so the backtest fix is loaded.
          </div>
        </Panel>
      )}

      {viewedResult && (
        <Panel title="Results" className="panel-span-6">
          <ResultsPanel result={viewedResult} />
        </Panel>
      )}

      {/* Job History */}
      <Panel title="Job History" className="panel-span-12">
        <JobHistoryTable jobs={history} onSelect={handleHistorySelect} />
      </Panel>
    </>
  );
}
