import { memo } from "react";
import type { JournalReviewPayload, JournalTrade } from "../types/realtime";
import { formatAgeMs, formatNumber, formatPct, formatRelativeTs, formatSigned, formatTs } from "../utils/format";
import { sideTone, signedClass } from "../utils/presentation";
import { GateTimelineTable } from "./GateTimelineTable";
import { Panel } from "./Panel";

interface JournalReviewState {
  source: string;
  review: JournalReviewPayload | null;
  error: string;
  loading: boolean;
}

interface JournalReviewPanelProps {
  state: JournalReviewState;
  startDay: string;
  endDay: string;
  onStartDayChange: (day: string) => void;
  onEndDayChange: (day: string) => void;
  onRefresh: () => void;
  selectedTradeId: string;
  onSelectTrade: (tradeId: string) => void;
  selectedTrade: JournalTrade | null;
}

export const JournalReviewPanel = memo(function JournalReviewPanel({
  state,
  startDay,
  endDay,
  onStartDayChange,
  onEndDayChange,
  onRefresh,
  selectedTradeId,
  onSelectTrade,
  selectedTrade,
}: JournalReviewPanelProps) {
  const payload = state.review || {};
  const summary = payload.summary || {};
  const trades = Array.isArray(payload.trades) ? payload.trades : [];

  const entryRegimes = summary.entry_regime_breakdown || {};
  const exitReasons = summary.exit_reason_breakdown || {};
  const topEntryRegimes = Object.entries(entryRegimes)
    .sort((left, right) => (Number(right[1]) || 0) - (Number(left[1]) || 0))
    .slice(0, 3)
    .map(([name, count]) => `${String(name || "unknown").replaceAll("_", " ")} ${count}`)
    .join(" · ");
  const topExitReasons = Object.entries(exitReasons)
    .sort((left, right) => (Number(right[1]) || 0) - (Number(left[1]) || 0))
    .slice(0, 3)
    .map(([name, count]) => `${String(name || "unknown")} ${count}`)
    .join(" · ");

  const selectedFills = Array.isArray(selectedTrade?.fills) ? selectedTrade.fills : [];
  const selectedPath = Array.isArray(selectedTrade?.path_points) ? selectedTrade.path_points : [];
  const selectedGateTimeline = Array.isArray(selectedTrade?.gate_timeline) ? selectedTrade.gate_timeline : [];
  const pathSummary = selectedTrade?.path_summary || {};

  return (
    <>
      <Panel title="Trade Journal" subtitle="Closed-trade journal reconstructed from fills with optional date range." className="panel-span-12">
        <div className="panel-toolbar">
          <label>
            Start
            <input type="date" value={startDay} onChange={(event) => onStartDayChange(event.target.value)} />
          </label>
          <label>
            End
            <input type="date" value={endDay} onChange={(event) => onEndDayChange(event.target.value)} />
          </label>
          <button type="button" onClick={onRefresh}>
            {state.loading ? "Loading..." : "Load journal"}
          </button>
        </div>
        <div className="panel-meta-row">
          <span className="meta-pill">Source {state.source || "n/a"}</span>
          <span className="meta-pill">Start {String(payload.start_day || startDay || "all")}</span>
          <span className="meta-pill">End {String(payload.end_day || endDay || "all")}</span>
          <span className="meta-pill">Pair {String(payload.trading_pair || "n/a")}</span>
        </div>
        <p className="panel-subtitle">{state.error || payload.narrative || "No journal loaded."}</p>
      </Panel>

      <Panel title="Journal Summary" subtitle="Outcomes, execution cost, and context mix." className="panel-span-12">
        <div className="summary-grid summary-grid-3">
          <article className="summary-card">
            <h3>Trade Outcomes</h3>
            <div className={`summary-value ${signedClass(summary.realized_pnl_quote_total)}`}>{formatSigned(summary.realized_pnl_quote_total, 4)}</div>
            <dl>
              <dt>Closed Trades</dt>
              <dd>{String(summary.trade_count || 0)}</dd>
              <dt>Win Rate</dt>
              <dd>{formatPct(summary.win_rate || 0, 1)}</dd>
              <dt>Winning / Losing</dt>
              <dd>
                {String(summary.winning_trades || 0)} / {String(summary.losing_trades || 0)}
              </dd>
              <dt>Avg Trade</dt>
              <dd className={signedClass(summary.avg_realized_pnl_quote)}>{formatSigned(summary.avg_realized_pnl_quote, 4)}</dd>
              <dt>Avg Win</dt>
              <dd className={signedClass(summary.avg_win_quote)}>{formatSigned(summary.avg_win_quote, 4)}</dd>
              <dt>Avg Loss</dt>
              <dd className={signedClass(summary.avg_loss_quote)}>{formatSigned(summary.avg_loss_quote, 4)}</dd>
              <dt>Avg MFE / MAE</dt>
              <dd>
                <span className={signedClass(summary.avg_mfe_quote)}>{formatSigned(summary.avg_mfe_quote, 4)}</span>
                {" / "}
                <span className={signedClass(summary.avg_mae_quote)}>{formatSigned(summary.avg_mae_quote, 4)}</span>
              </dd>
            </dl>
          </article>
          <article className="summary-card">
            <h3>Execution Cost / Timing</h3>
            <div className="summary-value">{formatNumber(summary.fees_quote_total, 4)}</div>
            <dl>
              <dt>Avg Hold</dt>
              <dd>{formatAgeMs((summary.avg_hold_seconds || 0) * 1000)}</dd>
              <dt>First Entry</dt>
              <dd>{formatTs(summary.start_ts)}</dd>
              <dt>Last Exit</dt>
              <dd>{formatTs(summary.end_ts)}</dd>
              <dt>Scope Start</dt>
              <dd>{String(payload.start_day || startDay || "all")}</dd>
              <dt>Scope End</dt>
              <dd>{String(payload.end_day || endDay || "all")}</dd>
            </dl>
          </article>
          <article className="summary-card">
            <h3>Context / Exit Mix</h3>
            <div className="summary-value">{topExitReasons || "n/a"}</div>
            <dl>
              <dt>Entry Regimes</dt>
              <dd>{topEntryRegimes || "n/a"}</dd>
              <dt>Exit Reasons</dt>
              <dd>{topExitReasons || "n/a"}</dd>
              <dt>Minute Context</dt>
              <dd>{state.source.includes("minute_log") ? "available" : "fills only"}</dd>
              <dt>Trades Shown</dt>
              <dd>{String(trades.length || 0)}</dd>
            </dl>
          </article>
        </div>
      </Panel>

      <Panel title="Closed Trades" subtitle="Select a row for drilldown details." className="panel-span-12">
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th scope="col">Entry</th>
                <th scope="col">Exit</th>
                <th scope="col">Side</th>
                <th scope="col">Qty</th>
                <th scope="col">Entry Avg</th>
                <th scope="col">Exit Avg</th>
                <th scope="col">Hold</th>
                <th scope="col">Context</th>
                <th scope="col">MFE / MAE</th>
                <th scope="col">Fees</th>
                <th scope="col">Exit</th>
                <th scope="col">Realized</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={13}>No closed trades available for the selected range.</td>
                </tr>
              ) : (
                trades
                  .slice()
                  .reverse()
                  .map((trade, index) => {
                    const tradeId = String(trade.trade_id || `trade-${index}`);
                    return (
                      <tr
                        key={tradeId}
                        className={`journal-trade-row ${tradeId === selectedTradeId ? "selected" : ""}`.trim()}
                        onClick={() => onSelectTrade(tradeId)}
                      >
                        <td>
                          <div>{formatTs(trade.entry_ts)}</div>
                          <div className="subvalue">{formatRelativeTs(trade.entry_ts)}</div>
                        </td>
                        <td>
                          <div>{formatTs(trade.exit_ts)}</div>
                          <div className="subvalue">{formatRelativeTs(trade.exit_ts)}</div>
                        </td>
                        <td>
                          <span className={`pill ${sideTone(String(trade.side || ""))}`}>{String(trade.side || "")}</span>
                        </td>
                        <td>{formatNumber(trade.quantity, 6)}</td>
                        <td>{formatNumber(trade.avg_entry_price, 4)}</td>
                        <td>{formatNumber(trade.avg_exit_price, 4)}</td>
                        <td>{formatAgeMs((Number(trade.hold_seconds || 0) || 0) * 1000)}</td>
                        <td>
                          <div>
                            {String(trade.entry_regime || "n/a").replaceAll("_", " ")}
                            {" -> "}
                            {String(trade.exit_regime || "n/a").replaceAll("_", " ")}
                          </div>
                          <div className="subvalue">
                            {String(trade.entry_state || "n/a")}
                            {" -> "}
                            {String(trade.exit_state || "n/a")}
                          </div>
                        </td>
                        <td>
                          <div>
                            <span className={signedClass(trade.mfe_quote)}>{formatSigned(trade.mfe_quote, 4)}</span> /{" "}
                            <span className={signedClass(trade.mae_quote)}>{formatSigned(trade.mae_quote, 4)}</span>
                          </div>
                          <div className="subvalue">
                            {Array.isArray(trade.risk_reasons_seen) && trade.risk_reasons_seen.length
                              ? trade.risk_reasons_seen.join(", ")
                              : "no risk tags"}
                          </div>
                        </td>
                        <td>{formatNumber(trade.fees_quote, 4)}</td>
                        <td>
                          <div>{String(trade.exit_reason_label || "n/a")}</div>
                          <div className="subvalue">
                            {trade.pnl_governor_seen
                              ? "pnl governor"
                              : trade.order_book_stale_seen
                                ? "book stale seen"
                                : String(trade.context_source || "fills only")}
                          </div>
                        </td>
                        <td className={signedClass(trade.realized_pnl_quote)}>{formatSigned(trade.realized_pnl_quote, 4)}</td>
                        <td>
                          <button type="button" className="secondary table-action-btn" onClick={() => onSelectTrade(tradeId)}>
                            {tradeId === selectedTradeId ? "Selected" : "Select"}
                          </button>
                        </td>
                      </tr>
                    );
                  })
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Trade Drilldown" subtitle="Selected trade detail and intratrade path context." className="panel-span-12">
        {!selectedTrade ? (
          <div className="empty-state">No trade selected.</div>
        ) : (
          <>
            <div className="panel-meta-row">
              <span className="meta-pill">Trade {String(selectedTrade.trade_id || "n/a")}</span>
              <span className="meta-pill">Side {String(selectedTrade.side || "n/a")}</span>
              <span className="meta-pill">Fills {String(selectedTrade.fill_count || selectedFills.length || 0)}</span>
              <span className="meta-pill">Path points {String(pathSummary.point_count || selectedPath.length || 0)}</span>
            </div>
            <div className="summary-grid summary-grid-3">
              <article className="summary-card">
                <h3>Selected Trade</h3>
                <div className={`summary-value ${signedClass(selectedTrade.realized_pnl_quote)}`}>
                  {formatSigned(selectedTrade.realized_pnl_quote, 4)}
                </div>
                <dl>
                  <dt>Entry</dt>
                  <dd>{formatTs(selectedTrade.entry_ts)}</dd>
                  <dt>Exit</dt>
                  <dd>{formatTs(selectedTrade.exit_ts)}</dd>
                  <dt>Hold</dt>
                  <dd>{formatAgeMs((Number(selectedTrade.hold_seconds || 0) || 0) * 1000)}</dd>
                  <dt>Quantity</dt>
                  <dd>{formatNumber(selectedTrade.quantity, 6)}</dd>
                  <dt>Fees</dt>
                  <dd>{formatNumber(selectedTrade.fees_quote, 4)}</dd>
                  <dt>Exit Label</dt>
                  <dd>{String(selectedTrade.exit_reason_label || "n/a")}</dd>
                </dl>
              </article>
              <article className="summary-card">
                <h3>Context</h3>
                <div className="summary-value">
                  {String(selectedTrade.entry_regime || "n/a").replaceAll("_", " ")}
                  {" -> "}
                  {String(selectedTrade.exit_regime || "n/a").replaceAll("_", " ")}
                </div>
                <dl>
                  <dt>State Transition</dt>
                  <dd>
                    {String(selectedTrade.entry_state || "n/a")}
                    {" -> "}
                    {String(selectedTrade.exit_state || "n/a")}
                  </dd>
                  <dt>Risk Tags</dt>
                  <dd>
                    {Array.isArray(selectedTrade.risk_reasons_seen) && selectedTrade.risk_reasons_seen.length
                      ? selectedTrade.risk_reasons_seen.join(", ")
                      : "none"}
                  </dd>
                  <dt>Pnl Governor</dt>
                  <dd>{selectedTrade.pnl_governor_seen ? "seen" : "not seen"}</dd>
                  <dt>Book Stale</dt>
                  <dd>{selectedTrade.order_book_stale_seen ? "seen" : "not seen"}</dd>
                  <dt>MFE</dt>
                  <dd className={signedClass(selectedTrade.mfe_quote)}>{formatSigned(selectedTrade.mfe_quote, 4)}</dd>
                  <dt>MAE</dt>
                  <dd className={signedClass(selectedTrade.mae_quote)}>{formatSigned(selectedTrade.mae_quote, 4)}</dd>
                </dl>
              </article>
              <article className="summary-card">
                <h3>Path Summary</h3>
                <div className="summary-value">
                  {formatNumber(pathSummary.mid_open, 4)}
                  {" -> "}
                  {formatNumber(pathSummary.mid_close, 4)}
                </div>
                <dl>
                  <dt>Mid High</dt>
                  <dd>{formatNumber(pathSummary.mid_high, 4)}</dd>
                  <dt>Mid Low</dt>
                  <dd>{formatNumber(pathSummary.mid_low, 4)}</dd>
                  <dt>Equity Open</dt>
                  <dd>{formatNumber(pathSummary.equity_open_quote, 4)}</dd>
                  <dt>Equity Close</dt>
                  <dd>{formatNumber(pathSummary.equity_close_quote, 4)}</dd>
                  <dt>Sampled Points</dt>
                  <dd>{String(pathSummary.point_count || selectedPath.length || 0)}</dd>
                  <dt>Context Source</dt>
                  <dd>{String(selectedTrade.context_source || "n/a")}</dd>
                </dl>
              </article>
            </div>
          </>
        )}
      </Panel>

      <Panel title="Contributing Fills" subtitle="Exact fill cluster attached to the selected trade." className="panel-span-6">
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Role</th>
                <th scope="col">Side</th>
                <th scope="col">Qty</th>
                <th scope="col">Price</th>
                <th scope="col">Notional</th>
                <th scope="col">Fee</th>
                <th scope="col">Realized</th>
              </tr>
            </thead>
            <tbody>
              {selectedFills.length === 0 ? (
                <tr>
                  <td colSpan={8}>No fill cluster available.</td>
                </tr>
              ) : (
                selectedFills.map((fill, index) => (
                  <tr key={`${fill.ts || "fill"}-${index}`}>
                    <td>
                      <div>{formatTs(fill.ts)}</div>
                      <div className="subvalue">{formatRelativeTs(fill.ts)}</div>
                    </td>
                    <td>{String(fill.role || "n/a")}</td>
                    <td>
                      <span className={`pill ${sideTone(String(fill.side || ""))}`}>{String(fill.side || "")}</span>
                    </td>
                    <td>{formatNumber(fill.amount_base, 6)}</td>
                    <td>{formatNumber(fill.price, 4)}</td>
                    <td>{formatNumber(fill.notional_quote, 4)}</td>
                    <td>{formatNumber(fill.fee_quote, 4)}</td>
                    <td className={signedClass(fill.realized_pnl_quote)}>{formatSigned(fill.realized_pnl_quote, 4)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Intratrade Path" subtitle="Sampled minute path for price, equity, state, and regime." className="panel-span-6">
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Mid</th>
                <th scope="col">Equity</th>
                <th scope="col">State</th>
                <th scope="col">Regime</th>
              </tr>
            </thead>
            <tbody>
              {selectedPath.length === 0 ? (
                <tr>
                  <td colSpan={5}>No intratrade path available.</td>
                </tr>
              ) : (
                selectedPath.map((point, index) => (
                  <tr key={`${point.ts || "path"}-${index}`}>
                    <td>
                      <div>{formatTs(point.ts)}</div>
                      <div className="subvalue">{formatRelativeTs(point.ts)}</div>
                    </td>
                    <td>{formatNumber(point.mid, 4)}</td>
                    <td>{formatNumber(point.equity_quote, 4)}</td>
                    <td>{String(point.state || "n/a")}</td>
                    <td>{String(point.regime || "n/a").replaceAll("_", " ")}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Bot Gate Timeline" subtitle="Gate transitions observed during the selected trade window." className="panel-span-12">
        <GateTimelineTable rows={selectedGateTimeline} emptyMessage="No gate transitions available for this trade." />
      </Panel>
    </>
  );
});
