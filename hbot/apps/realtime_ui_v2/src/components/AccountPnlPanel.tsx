import { memo, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatNumber, formatPct, formatSigned, toNum } from "../utils/format";
import { getLiveAccountMetrics } from "../utils/metrics";
import { useFlashClass } from "../hooks/useFlashClass";
import { Panel } from "./Panel";

/* ── helpers ─────────────────────────────────────────────────────────── */

function equityStatus(deltaVsOpen: number | null, deltaVsPeak: number | null): { label: string; tone: string } {
  if (deltaVsOpen === null) return { label: "unknown", tone: "neutral" };
  if (deltaVsOpen >= 0 && (deltaVsPeak === null || deltaVsPeak >= -0.0005))
    return { label: "at highs", tone: "ok" };
  if (deltaVsOpen >= 0) return { label: "green drawdown", tone: "warn" };
  return { label: "below open", tone: "fail" };
}

function riskTone(sa: Record<string, unknown>): { label: string; tone: string } {
  const cs = String(sa.controller_state || "").trim().toLowerCase();
  if (cs === "hard_stop") return { label: "hard stop", tone: "fail" };
  if (sa.risk_reasons) return { label: "risk active", tone: "warn" };
  if (sa.order_book_stale) return { label: "book stale", tone: "warn" };
  if (sa.pnl_governor_active) return { label: "governor", tone: "warn" };
  if (cs) return { label: cs.replaceAll("_", " "), tone: "ok" };
  return { label: "unknown", tone: "neutral" };
}

/* ── component ───────────────────────────────────────────────────────── */

export const AccountPnlPanel = memo(function AccountPnlPanel() {
  const awaiting = useDashboardStore((s) => s.connection.lastMessageTsMs === 0 && s.source === "");

  const {
    marketMidPrice, depthBestBid, depthBestAsk, latestMid,
    posQty, posSide, posEntry, posUnreal,
    realizedPnl, quoteBalance, equityQuote, equityOpen, equityPeak,
    controllerState, govActive, govReason, riskReasons,
    dailyLossPct, dailyLossHard, drawdownPct, drawdownHard,
    bookStale, snapshotTs,
  } = useDashboardStore(
    useShallow((s) => ({
      marketMidPrice: s.market.mid_price,
      depthBestBid: s.depth.best_bid,
      depthBestAsk: s.depth.best_ask,
      latestMid: s.latestMid,
      posQty: s.position.quantity,
      posSide: s.position.side,
      posEntry: s.position.avg_entry_price,
      posUnreal: s.position.unrealized_pnl,
      realizedPnl: s.summaryAccount.realized_pnl_quote,
      quoteBalance: s.summaryAccount.quote_balance,
      equityQuote: s.summaryAccount.equity_quote,
      equityOpen: s.summaryAccount.equity_open_quote,
      equityPeak: s.summaryAccount.equity_peak_quote,
      controllerState: s.summaryAccount.controller_state,
      govActive: s.summaryAccount.pnl_governor_active,
      govReason: s.summaryAccount.pnl_governor_reason,
      riskReasons: s.summaryAccount.risk_reasons,
      dailyLossPct: s.summaryAccount.daily_loss_pct,
      dailyLossHard: s.summaryAccount.max_daily_loss_pct_hard,
      drawdownPct: s.summaryAccount.drawdown_pct,
      drawdownHard: s.summaryAccount.max_drawdown_pct_hard,
      bookStale: s.summaryAccount.order_book_stale,
      snapshotTs: s.summaryAccount.snapshot_ts,
    })),
  );

  const sa = useMemo(() => ({
    realized_pnl_quote: realizedPnl, quote_balance: quoteBalance,
    equity_quote: equityQuote, equity_open_quote: equityOpen, equity_peak_quote: equityPeak,
    controller_state: controllerState, pnl_governor_active: govActive,
    pnl_governor_reason: govReason, risk_reasons: riskReasons,
    daily_loss_pct: dailyLossPct, max_daily_loss_pct_hard: dailyLossHard,
    drawdown_pct: drawdownPct, max_drawdown_pct_hard: drawdownHard,
    order_book_stale: bookStale, snapshot_ts: snapshotTs,
  }), [realizedPnl, quoteBalance, equityQuote, equityOpen, equityPeak,
    controllerState, govActive, govReason, riskReasons,
    dailyLossPct, dailyLossHard, drawdownPct, drawdownHard, bookStale, snapshotTs]);

  const pos = useMemo(() => ({
    quantity: posQty, side: posSide, avg_entry_price: posEntry, unrealized_pnl: posUnreal,
  }), [posQty, posSide, posEntry, posUnreal]);

  const mkt = useMemo(() => ({ mid_price: marketMidPrice }), [marketMidPrice]);
  const dep = useMemo(() => ({ best_bid: depthBestBid, best_ask: depthBestAsk }), [depthBestBid, depthBestAsk]);

  const m = useMemo(() => getLiveAccountMetrics(sa, pos, mkt, dep, latestMid), [sa, pos, mkt, dep, latestMid]);
  const eqStatus = equityStatus(m.deltaVsOpenQuote, m.deltaVsPeakQuote);
  const risk = riskTone(sa as Record<string, unknown>);
  const eqFlash = useFlashClass(m.equityQuote);
  const pnlFlash = useFlashClass(m.totalPnl);

  const dlPct = toNum(dailyLossPct) || 0;
  const dlHard = toNum(dailyLossHard) || 0;
  const ddPct = toNum(drawdownPct) || 0;
  const ddHard = toNum(drawdownHard) || 0;
  const dlProgress = dlHard > 0 ? Math.min(1, Math.abs(dlPct) / Math.abs(dlHard)) : 0;
  const ddProgress = ddHard > 0 ? Math.min(1, Math.abs(ddPct) / Math.abs(ddHard)) : 0;

  return (
    <Panel title="24h Equity & PnL" className="panel-span-8" loading={awaiting}>
      <div className="summary-grid summary-grid-3">
        {/* ── Equity card ──────────────────────────────────────────── */}
        <article className="summary-card">
          <h3>Equity</h3>
          <div className={`summary-value ${eqFlash || (m.equityQuote && m.equityQuote < 0 ? "value-negative" : "value-positive")}`}>
            {formatNumber(m.equityQuote, 2)}
          </div>
          <div style={{ marginBottom: 6 }}>
            <span className={`pill ${eqStatus.tone}`}>{eqStatus.label}</span>
          </div>
          <dl>
            <dt>Open</dt><dd>{formatNumber(m.equityOpenQuote, 2)}</dd>
            <dt>Peak</dt><dd>{formatNumber(m.equityPeakQuote, 2)}</dd>
            <dt>Vs Open</dt>
            <dd className={m.deltaVsOpenQuote && m.deltaVsOpenQuote < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(m.deltaVsOpenQuote, 2)}
            </dd>
            <dt>Vs Peak</dt>
            <dd className={m.deltaVsPeakQuote && m.deltaVsPeakQuote < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(m.deltaVsPeakQuote, 2)}
            </dd>
            <dt>Return</dt>
            <dd className={m.returnVsOpen && m.returnVsOpen < 0 ? "value-negative" : "value-positive"}>
              {formatPct(m.returnVsOpen, 2)}
            </dd>
            <dt>Balance</dt><dd>{formatNumber(m.quoteBalance, 2)}</dd>
          </dl>
        </article>

        {/* ── PnL breakdown card ───────────────────────────────────── */}
        <article className="summary-card">
          <h3>
            PnL
            {m.totalPnlSource === "components" ? (
              <span className="source-badge" title="Realized + unrealized PnL">sum</span>
            ) : m.totalPnlSource === "equity_delta" ? (
              <span className="source-badge warn" title="Fallback: equity vs open">equity&nbsp;&Delta;</span>
            ) : null}
          </h3>
          <div className={`summary-value ${pnlFlash || (m.totalPnl && m.totalPnl < 0 ? "value-negative" : "value-positive")}`}>
            {formatSigned(m.totalPnl, 2)}
          </div>
          <dl>
            <dt>Realized</dt>
            <dd className={m.realizedPnl && m.realizedPnl < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(m.realizedPnl, 4)}
            </dd>
            <dt>Unrealized</dt>
            <dd className={m.unrealizedPnl && m.unrealizedPnl < 0 ? "value-negative" : "value-positive"}>
              {formatSigned(m.unrealizedPnl, 4)}
            </dd>
            <dt>Mark</dt><dd>{formatNumber(m.mark, 2)}</dd>
            <dt>Entry</dt><dd>{formatNumber(m.avgEntryPrice, 2)}</dd>
          </dl>
        </article>

        {/* ── Risk card ────────────────────────────────────────────── */}
        <article className="summary-card">
          <h3>Risk</h3>
          <div className="summary-value">
            <span className={`pill ${risk.tone}`}>{risk.label}</span>
          </div>
          <dl>
            <dt>Controller</dt><dd>{String(sa.controller_state || "n/a")}</dd>
            <dt>Governor</dt><dd>{sa.pnl_governor_active ? String(sa.pnl_governor_reason || "active") : "off"}</dd>
            <dt>Risk</dt><dd>{String(sa.risk_reasons || "none")}</dd>
            <dt>Daily Loss</dt>
            <dd>
              {formatPct(dlPct, 2)} / {formatPct(dlHard, 2)}
              <div className="risk-gauge"><div className="risk-gauge-fill" style={{ width: `${dlProgress * 100}%` }} /></div>
            </dd>
            <dt>Drawdown</dt>
            <dd>
              {formatPct(ddPct, 2)} / {formatPct(ddHard, 2)}
              <div className="risk-gauge"><div className="risk-gauge-fill" style={{ width: `${ddProgress * 100}%` }} /></div>
            </dd>
            <dt>Book</dt><dd>{sa.order_book_stale ? "stale" : "fresh"}</dd>
          </dl>
        </article>
      </div>
    </Panel>
  );
});
