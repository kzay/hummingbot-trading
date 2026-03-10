import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatNumber, formatPct, formatRelativeTs, formatSigned, toNum } from "../utils/format";
import { getLiveAccountMetrics } from "../utils/metrics";
import { Panel } from "./Panel";

function accountState(deltaVsOpenQuote: number | null, deltaVsPeakQuote: number | null): { label: string; tone: string } {
  if (deltaVsOpenQuote === null) {
    return { label: "unknown", tone: "neutral" };
  }
  if (deltaVsOpenQuote >= 0 && (deltaVsPeakQuote === null || deltaVsPeakQuote >= -0.0005)) {
    return { label: "at highs", tone: "ok" };
  }
  if (deltaVsOpenQuote >= 0) {
    return { label: "green drawdown", tone: "warn" };
  }
  return { label: "below open", tone: "fail" };
}

function riskState(summaryAccount: Record<string, unknown>): { label: string; tone: string } {
  const controllerState = String(summaryAccount.controller_state || "").trim().toLowerCase();
  const riskReasons = String(summaryAccount.risk_reasons || "").trim();
  const governorActive = Boolean(summaryAccount.pnl_governor_active);
  const bookStale = Boolean(summaryAccount.order_book_stale);
  if (controllerState === "hard_stop") {
    return { label: "hard stop", tone: "fail" };
  }
  if (riskReasons) {
    return { label: "risk active", tone: "warn" };
  }
  if (bookStale) {
    return { label: "book stale", tone: "warn" };
  }
  if (governorActive) {
    return { label: "governor", tone: "warn" };
  }
  if (controllerState) {
    return { label: controllerState.replaceAll("_", " "), tone: "ok" };
  }
  return { label: "unknown", tone: "neutral" };
}

export function AccountPnlPanel() {
  const {
    source,
    fallbackActive,
    marketMidPrice,
    depthBestBid,
    depthBestAsk,
    latestMid,
    positionQuantity,
    positionSide,
    positionAvgEntryPrice,
    positionUnrealizedPnl,
    realizedPnlQuote,
    quoteBalance,
    equityQuote,
    equityOpenQuote,
    equityPeakQuote,
    controllerState,
    pnlGovernorActive,
    pnlGovernorReason,
    riskReasons,
    dailyLossPctRaw,
    dailyLossHardPctRaw,
    drawdownPctRaw,
    drawdownHardPctRaw,
    orderBookStale,
    snapshotTs,
    activityFillCount,
    activityMakerRatio,
    activityFeesQuote,
    activityAvgFillSize,
  } = useDashboardStore(
    useShallow((state) => ({
      source: state.source,
      fallbackActive: state.summarySystem.fallback_active,
      marketMidPrice: state.market.mid_price,
      depthBestBid: state.depth.best_bid,
      depthBestAsk: state.depth.best_ask,
      latestMid: state.latestMid,
      positionQuantity: state.position.quantity,
      positionSide: state.position.side,
      positionAvgEntryPrice: state.position.avg_entry_price,
      positionUnrealizedPnl: state.position.unrealized_pnl,
      realizedPnlQuote: state.summaryAccount.realized_pnl_quote,
      quoteBalance: state.summaryAccount.quote_balance,
      equityQuote: state.summaryAccount.equity_quote,
      equityOpenQuote: state.summaryAccount.equity_open_quote,
      equityPeakQuote: state.summaryAccount.equity_peak_quote,
      controllerState: state.summaryAccount.controller_state,
      pnlGovernorActive: state.summaryAccount.pnl_governor_active,
      pnlGovernorReason: state.summaryAccount.pnl_governor_reason,
      riskReasons: state.summaryAccount.risk_reasons,
      dailyLossPctRaw: state.summaryAccount.daily_loss_pct,
      dailyLossHardPctRaw: state.summaryAccount.max_daily_loss_pct_hard,
      drawdownPctRaw: state.summaryAccount.drawdown_pct,
      drawdownHardPctRaw: state.summaryAccount.max_drawdown_pct_hard,
      orderBookStale: state.summaryAccount.order_book_stale,
      snapshotTs: state.summaryAccount.snapshot_ts,
      activityFillCount: state.summaryActivity.window_1h?.fill_count,
      activityMakerRatio: state.summaryActivity.window_1h?.maker_ratio,
      activityFeesQuote: state.summaryActivity.window_1h?.fees_quote,
      activityAvgFillSize: state.summaryActivity.window_1h?.avg_fill_size,
    })),
  );

  const summaryAccount = useMemo(
    () => ({
      realized_pnl_quote: realizedPnlQuote,
      quote_balance: quoteBalance,
      equity_quote: equityQuote,
      equity_open_quote: equityOpenQuote,
      equity_peak_quote: equityPeakQuote,
      controller_state: controllerState,
      pnl_governor_active: pnlGovernorActive,
      pnl_governor_reason: pnlGovernorReason,
      risk_reasons: riskReasons,
      daily_loss_pct: dailyLossPctRaw,
      max_daily_loss_pct_hard: dailyLossHardPctRaw,
      drawdown_pct: drawdownPctRaw,
      max_drawdown_pct_hard: drawdownHardPctRaw,
      order_book_stale: orderBookStale,
      snapshot_ts: snapshotTs,
    }),
    [
      controllerState,
      dailyLossHardPctRaw,
      dailyLossPctRaw,
      drawdownHardPctRaw,
      drawdownPctRaw,
      equityOpenQuote,
      equityPeakQuote,
      equityQuote,
      orderBookStale,
      pnlGovernorActive,
      pnlGovernorReason,
      quoteBalance,
      realizedPnlQuote,
      riskReasons,
      snapshotTs,
    ],
  );
  const position = useMemo(
    () => ({
      quantity: positionQuantity,
      side: positionSide,
      avg_entry_price: positionAvgEntryPrice,
      unrealized_pnl: positionUnrealizedPnl,
    }),
    [positionAvgEntryPrice, positionQuantity, positionSide, positionUnrealizedPnl],
  );
  const market = useMemo(() => ({ mid_price: marketMidPrice }), [marketMidPrice]);
  const depth = useMemo(
    () => ({
      best_bid: depthBestBid,
      best_ask: depthBestAsk,
    }),
    [depthBestAsk, depthBestBid],
  );

  const metrics = useMemo(
    () => getLiveAccountMetrics(summaryAccount, position, market, depth, latestMid),
    [summaryAccount, position, market, depth, latestMid],
  );
  const accState = accountState(metrics.deltaVsOpenQuote, metrics.deltaVsPeakQuote);
  const risk = riskState(summaryAccount as Record<string, unknown>);

  const dailyLossPct = toNum(dailyLossPctRaw) || 0;
  const dailyLossHardPct = toNum(dailyLossHardPctRaw) || 0;
  const drawdownPct = toNum(drawdownPctRaw) || 0;
  const drawdownHardPct = toNum(drawdownHardPctRaw) || 0;
  const dailyLossProgress = dailyLossHardPct > 0 ? Math.min(1, Math.abs(dailyLossPct) / Math.abs(dailyLossHardPct)) : 0;
  const drawdownProgress = drawdownHardPct > 0 ? Math.min(1, Math.abs(drawdownPct) / Math.abs(drawdownHardPct)) : 0;

  return (
    <Panel title="Account / PnL" subtitle="Equity and PnL decomposition with runtime risk context." className="panel-span-8">
      <div className="panel-meta-row">
        <span className="meta-pill">Source {source || "n/a"}</span>
        <span className="meta-pill">Snapshot {formatRelativeTs(snapshotTs)}</span>
        <span className="meta-pill">Fallback {fallbackActive ? "active" : "off"}</span>
      </div>
      <div className="summary-grid">
        <article className="summary-card">
          <h3>Equity</h3>
          <div className={`summary-value ${metrics.equityQuote && metrics.equityQuote < 0 ? "value-negative" : "value-positive"}`}>
            {formatNumber(metrics.equityQuote, 4)}
          </div>
          <dl>
            <dt>Status</dt>
            <dd>
              <span className={`pill ${accState.tone}`}>{accState.label}</span>
            </dd>
            <dt>Quote Balance</dt>
            <dd>{formatNumber(metrics.quoteBalance, 4)}</dd>
            <dt>Open Equity</dt>
            <dd>{formatNumber(metrics.equityOpenQuote, 4)}</dd>
            <dt>Peak Equity</dt>
            <dd>{formatNumber(metrics.equityPeakQuote, 4)}</dd>
            <dt>Vs Open</dt>
            <dd className={metrics.deltaVsOpenQuote && metrics.deltaVsOpenQuote < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(metrics.deltaVsOpenQuote, 4)}
            </dd>
            <dt>Vs Peak</dt>
            <dd className={metrics.deltaVsPeakQuote && metrics.deltaVsPeakQuote < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(metrics.deltaVsPeakQuote, 4)}
            </dd>
            <dt>Return vs Open</dt>
            <dd className={metrics.returnVsOpen && metrics.returnVsOpen < 0 ? "value-negative" : "value-positive"}>
              {formatPct(metrics.returnVsOpen, 2)}
            </dd>
          </dl>
        </article>

        <article className="summary-card">
          <h3>PnL Stack</h3>
          <div className={`summary-value ${metrics.totalPnl && metrics.totalPnl < 0 ? "value-negative" : "value-positive"}`}>
            {formatSigned(metrics.totalPnl, 4)}
          </div>
          <dl>
            <dt>Realized</dt>
            <dd className={metrics.realizedPnl && metrics.realizedPnl < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(metrics.realizedPnl, 4)}
            </dd>
            <dt>Unrealized</dt>
            <dd className={metrics.unrealizedPnl && metrics.unrealizedPnl < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(metrics.unrealizedPnl, 4)}
            </dd>
            <dt>Mark</dt>
            <dd>{formatNumber(metrics.mark, 4)}</dd>
            <dt>Avg Entry</dt>
            <dd>{formatNumber(metrics.avgEntryPrice, 4)}</dd>
            <dt>Position Qty</dt>
            <dd>{formatNumber(metrics.positionQty, 6)}</dd>
          </dl>
        </article>

        <article className="summary-card">
          <h3>Risk State</h3>
          <div className="summary-value">
            <span className={`pill ${risk.tone}`}>{risk.label}</span>
          </div>
          <dl>
            <dt>Controller</dt>
            <dd>{String(summaryAccount.controller_state || "n/a")}</dd>
            <dt>Governor</dt>
            <dd>{summaryAccount.pnl_governor_active ? String(summaryAccount.pnl_governor_reason || "active") : "off"}</dd>
            <dt>Risk Reasons</dt>
            <dd>{String(summaryAccount.risk_reasons || "none")}</dd>
            <dt>Daily Loss</dt>
            <dd>
              {formatPct(dailyLossPct, 2)} / {formatPct(dailyLossHardPct, 2)}
              <div className="risk-gauge">
                <div className="risk-gauge-fill" style={{ width: `${dailyLossProgress * 100}%` }} />
              </div>
            </dd>
            <dt>Drawdown</dt>
            <dd>
              {formatPct(drawdownPct, 2)} / {formatPct(drawdownHardPct, 2)}
              <div className="risk-gauge">
                <div className="risk-gauge-fill" style={{ width: `${drawdownProgress * 100}%` }} />
              </div>
            </dd>
            <dt>Order Book</dt>
            <dd>{summaryAccount.order_book_stale ? "stale" : "fresh"}</dd>
          </dl>
        </article>
      </div>
      <div className="metric-grid metric-grid-session">
        <article className="metric-card compact">
          <h3>Session fills</h3>
          <div className="metric-value">{String(activityFillCount ?? 0)}</div>
          <dl>
            <dt>Maker ratio</dt>
            <dd>{formatPct(activityMakerRatio ?? 0, 1)}</dd>
            <dt>Fees</dt>
            <dd>{formatNumber(activityFeesQuote ?? 0, 4)}</dd>
            <dt>Avg fill size</dt>
            <dd>{formatNumber(activityAvgFillSize ?? 0, 6)}</dd>
          </dl>
        </article>
      </div>
    </Panel>
  );
}
