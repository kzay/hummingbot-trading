import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatNumber } from "../utils/format";
import { getDepthStats } from "../utils/metrics";
import { Panel } from "./Panel";

const EMPTY_DEPTH_LEVELS: [] = [];

export function DepthLadderPanel() {
  const depth = useDashboardStore(
    useShallow((state) => ({
      bestBid: state.depth.best_bid,
      bestAsk: state.depth.best_ask,
      bids: state.depth.bids,
      asks: state.depth.asks,
    })),
  );
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

  const bids = depth.bids ?? EMPTY_DEPTH_LEVELS;
  const asks = depth.asks ?? EMPTY_DEPTH_LEVELS;
  const rowCount = Math.max(12, bids.length, asks.length);
  const maxBidSize = Math.max(1, ...bids.map((entry) => Number(entry.size ?? 0) || 0));
  const maxAskSize = Math.max(1, ...asks.map((entry) => Number(entry.size ?? 0) || 0));

  return (
    <Panel title="L2 Depth Ladder" subtitle="Top-of-book depth snapshot with spread and imbalance." className="panel-span-4">
      <div className="panel-meta-row">
        <span className="meta-pill">Spread {formatNumber(stats.spread, 4)}</span>
        <span className="meta-pill">Spread % {formatNumber(stats.spreadPct, 3)}%</span>
        <span className="meta-pill">Bid Vol {formatNumber(stats.bidVolume, 3)}</span>
        <span className="meta-pill">Ask Vol {formatNumber(stats.askVolume, 3)}</span>
        <span className="meta-pill">Imbalance {formatNumber(stats.imbalance, 3)}</span>
      </div>
      <div className="table-wrap table-tall">
        <table>
          <thead>
            <tr>
              <th>Bid Size</th>
              <th>Bid Price</th>
              <th>Ask Price</th>
              <th>Ask Size</th>
            </tr>
          </thead>
          <tbody>
            {rowCount === 0 ? (
              <tr>
                <td colSpan={4}>No depth available for current selection.</td>
              </tr>
            ) : (
              Array.from({ length: rowCount }).map((_, index) => {
                const bid = bids[index] || {};
                const ask = asks[index] || {};
                const bidSize = Number(bid.size ?? 0) || 0;
                const askSize = Number(ask.size ?? 0) || 0;
                const bidBarWidth = `${Math.min(100, (bidSize / maxBidSize) * 100)}%`;
                const askBarWidth = `${Math.min(100, (askSize / maxAskSize) * 100)}%`;
                return (
                  <tr
                    key={`depth-${index}`}
                    className={`${bid.price ? "row-bid" : ""} ${ask.price ? "row-ask" : ""} ${index === 0 ? "spread-row" : ""}`.trim()}
                  >
                    <td className="depth-size-cell">
                      <span className="depth-volume-bar depth-volume-bar-bid" style={{ width: bidBarWidth }} />
                      <span className="depth-cell-value">{formatNumber(bid.size, 6)}</span>
                    </td>
                    <td>{formatNumber(bid.price, 4)}</td>
                    <td>{formatNumber(ask.price, 4)}</td>
                    <td className="depth-size-cell">
                      <span className="depth-volume-bar depth-volume-bar-ask" style={{ width: askBarWidth }} />
                      <span className="depth-cell-value">{formatNumber(ask.size, 6)}</span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
