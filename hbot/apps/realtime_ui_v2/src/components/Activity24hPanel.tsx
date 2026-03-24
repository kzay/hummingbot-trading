import { memo, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type { UiFill } from "../types/realtime";
import { formatNumber, formatPct, formatSigned } from "../utils/format";
import { Panel } from "./Panel";

interface WindowStats {
  label: string;
  fillCount: number;
  makerRatio: number | null;
  volumeBase: number;
  notionalQuote: number;
  realizedPnl: number;
  feesQuote: number;
}

function computeSessionStats(fills: UiFill[]): Omit<WindowStats, "label"> {
  let makers = 0;
  let volume = 0;
  let notional = 0;
  let pnl = 0;
  let fees = 0;
  for (const f of fills) {
    const amt = Math.abs(Number(f.amount_base ?? f.amount ?? 0)) || 0;
    const px = Number(f.price ?? 0) || 0;
    volume += amt;
    notional += Number(f.notional_quote) || amt * px;
    pnl += Number(f.realized_pnl_quote ?? 0) || 0;
    fees += Number(f.fee_quote ?? 0) || 0;
    if (f.is_maker) makers += 1;
  }
  const total = fills.length;
  return {
    fillCount: total,
    makerRatio: total > 0 ? makers / total : null,
    volumeBase: volume,
    notionalQuote: notional,
    realizedPnl: pnl,
    feesQuote: fees,
  };
}

function ActivityCard({ w }: { w: WindowStats }) {
  return (
    <article className="metric-card compact">
      <h3>{w.label}</h3>
      <div className="metric-value">{w.fillCount} <span style={{ fontSize: 11, color: "var(--muted)" }}>fills</span></div>
      <dl>
        <dt>Maker</dt><dd>{w.makerRatio !== null ? formatPct(w.makerRatio, 1) : "—"}</dd>
        <dt>Volume</dt><dd>{formatNumber(w.volumeBase, 6)}</dd>
        <dt>Notional</dt><dd>{formatNumber(w.notionalQuote, 2)}</dd>
        <dt>Realized</dt>
        <dd className={w.realizedPnl >= 0 ? "value-positive" : "value-negative"}>
          {formatSigned(w.realizedPnl, 4)}
        </dd>
        <dt>Fees</dt><dd>{formatNumber(w.feesQuote, 4)}</dd>
      </dl>
    </article>
  );
}

export const Activity24hPanel = memo(function Activity24hPanel() {
  const awaiting = useDashboardStore((s) => s.connection.lastMessageTsMs === 0 && s.source === "");

  const {
    w15, w1h, fills,
  } = useDashboardStore(
    useShallow((s) => ({
      w15: s.summaryActivity.window_15m,
      w1h: s.summaryActivity.window_1h,
      fills: s.fills,
    })),
  );

  const session = useMemo(() => computeSessionStats(fills), [fills]);

  const windows: WindowStats[] = useMemo(() => [
    {
      label: "15 min",
      fillCount: w15?.fill_count ?? 0,
      makerRatio: w15?.maker_ratio ?? null,
      volumeBase: w15?.volume_base ?? 0,
      notionalQuote: w15?.notional_quote ?? 0,
      realizedPnl: w15?.realized_pnl_quote ?? 0,
      feesQuote: w15?.fees_quote ?? 0,
    },
    {
      label: "1 hour",
      fillCount: w1h?.fill_count ?? 0,
      makerRatio: w1h?.maker_ratio ?? null,
      volumeBase: w1h?.volume_base ?? 0,
      notionalQuote: w1h?.notional_quote ?? 0,
      realizedPnl: w1h?.realized_pnl_quote ?? 0,
      feesQuote: w1h?.fees_quote ?? 0,
    },
    {
      label: "Session",
      ...session,
    },
  ], [w15, w1h, session]);

  return (
    <Panel title="24h Activity" className="panel-span-4" loading={awaiting}>
      <div className="activity-stack">
        {windows.map((w) => (
          <ActivityCard key={w.label} w={w} />
        ))}
      </div>
    </Panel>
  );
});
