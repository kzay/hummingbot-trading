import type { SummaryAccount, UiDepth, UiMarket, UiPosition } from "../types/realtime";
import { toNum } from "./format";

export interface LiveAccountMetrics {
  mark: number | null;
  side: string;
  positionQty: number | null;
  avgEntryPrice: number | null;
  unrealizedPnl: number | null;
  realizedPnl: number | null;
  equityQuote: number | null;
  equityOpenQuote: number | null;
  equityPeakQuote: number | null;
  totalPnl: number | null;
  deltaVsOpenQuote: number | null;
  deltaVsPeakQuote: number | null;
  returnVsOpen: number | null;
  quoteBalance: number | null;
}

export interface DepthStats {
  bestBid: number | null;
  bestAsk: number | null;
  spread: number | null;
  spreadPct: number | null;
  bidVolume: number;
  askVolume: number;
  imbalance: number | null;
}

export function depthMid(depth: UiDepth): number | null {
  const bestBid = toNum(depth.best_bid ?? depth.bids?.[0]?.price);
  const bestAsk = toNum(depth.best_ask ?? depth.asks?.[0]?.price);
  if (bestBid !== null && bestAsk !== null) {
    return (bestBid + bestAsk) / 2;
  }
  return bestBid ?? bestAsk ?? null;
}

export function currentMarkPrice(market: UiMarket, depth: UiDepth, latestMid: number | null): number | null {
  return toNum(market.mid_price) ?? latestMid ?? depthMid(depth);
}

export function getLiveAccountMetrics(
  account: SummaryAccount,
  position: UiPosition,
  market: UiMarket,
  depth: UiDepth,
  latestMid: number | null,
): LiveAccountMetrics {
  const mark = currentMarkPrice(market, depth, latestMid);
  const qtyRaw = toNum(position.quantity);
  const qtyAbs = qtyRaw !== null ? Math.abs(qtyRaw) : 0;
  const avgEntryPrice = toNum(position.avg_entry_price);
  const storedUnrealized = toNum(position.unrealized_pnl);
  const side = String(position.side || "").trim().toLowerCase();
  let direction = 0;
  if (qtyAbs > 0) {
    direction = side === "short" ? -1 : side === "long" ? 1 : (qtyRaw || 0) < 0 ? -1 : 1;
  }
  let unrealizedPnl = storedUnrealized;
  if (mark !== null && avgEntryPrice !== null && avgEntryPrice > 0 && qtyAbs > 0 && direction !== 0) {
    unrealizedPnl = (mark - avgEntryPrice) * qtyAbs * direction;
  }

  const realizedPnl = toNum(account.realized_pnl_quote);
  const quoteBalance = toNum(account.quote_balance);
  const snapshotEquity = toNum(account.equity_quote);
  const equityOpenQuote = toNum(account.equity_open_quote);
  const equityPeakQuote = toNum(account.equity_peak_quote);

  let equityQuote = snapshotEquity;
  if (snapshotEquity !== null && unrealizedPnl !== null) {
    equityQuote = snapshotEquity - (storedUnrealized || 0) + unrealizedPnl;
  } else if (quoteBalance !== null && unrealizedPnl !== null) {
    equityQuote = quoteBalance + unrealizedPnl;
  }

  const totalPnl =
    realizedPnl !== null || unrealizedPnl !== null ? Number(realizedPnl || 0) + Number(unrealizedPnl || 0) : null;
  const deltaVsOpenQuote = equityQuote !== null && equityOpenQuote !== null ? equityQuote - equityOpenQuote : null;
  const deltaVsPeakQuote = equityQuote !== null && equityPeakQuote !== null ? equityQuote - equityPeakQuote : null;
  const returnVsOpen =
    deltaVsOpenQuote !== null && equityOpenQuote !== null && equityOpenQuote !== 0 ? deltaVsOpenQuote / equityOpenQuote : null;

  return {
    mark,
    side,
    positionQty: qtyRaw,
    avgEntryPrice,
    unrealizedPnl,
    realizedPnl,
    equityQuote,
    equityOpenQuote,
    equityPeakQuote,
    totalPnl,
    deltaVsOpenQuote,
    deltaVsPeakQuote,
    returnVsOpen,
    quoteBalance,
  };
}

export function getDepthStats(depth: UiDepth): DepthStats {
  const bids = Array.isArray(depth.bids) ? depth.bids : [];
  const asks = Array.isArray(depth.asks) ? depth.asks : [];
  const bestBid = toNum(depth.best_bid ?? bids[0]?.price);
  const bestAsk = toNum(depth.best_ask ?? asks[0]?.price);
  const spread = bestBid !== null && bestAsk !== null ? bestAsk - bestBid : null;
  const spreadPct =
    spread !== null && bestBid !== null && bestAsk !== null && bestBid + bestAsk > 0
      ? (spread / ((bestBid + bestAsk) / 2)) * 100
      : null;
  const bidVolume = bids.reduce((sum, row) => sum + Math.max(0, Number(row.size || 0) || 0), 0);
  const askVolume = asks.reduce((sum, row) => sum + Math.max(0, Number(row.size || 0) || 0), 0);
  const imbalance = bidVolume + askVolume > 0 ? (bidVolume - askVolume) / (bidVolume + askVolume) : null;

  return {
    bestBid,
    bestAsk,
    spread,
    spreadPct,
    bidVolume,
    askVolume,
    imbalance,
  };
}
