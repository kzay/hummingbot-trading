import { memo } from "react";
import type { WeeklyReviewPayload } from "../types/realtime";
import { formatNumber, formatPct, formatSigned } from "../utils/format";
import { signedClass } from "../utils/presentation";
import { Panel } from "./Panel";

interface WeeklyReviewState {
  source: string;
  review: WeeklyReviewPayload | null;
  error: string;
  loading: boolean;
}

interface WeeklyReviewPanelProps {
  state: WeeklyReviewState;
  onRefresh: () => void;
}

export const WeeklyReviewPanel = memo(function WeeklyReviewPanel({ state, onRefresh }: WeeklyReviewPanelProps) {
  const payload = state.review || {};
  const summary = payload.summary || {};
  const days = Array.isArray(payload.days) ? payload.days : [];
  const regimeBreakdown = payload.regime_breakdown || {};
  const regimeTotal = Object.values(regimeBreakdown).reduce((acc, value) => acc + (Number(value) || 0), 0);
  const regimeLeader = Object.entries(regimeBreakdown)
    .sort((left, right) => (Number(right[1]) || 0) - (Number(left[1]) || 0))
    .slice(0, 3)
    .map(([name, count]) => `${String(name || "n/a").replaceAll("_", " ")} ${regimeTotal > 0 ? formatPct((Number(count) || 0) / regimeTotal, 1) : "0.0%"}`)
    .join(" · ");
  const regimeRows = Object.entries(regimeBreakdown)
    .sort((left, right) => (Number(right[1]) || 0) - (Number(left[1]) || 0))
    .slice(0, 6);

  return (
    <>
      <Panel title="Weekly Review" subtitle="Multi-day strategy review sourced from promotion/report artifacts." className="panel-span-12">
        <div className="panel-toolbar">
          <button type="button" onClick={onRefresh}>
            {state.loading ? "Loading..." : "Load weekly review"}
          </button>
        </div>
        <div className="panel-meta-row">
          <span className="meta-pill">Source {state.source || "n/a"}</span>
          <span className="meta-pill">
            Window {String(summary.period_start || "n/a")} → {String(summary.period_end || "n/a")}
          </span>
          <span className="meta-pill">
            Days {String(summary.days_with_data || 0)} / {String(summary.n_days || 0)}
          </span>
        </div>
        <p className="panel-subtitle">{state.error || payload.narrative || "No weekly review loaded."}</p>
      </Panel>

      <Panel title="Weekly Summary" subtitle="Performance, risk/gates, and regime composition." className="panel-span-12">
        <div className="summary-grid summary-grid-3">
          <article className="summary-card">
            <h3>Performance</h3>
            <div className={`summary-value ${signedClass(summary.total_net_pnl_quote)}`}>{formatSigned(summary.total_net_pnl_quote, 4)}</div>
            <dl>
              <dt>Mean / Day</dt>
              <dd className={signedClass(summary.mean_daily_pnl_quote)}>{formatSigned(summary.mean_daily_pnl_quote, 4)}</dd>
              <dt>Mean Bps</dt>
              <dd className={signedClass(summary.mean_daily_net_pnl_bps)}>{formatSigned(summary.mean_daily_net_pnl_bps, 2)}</dd>
              <dt>Sharpe</dt>
              <dd>{formatNumber(summary.sharpe_annualized, 3)}</dd>
              <dt>Win Rate</dt>
              <dd>{formatPct(summary.win_rate || 0, 1)}</dd>
              <dt>Winning / Losing</dt>
              <dd>
                {String(summary.winning_days || 0)} / {String(summary.losing_days || 0)}
              </dd>
              <dt>Total Fills</dt>
              <dd>{String(summary.total_fills || 0)}</dd>
            </dl>
          </article>

          <article className="summary-card">
            <h3>Risk / Gate</h3>
            <div className="summary-value">
              <span className={`pill ${summary.gate_pass ? "ok" : "fail"}`}>{summary.gate_pass ? "pass" : "fail"}</span>
            </div>
            <dl>
              <dt>Max DD</dt>
              <dd>{formatPct(summary.max_single_day_drawdown_pct || 0, 2)}</dd>
              <dt>Hard Stop Days</dt>
              <dd>{String(summary.hard_stop_days || 0)}</dd>
              <dt>Dominant Source</dt>
              <dd>{String(summary.dominant_source || "n/a")}</dd>
              <dt>Spread Capture</dt>
              <dd>{summary.spread_capture_dominant_source ? "dominant" : "not dominant"}</dd>
              <dt>Dominant Regime</dt>
              <dd>{String(summary.dominant_regime || "n/a").replaceAll("_", " ")}</dd>
              <dt>Failed Criteria</dt>
              <dd>
                {Array.isArray(summary.gate_failed_criteria) && summary.gate_failed_criteria.length > 0
                  ? summary.gate_failed_criteria.join(", ")
                  : "none"}
              </dd>
            </dl>
          </article>

          <article className="summary-card">
            <h3>Warnings / Regimes</h3>
            <div className="summary-value">{Array.isArray(summary.warnings) ? summary.warnings.length : 0} warnings</div>
            <dl>
              <dt>Regime Mix</dt>
              <dd>{regimeLeader || "n/a"}</dd>
              <dt>Warnings</dt>
              <dd>{Array.isArray(summary.warnings) && summary.warnings.length ? summary.warnings.join(", ") : "none"}</dd>
              <dt>Window Start</dt>
              <dd>{String(summary.period_start || "n/a")}</dd>
              <dt>Window End</dt>
              <dd>{String(summary.period_end || "n/a")}</dd>
            </dl>
          </article>
        </div>
      </Panel>

      <Panel title="Regime Breakdown" subtitle="Most frequent regimes across the review window." className="panel-span-6">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Regime</th>
                <th scope="col">Count</th>
                <th scope="col">Share</th>
              </tr>
            </thead>
            <tbody>
              {regimeRows.length === 0 ? (
                <tr>
                  <td colSpan={3}>No regime mix available.</td>
                </tr>
              ) : (
                regimeRows.map(([name, count]) => (
                  <tr key={name}>
                    <td>{String(name || "n/a").replaceAll("_", " ")}</td>
                    <td>{formatNumber(count, 0)}</td>
                    <td>{regimeTotal > 0 ? formatPct((Number(count) || 0) / regimeTotal, 1) : "0.0%"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Gate Notes" subtitle="Warnings and failed criteria that need follow-up." className="panel-span-6">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Type</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {[
                ...(Array.isArray(summary.gate_failed_criteria) ? summary.gate_failed_criteria.map((item) => ["failed", item]) : []),
                ...(Array.isArray(summary.warnings) ? summary.warnings.map((item) => ["warning", item]) : []),
              ].length === 0 ? (
                <tr>
                  <td colSpan={2}>No warnings or failed criteria.</td>
                </tr>
              ) : (
                [
                  ...(Array.isArray(summary.gate_failed_criteria) ? summary.gate_failed_criteria.map((item) => ["failed", item]) : []),
                  ...(Array.isArray(summary.warnings) ? summary.warnings.map((item) => ["warning", item]) : []),
                ].map(([kind, detail], index) => (
                  <tr key={`${kind}-${index}`}>
                    <td>{String(kind)}</td>
                    <td>{String(detail || "")}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Daily Breakdown" subtitle="Day-by-day performance, drawdown, and dominant regime." className="panel-span-12">
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Net PnL</th>
                <th scope="col">Bps</th>
                <th scope="col">Drawdown</th>
                <th scope="col">Fills</th>
                <th scope="col">Turnover</th>
                <th scope="col">Regime</th>
              </tr>
            </thead>
            <tbody>
              {days.length === 0 ? (
                <tr>
                  <td colSpan={7}>No weekly breakdown available.</td>
                </tr>
              ) : (
                days.map((day, index) => (
                  <tr key={`${day.date || "day"}-${index}`}>
                    <td>{String(day.date || "")}</td>
                    <td className={signedClass(day.net_pnl_quote || 0)}>{formatSigned(day.net_pnl_quote || 0, 4)}</td>
                    <td className={signedClass(day.net_pnl_bps || 0)}>{formatSigned(day.net_pnl_bps || 0, 2)}</td>
                    <td>{formatPct(day.drawdown_pct || 0, 2)}</td>
                    <td>{String(day.fills || 0)}</td>
                    <td>{formatNumber(day.turnover_x || 0, 3)}</td>
                    <td>{String(day.dominant_regime || "n/a").replaceAll("_", " ")}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
});
