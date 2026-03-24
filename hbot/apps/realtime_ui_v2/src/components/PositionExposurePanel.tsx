import { memo, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatNumber, formatSigned } from "../utils/format";
import { currentMarkPrice } from "../utils/metrics";
import { sideTone } from "../utils/presentation";
import { Panel } from "./Panel";

export const PositionExposurePanel = memo(function PositionExposurePanel() {
  const awaiting = useDashboardStore((s) => s.connection.lastMessageTsMs === 0 && s.source === "");

  const {
    midPrice, bestBid, bestAsk, latestMid,
    qty, side, entry, unrealPnl,
    equityQuote, ordersLen, positionTsMs,
  } = useDashboardStore(
    useShallow((s) => ({
      midPrice: s.market.mid_price,
      bestBid: s.depth.best_bid,
      bestAsk: s.depth.best_ask,
      latestMid: s.latestMid,
      qty: s.position.quantity,
      side: s.position.side,
      entry: s.position.avg_entry_price,
      unrealPnl: s.position.unrealized_pnl,
      equityQuote: s.summaryAccount.equity_quote,
      ordersLen: s.orders.length,
      positionTsMs: s.freshness.positionTsMs,
    })),
  );

  const mark = useMemo(
    () => currentMarkPrice({ mid_price: midPrice }, { best_bid: bestBid, best_ask: bestAsk }, latestMid),
    [midPrice, bestBid, bestAsk, latestMid],
  );

  const rawQty = Math.abs(Number(qty ?? 0));
  const qtyNum = rawQty > 1e-12 ? rawQty : 0;
  const sideStr = String(side || "").trim().toLowerCase();
  const isFlat = sideStr === "flat" || sideStr === "" || qtyNum === 0;
  const entryNum = isFlat ? 0 : Number(entry ?? 0) || 0;
  const markNum = mark ?? 0;
  const direction = sideStr === "short" ? -1 : sideStr === "long" ? 1 : 0;

  let unrealized = Number(unrealPnl ?? 0) || 0;
  if (mark !== null && entryNum > 0 && qtyNum > 0 && direction !== 0) {
    unrealized = (markNum - entryNum) * qtyNum * direction;
  }

  const notional = qtyNum * markNum;
  const eqNum = Number(equityQuote ?? 0) || 0;
  const leverage = eqNum > 0 ? notional / eqNum : 0;

  const items: Array<{ label: string; value: string; className?: string }> = [
    { label: "Side", value: sideStr || "flat", className: `pill ${sideTone(sideStr)}` },
    { label: "Qty", value: formatNumber(qtyNum, 6) },
    { label: "Entry", value: isFlat ? "—" : formatNumber(entryNum, 2) },
    { label: "Mark", value: formatNumber(markNum, 2) },
    {
      label: "Unrealized",
      value: formatSigned(unrealized, 4),
      className: unrealized > 0 ? "value-positive" : unrealized < 0 ? "value-negative" : "value-neutral",
    },
    { label: "Notional", value: formatNumber(notional, 2) },
    { label: "Leverage", value: leverage > 0 ? `${formatNumber(leverage, 2)}×` : "—" },
    { label: "Orders", value: String(ordersLen) },
  ];

  return (
    <Panel title="Position" className="panel-span-4" loading={awaiting} freshnessTsMs={positionTsMs}>
      <div className="kv-grid">
        {items.map((it) => (
          <div key={it.label} className="kv-card">
            <div className="kv-label">{it.label}</div>
            <div className={`kv-value ${it.className || ""}`.trim()}>{it.value}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
});
