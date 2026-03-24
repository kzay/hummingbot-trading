import { memo, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatNumber } from "../utils/format";
import { getDepthStats } from "../utils/metrics";
import { Panel } from "./Panel";

const EMPTY_DEPTH_LEVELS: [] = [];
const MAX_DEPTH_ROWS = 15;

export const DepthLadderPanel = memo(function DepthLadderPanel() {
  const awaitingData = useDashboardStore((s) => s.connection.lastMessageTsMs === 0 && s.source === "");
  const depth = useDashboardStore(
    useShallow((state) => ({
      bestBid: state.depth.best_bid,
      bestAsk: state.depth.best_ask,
      bids: state.depth.bids,
      asks: state.depth.asks,
    })),
  );
  const orders = useDashboardStore((state) => state.orders);

  const stats = useMemo(
    () =>
      getDepthStats({
        best_bid: depth.bestBid,
        best_ask: depth.bestAsk,
        bids: depth.bids ?? EMPTY_DEPTH_LEVELS,
        asks: depth.asks ?? EMPTY_DEPTH_LEVELS,
      }),
    [depth],
  );

  const orderPriceSet = useMemo(() => {
    const set = new Set<string>();
    for (const o of orders) {
      const p = Number(o.price);
      if (Number.isFinite(p) && p > 0) set.add(p.toFixed(2));
    }
    return set;
  }, [orders]);

  const bids = depth.bids ?? EMPTY_DEPTH_LEVELS;
  const asks = depth.asks ?? EMPTY_DEPTH_LEVELS;
  const hasDepthData = bids.length > 0 || asks.length > 0;

  const { rowCount, maxBidSize, maxAskSize, bidCumulative, askCumulative } = useMemo(() => {
    if (!hasDepthData) {
      return { rowCount: 0, maxBidSize: 1, maxAskSize: 1, bidCumulative: [] as number[], askCumulative: [] as number[] };
    }
    const rc = Math.min(MAX_DEPTH_ROWS, Math.max(10, bids.length, asks.length));
    const mbs = Math.max(1, ...bids.slice(0, rc).map((e) => Number(e.size ?? 0) || 0));
    const mas = Math.max(1, ...asks.slice(0, rc).map((e) => Number(e.size ?? 0) || 0));
    const bc: number[] = [];
    const ac: number[] = [];
    let bSum = 0;
    let aSum = 0;
    for (let i = 0; i < rc; i++) {
      bSum += Number(bids[i]?.size ?? 0) || 0;
      aSum += Number(asks[i]?.size ?? 0) || 0;
      bc.push(bSum);
      ac.push(aSum);
    }
    return { rowCount: rc, maxBidSize: mbs, maxAskSize: mas, bidCumulative: bc, askCumulative: ac };
  }, [bids, asks, hasDepthData]);

  return (
    <Panel title="Depth Ladder" className="panel-span-4" loading={awaitingData}>
      <div className="panel-meta-row">
        <span className="meta-pill">Sprd {formatNumber(stats.spreadPct, 4)}%</span>
        <span className="meta-pill">Imb {formatNumber(stats.imbalance, 2)}</span>
        <span className="meta-pill">B {formatNumber(stats.bidVolume, 2)}</span>
        <span className="meta-pill">A {formatNumber(stats.askVolume, 2)}</span>
      </div>
      <div className="table-wrap table-tall">
        <table>
          <thead>
            <tr>
              <th scope="col">Cum</th>
              <th scope="col">Bid Size</th>
              <th scope="col">Bid</th>
              <th scope="col">Ask</th>
              <th scope="col">Ask Size</th>
              <th scope="col">Cum</th>
            </tr>
          </thead>
          <tbody>
            {rowCount === 0 ? (
              <tr>
                <td colSpan={6} className="empty-state-cell">Waiting for depth…</td>
              </tr>
            ) : (
              Array.from({ length: rowCount }).map((_, index) => {
                const bid = bids[index] || {};
                const ask = asks[index] || {};
                const bidSize = Number(bid.size ?? 0) || 0;
                const askSize = Number(ask.size ?? 0) || 0;
                const bidBarWidth = `${Math.min(100, (bidSize / maxBidSize) * 100)}%`;
                const askBarWidth = `${Math.min(100, (askSize / maxAskSize) * 100)}%`;
                const bidPrice = Number(bid.price ?? 0);
                const askPrice = Number(ask.price ?? 0);
                const bidHasOrder = bidPrice > 0 && orderPriceSet.has(bidPrice.toFixed(2));
                const askHasOrder = askPrice > 0 && orderPriceSet.has(askPrice.toFixed(2));

                return (
                  <tr
                    key={`depth-${index}`}
                    className={`${bid.price ? "row-bid" : ""} ${ask.price ? "row-ask" : ""} ${index === 0 ? "spread-row" : ""}`.trim()}
                  >
                    <td className="cumulative-cell">{formatNumber(bidCumulative[index], 3)}</td>
                    <td className="depth-size-cell">
                      <span className="depth-volume-bar depth-volume-bar-bid" style={{ width: bidBarWidth }} />
                      <span className="depth-cell-value">{formatNumber(bid.size, 4)}</span>
                    </td>
                    <td style={bidHasOrder ? { fontWeight: 700, color: "#5ea7ff" } : undefined}>
                      {formatNumber(bid.price, 2)}
                    </td>
                    <td style={askHasOrder ? { fontWeight: 700, color: "#5ea7ff" } : undefined}>
                      {formatNumber(ask.price, 2)}
                    </td>
                    <td className="depth-size-cell">
                      <span className="depth-volume-bar depth-volume-bar-ask" style={{ width: askBarWidth }} />
                      <span className="depth-cell-value">{formatNumber(ask.size, 4)}</span>
                    </td>
                    <td className="cumulative-cell">{formatNumber(askCumulative[index], 3)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
});
