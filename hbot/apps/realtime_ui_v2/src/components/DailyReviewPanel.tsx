import { memo, useEffect, useMemo, useRef } from "react";
import { ColorType, LineSeries, createChart, type IChartApi, type ISeriesApi, type LineData, type Time } from "lightweight-charts";

import type { DailyReviewPayload } from "../types/realtime";
import { formatNumber, formatPct, formatRelativeTs, formatSigned, formatTs } from "../utils/format";
import { gateTone, sideTone, signedClass } from "../utils/presentation";
import { GateTimelineTable } from "./GateTimelineTable";
import { Panel } from "./Panel";

function EquityCurveChart({ points }: { points: NonNullable<DailyReviewPayload["equity_curve"]> }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line", Time> | null>(null);
  const lineData = useMemo(
    () =>
      points
        .map((point) => {
          const time = Math.floor(Number(point.ts_ms ?? 0) / 1000);
          const value = Number(point.equity_quote ?? 0);
          if (!Number.isFinite(time) || time <= 0 || !Number.isFinite(value)) {
            return null;
          }
          return { time: time as Time, value };
        })
        .filter(Boolean) as LineData<Time>[],
    [points],
  );

  useEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }
    const chart = createChart(root, {
      layout: {
        background: { type: ColorType.Solid, color: "#121a28" },
        textColor: "#dce3f0",
      },
      grid: {
        vertLines: { color: "#273244" },
        horzLines: { color: "#273244" },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#3c4555",
      },
      rightPriceScale: {
        borderColor: "#3c4555",
      },
      width: Math.max(320, root.clientWidth),
      height: Math.max(220, root.clientHeight || 260),
    });
    const series = chart.addSeries(LineSeries, {
      color: "#5ea7ff",
      lineWidth: 2,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const resize = () => {
      chart.applyOptions({
        width: Math.max(320, root.clientWidth),
        height: Math.max(220, root.clientHeight || 260),
      });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) {
      return;
    }
    seriesRef.current.setData(lineData);
  }, [lineData]);

  return <div ref={rootRef} className="review-chart-root" />;
}

interface DailyReviewState {
  source: string;
  review: DailyReviewPayload | null;
  error: string;
  loading: boolean;
}

interface DailyReviewPanelProps {
  day: string;
  onDayChange: (day: string) => void;
  onRefresh: () => void;
  state: DailyReviewState;
}

export const DailyReviewPanel = memo(function DailyReviewPanel({ day, onDayChange, onRefresh, state }: DailyReviewPanelProps) {
  const payload = state.review || {};
  const summary = payload.summary || {};
  const fills = Array.isArray(payload.fills) ? payload.fills : [];
  const hourly = Array.isArray(payload.hourly) ? payload.hourly : [];
  const gateTimeline = Array.isArray(payload.gate_timeline) ? payload.gate_timeline : [];
  const equityCurve = Array.isArray(payload.equity_curve) ? payload.equity_curve : [];

  return (
    <>
      <Panel title="Daily Review" subtitle="Selected day summary, hourly activity, and fills." className="panel-span-12">
        <div className="panel-toolbar">
          <label>
            Day
            <input type="date" value={day} onChange={(event) => onDayChange(event.target.value)} />
          </label>
          <button type="button" onClick={onRefresh}>
            {state.loading ? "Loading..." : "Load day"}
          </button>
        </div>
        <div className="panel-meta-row">
          <span className="meta-pill">Source {state.source || "n/a"}</span>
          <span className="meta-pill">Day {String(payload.day || day || "n/a")}</span>
          <span className="meta-pill">Pair {String(payload.trading_pair || "n/a")}</span>
        </div>
        <p className="panel-subtitle">{state.error || payload.narrative || "No daily review loaded."}</p>
      </Panel>

      <Panel title="Session Summary" subtitle="Equity and execution stats for the selected day." className="panel-span-12">
        <div className="summary-grid summary-grid-2">
          <article className="summary-card">
            <h3>Session</h3>
            <div className={`summary-value ${signedClass(summary.realized_pnl_day_quote)}`}>{formatSigned(summary.realized_pnl_day_quote, 4)}</div>
            <dl>
              <dt>Open Equity</dt>
              <dd>{formatNumber(summary.equity_open_quote, 4)}</dd>
              <dt>Close Equity</dt>
              <dd>{formatNumber(summary.equity_close_quote, 4)}</dd>
              <dt>High / Low</dt>
              <dd>
                {formatNumber(summary.equity_high_quote, 4)} / {formatNumber(summary.equity_low_quote, 4)}
              </dd>
              <dt>Unrealized EOD</dt>
              <dd className={signedClass(summary.unrealized_pnl_end_quote)}>{formatSigned(summary.unrealized_pnl_end_quote, 4)}</dd>
              <dt>Quote Balance</dt>
              <dd>{formatNumber(summary.quote_balance_end_quote, 4)}</dd>
              <dt>Minute Points</dt>
              <dd>{String(summary.minute_points || 0)}</dd>
            </dl>
          </article>

          <article className="summary-card">
            <h3>Execution</h3>
            <div className="summary-value">{String(summary.fill_count || 0)} fills</div>
            <dl>
              <dt>Maker Ratio</dt>
              <dd>{formatPct(summary.maker_ratio || 0, 1)}</dd>
              <dt>Buy / Sell</dt>
              <dd>
                {String(summary.buy_count || 0)} / {String(summary.sell_count || 0)}
              </dd>
              <dt>Notional</dt>
              <dd>{formatNumber(summary.notional_quote, 2)}</dd>
              <dt>Fees</dt>
              <dd>{formatNumber(summary.fees_quote, 4)}</dd>
              <dt>Controller State</dt>
              <dd>
                <span className={`pill ${gateTone(String(summary.controller_state_end || ""))}`}>{String(summary.controller_state_end || "n/a")}</span>
              </dd>
              <dt>Regime</dt>
              <dd>{String(summary.regime_end || "n/a").replaceAll("_", " ")}</dd>
              <dt>Risk</dt>
              <dd>{String(summary.risk_reasons_end || "none")}</dd>
            </dl>
          </article>
        </div>
      </Panel>

      <Panel title="Equity Curve" subtitle="Intraday equity progression for the selected day." className="panel-span-12">
        {equityCurve.length === 0 ? (
          <div className="empty-state">No equity curve available for this day.</div>
        ) : (
          <EquityCurveChart points={equityCurve} />
        )}
      </Panel>

      <Panel title="Hourly Activity" subtitle="Intraday fill flow and realized PnL by hour." className="panel-span-6">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Hour</th>
                <th scope="col">Fills</th>
                <th scope="col">Buy / Sell</th>
                <th scope="col">Maker</th>
                <th scope="col">Notional</th>
                <th scope="col">Realized</th>
              </tr>
            </thead>
            <tbody>
              {hourly.length === 0 ? (
                <tr>
                  <td colSpan={6}>No hourly activity available for this day.</td>
                </tr>
              ) : (
                hourly.map((bucket, index) => (
                  <tr key={`hour-${bucket.hour_ts_ms || index}`}>
                    <td>{formatTs(bucket.hour_ts_ms)}</td>
                    <td>{String(bucket.fill_count || 0)}</td>
                    <td>
                      {String(bucket.buy_count || 0)} / {String(bucket.sell_count || 0)}
                    </td>
                    <td>{formatPct(bucket.maker_ratio || 0, 1)}</td>
                    <td>{formatNumber(bucket.notional_quote || 0, 2)}</td>
                    <td className={signedClass(bucket.realized_pnl_quote || 0)}>{formatSigned(bucket.realized_pnl_quote || 0, 4)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Day Fills" subtitle="Fill tape for the selected trading day." className="panel-span-6">
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Side</th>
                <th scope="col">Price</th>
                <th scope="col">Amount</th>
                <th scope="col">Notional</th>
                <th scope="col">Fee</th>
                <th scope="col">Realized</th>
                <th scope="col">Order</th>
              </tr>
            </thead>
            <tbody>
              {fills.length === 0 ? (
                <tr>
                  <td colSpan={8}>No fills available for this day.</td>
                </tr>
              ) : (
                fills
                  .slice()
                  .reverse()
                  .map((fill, index) => {
                    const notional = Number(fill.notional_quote || 0) || Math.abs(Number(fill.amount_base || 0)) * Number(fill.price || 0);
                    return (
                      <tr key={`${fill.order_id || "order"}-${fill.timestamp_ms || index}`}>
                        <td>
                          <div>{fill.ts || formatTs(fill.timestamp_ms)}</div>
                          <div className="subvalue">{formatRelativeTs(fill.timestamp_ms)}</div>
                        </td>
                        <td>
                          <span className={`pill ${sideTone(String(fill.side || ""))}`}>{String(fill.side || "")}</span>
                        </td>
                        <td>{formatNumber(fill.price, 4)}</td>
                        <td>{formatNumber(fill.amount_base, 6)}</td>
                        <td>{formatNumber(notional, 2)}</td>
                        <td>{formatNumber(fill.fee_quote, 4)}</td>
                        <td className={signedClass(fill.realized_pnl_quote)}>{formatSigned(fill.realized_pnl_quote, 4)}</td>
                        <td className="mono">{String(fill.order_id || "")}</td>
                      </tr>
                    );
                  })
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Bot Gate Timeline" subtitle="Quoting / waiting / limited / blocked transitions across the selected day." className="panel-span-12">
        <GateTimelineTable rows={gateTimeline} emptyMessage="No gate transitions available for this day." />
      </Panel>
    </>
  );
});
