import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatNumber, formatPct, formatSigned, formatTs, toNum } from "../utils/format";
import { getDepthStats, getLiveAccountMetrics } from "../utils/metrics";
import { sideTone } from "../utils/presentation";
import { Panel } from "./Panel";

export function PositionExposurePanel() {
  const {
    mode,
    source,
    marketMidPrice,
    depthBestBid,
    depthBestAsk,
    positionQuantity,
    positionSide,
    positionAvgEntryPrice,
    positionUnrealizedPnl,
    positionSourceTsMs,
    ordersLength,
    fillsTotal,
    latestMarketTsMs,
    summarySnapshotTs,
    accountRealizedPnlQuote,
    accountQuoteBalance,
    accountEquityQuote,
    accountEquityOpenQuote,
    accountEquityPeakQuote,
    latestMid,
    activity15mFillCount,
    activity15mMakerRatio,
    activity15mVolumeBase,
    activity15mNotionalQuote,
    activity15mRealizedPnlQuote,
    activity1hFillCount,
    activity1hMakerRatio,
    activity1hVolumeBase,
    activity1hNotionalQuote,
    activity1hRealizedPnlQuote,
  } = useDashboardStore(
    useShallow((state) => ({
      mode: state.mode,
      source: state.source,
      marketMidPrice: state.market.mid_price,
      depthBestBid: state.depth.best_bid,
      depthBestAsk: state.depth.best_ask,
      positionQuantity: state.position.quantity,
      positionSide: state.position.side,
      positionAvgEntryPrice: state.position.avg_entry_price,
      positionUnrealizedPnl: state.position.unrealized_pnl,
      positionSourceTsMs: state.position.source_ts_ms,
      ordersLength: state.orders.length,
      fillsTotal: state.fillsTotal,
      latestMarketTsMs: state.summarySystem.latest_market_ts_ms,
      summarySnapshotTs: state.summaryAccount.snapshot_ts,
      accountRealizedPnlQuote: state.summaryAccount.realized_pnl_quote,
      accountQuoteBalance: state.summaryAccount.quote_balance,
      accountEquityQuote: state.summaryAccount.equity_quote,
      accountEquityOpenQuote: state.summaryAccount.equity_open_quote,
      accountEquityPeakQuote: state.summaryAccount.equity_peak_quote,
      latestMid: state.latestMid,
      activity15mFillCount: state.summaryActivity.window_15m?.fill_count,
      activity15mMakerRatio: state.summaryActivity.window_15m?.maker_ratio,
      activity15mVolumeBase: state.summaryActivity.window_15m?.volume_base,
      activity15mNotionalQuote: state.summaryActivity.window_15m?.notional_quote,
      activity15mRealizedPnlQuote: state.summaryActivity.window_15m?.realized_pnl_quote,
      activity1hFillCount: state.summaryActivity.window_1h?.fill_count,
      activity1hMakerRatio: state.summaryActivity.window_1h?.maker_ratio,
      activity1hVolumeBase: state.summaryActivity.window_1h?.volume_base,
      activity1hNotionalQuote: state.summaryActivity.window_1h?.notional_quote,
      activity1hRealizedPnlQuote: state.summaryActivity.window_1h?.realized_pnl_quote,
    })),
  );

  const market = useMemo(() => ({ mid_price: marketMidPrice }), [marketMidPrice]);
  const depth = useMemo(
    () => ({
      best_bid: depthBestBid,
      best_ask: depthBestAsk,
    }),
    [depthBestAsk, depthBestBid],
  );
  const position = useMemo(
    () => ({
      quantity: positionQuantity,
      side: positionSide,
      avg_entry_price: positionAvgEntryPrice,
      unrealized_pnl: positionUnrealizedPnl,
      source_ts_ms: positionSourceTsMs,
    }),
    [positionAvgEntryPrice, positionQuantity, positionSide, positionSourceTsMs, positionUnrealizedPnl],
  );
  const summaryAccount = useMemo(
    () => ({
      realized_pnl_quote: accountRealizedPnlQuote,
      quote_balance: accountQuoteBalance,
      equity_quote: accountEquityQuote,
      equity_open_quote: accountEquityOpenQuote,
      equity_peak_quote: accountEquityPeakQuote,
      snapshot_ts: summarySnapshotTs,
    }),
    [accountEquityOpenQuote, accountEquityPeakQuote, accountEquityQuote, accountQuoteBalance, accountRealizedPnlQuote, summarySnapshotTs],
  );

  const metrics = useMemo(
    () => getLiveAccountMetrics(summaryAccount, position, market, depth, latestMid),
    [summaryAccount, position, market, depth, latestMid],
  );
  const depthStats = useMemo(() => getDepthStats(depth), [depth]);
  const updatedTs = toNum(positionSourceTsMs ?? latestMarketTsMs ?? summarySnapshotTs);
  const activityCards = useMemo(
    () => [
      {
        label: "15m",
        fillCount: activity15mFillCount,
        makerRatio: activity15mMakerRatio,
        volumeBase: activity15mVolumeBase,
        notionalQuote: activity15mNotionalQuote,
        realizedPnlQuote: activity15mRealizedPnlQuote,
      },
      {
        label: "1h",
        fillCount: activity1hFillCount,
        makerRatio: activity1hMakerRatio,
        volumeBase: activity1hVolumeBase,
        notionalQuote: activity1hNotionalQuote,
        realizedPnlQuote: activity1hRealizedPnlQuote,
      },
    ],
    [
      activity15mFillCount,
      activity15mMakerRatio,
      activity15mNotionalQuote,
      activity15mRealizedPnlQuote,
      activity15mVolumeBase,
      activity1hFillCount,
      activity1hMakerRatio,
      activity1hNotionalQuote,
      activity1hRealizedPnlQuote,
      activity1hVolumeBase,
    ],
  );

  const items: Array<{ label: string; value: string; className?: string }> = [
    { label: "Mode", value: mode || "n/a" },
    { label: "Source", value: source || "n/a", className: "mono" },
    { label: "Mid", value: formatNumber(metrics.mark, 4) },
    { label: "Best Bid", value: formatNumber(depthStats.bestBid, 4) },
    { label: "Best Ask", value: formatNumber(depthStats.bestAsk, 4) },
    { label: "Position Side", value: String(position.side || "flat"), className: `pill ${sideTone(String(position.side || ""))}` },
    { label: "Position Qty", value: formatNumber(metrics.positionQty, 6) },
    { label: "Avg Entry", value: formatNumber(metrics.avgEntryPrice, 4) },
    {
      label: "Unrealized PnL",
      value: formatSigned(metrics.unrealizedPnl, 4),
      className:
        (metrics.unrealizedPnl || 0) > 0 ? "value-positive" : (metrics.unrealizedPnl || 0) < 0 ? "value-negative" : "value-neutral",
    },
    {
      label: "Realized PnL",
      value: formatSigned(metrics.realizedPnl, 4),
      className: (metrics.realizedPnl || 0) > 0 ? "value-positive" : (metrics.realizedPnl || 0) < 0 ? "value-negative" : "value-neutral",
    },
    { label: "Open Orders", value: String(ordersLength) },
    { label: "Fills Total", value: String(fillsTotal) },
    { label: "Updated", value: formatTs(updatedTs) },
  ];

  return (
    <Panel title="Position / Exposure" subtitle="Live position state, pricing context, and execution exposure." className="panel-span-4">
      <div className="kv-grid">
        {items.map((item) => (
          <div key={item.label} className="kv-card">
            <div className="kv-label">{item.label}</div>
            <div className={`kv-value ${item.className || ""}`.trim()}>{item.value}</div>
          </div>
        ))}
      </div>
      <div className="activity-window-grid">
        {activityCards.map((entry) => (
          <article key={entry.label} className="metric-card compact">
            <h3>{entry.label} activity</h3>
            <div className="metric-value">{String(entry.fillCount ?? 0)} fills</div>
            <dl>
              <dt>Maker</dt>
              <dd>{formatPct(entry.makerRatio ?? 0, 1)}</dd>
              <dt>Volume</dt>
              <dd>{formatNumber(entry.volumeBase ?? 0, 6)}</dd>
              <dt>Notional</dt>
              <dd>{formatNumber(entry.notionalQuote ?? 0, 2)}</dd>
              <dt>PnL</dt>
              <dd className={(Number(entry.realizedPnlQuote ?? 0) || 0) >= 0 ? "value-positive" : "value-negative"}>
                {formatSigned(entry.realizedPnlQuote ?? 0, 4)}
              </dd>
            </dl>
          </article>
        ))}
      </div>
    </Panel>
  );
}
