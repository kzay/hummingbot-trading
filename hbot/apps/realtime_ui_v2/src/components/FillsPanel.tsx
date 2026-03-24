import { memo, useMemo, useRef, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type { UiFill } from "../types/realtime";
import { formatNumber, formatPct, formatSigned, toNum } from "../utils/format";
import { sideTone } from "../utils/presentation";
import { Panel } from "./Panel";

function normalizeFill(fill: UiFill): UiFill {
  const price = Number(fill.price ?? 0) || 0;
  const amountBase = Number(fill.amount_base ?? fill.amount ?? 0) || 0;
  return {
    ...fill,
    timestamp_ms: Number(fill.timestamp_ms ?? fill.ts ?? 0) || 0,
    side: String(fill.side ?? "").toUpperCase(),
    price,
    amount_base: amountBase,
    realized_pnl_quote: Number(fill.realized_pnl_quote ?? 0) || 0,
    notional_quote: Number(fill.notional_quote) || Math.abs(amountBase) * price,
    is_maker: Boolean(fill.is_maker),
  };
}

export const FillsPanel = memo(function FillsPanel() {
  const awaitingData = useDashboardStore((s) => s.connection.lastMessageTsMs === 0 && s.source === "");
  const { fillFilter, fillMaker, fillSide, fills, fillsTotal, accountRealizedPnl } = useDashboardStore(
    useShallow((state) => ({
      fillFilter: state.settings.fillFilter,
      fillMaker: state.settings.fillMaker,
      fillSide: state.settings.fillSide,
      fills: state.fills,
      fillsTotal: state.fillsTotal,
      accountRealizedPnl: state.summaryAccount.realized_pnl_quote,
    })),
  );
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const [sorting, setSorting] = useState<SortingState>([]);
  const prevCountRef = useRef(0);
  const newestTsRef = useRef(0);

  const normalizedFills = useMemo(() => fills.map((fill) => normalizeFill(fill)), [fills]);

  const filteredFills = useMemo(() => {
    const query = fillFilter.trim().toLowerCase();
    return normalizedFills.filter((fill) => {
      const side = String(fill.side ?? "").toLowerCase();
      if (fillSide !== "all" && side !== fillSide) {
        return false;
      }
      if (fillMaker === "maker" && !fill.is_maker) {
        return false;
      }
      if (fillMaker === "taker" && fill.is_maker) {
        return false;
      }
      if (!query) {
        return true;
      }
      return [
        fill.order_id,
        fill.side,
        fill.price,
        fill.amount_base,
        fill.realized_pnl_quote,
        fill.timestamp_ms,
        fill.notional_quote,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [fillFilter, fillMaker, fillSide, normalizedFills]);

  const columns = useMemo<ColumnDef<UiFill>[]>(
    () => [
      {
        accessorFn: (row) => Number(row.timestamp_ms ?? 0),
        id: "timestamp_ms",
        header: "Time",
        cell: ({ row }) => {
          const value = Number(row.getValue("timestamp_ms") || 0);
          return (
            <span title={value ? new Date(value).toISOString() : ""}>
              {value ? new Date(value).toLocaleTimeString() : "n/a"}
            </span>
          );
        },
      },
      {
        accessorKey: "side",
        header: "Side",
        cell: ({ row }) => {
          const side = String(row.getValue("side") ?? "");
          return <span className={`pill ${sideTone(side)}`}>{side || "N/A"}</span>;
        },
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => formatNumber(row.getValue("price"), 2),
      },
      {
        accessorKey: "amount_base",
        header: "Qty",
        cell: ({ row }) => formatNumber(row.getValue("amount_base"), 6),
      },
      {
        accessorFn: (row) => Number(row.notional_quote ?? Math.abs(Number(row.amount_base ?? 0)) * Number(row.price ?? 0)),
        id: "notional_quote",
        header: "Notional",
        cell: ({ row }) => formatNumber(row.getValue("notional_quote"), 2),
      },
      {
        accessorKey: "realized_pnl_quote",
        header: "PnL",
        cell: ({ row }) => {
          const value = Number(row.getValue("realized_pnl_quote") || 0);
          const className = value > 0 ? "value-positive" : value < 0 ? "value-negative" : "value-neutral";
          return <span className={className}>{formatSigned(value, 4)}</span>;
        },
      },
      {
        accessorFn: (row) => (row.is_maker ? "maker" : "taker"),
        id: "maker",
        header: "M/T",
        cell: ({ row }) => {
          const maker = String(row.getValue("maker") || "taker");
          return <span className={`pill ${maker === "maker" ? "good" : "neutral"}`}>{maker === "maker" ? "M" : "T"}</span>;
        },
      },
      {
        accessorKey: "order_id",
        header: "Order",
        cell: ({ row }) => {
          const fullId = String(row.getValue("order_id") ?? "");
          return (
            <span className="order-id-cell" title={fullId}>
              {fullId.length > 10 ? fullId.slice(0, 8) + "…" : fullId}
            </span>
          );
        },
      },
    ],
    [],
  );

  const tableData = useMemo(() => {
    const data = filteredFills.slice(-200).reverse();
    if (data.length > 0) {
      const topTs = Number(data[0]?.timestamp_ms ?? 0);
      if (topTs > newestTsRef.current) {
        newestTsRef.current = topTs;
      }
    }
    prevCountRef.current = data.length;
    return data;
  }, [filteredFills]);

  const table = useReactTable({
    data: tableData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const fillStats = useMemo(() => {
    let pnl = 0, notional = 0, fees = 0, buys = 0, sells = 0, makers = 0;
    for (const f of normalizedFills) {
      pnl += Number(f.realized_pnl_quote) || 0;
      notional += Number(f.notional_quote) || 0;
      fees += Number(f.fee_quote ?? 0) || 0;
      if (String(f.side).toUpperCase() === "BUY") buys += 1; else sells += 1;
      if (f.is_maker) makers += 1;
    }
    const total = normalizedFills.length;
    return { pnl, notional, fees, buys, sells, makers, makerPct: total > 0 ? makers / total : 0 };
  }, [normalizedFills]);
  const authoritativeRealizedPnl = toNum(accountRealizedPnl);
  const totalPnl = authoritativeRealizedPnl ?? fillStats.pnl;
  const pnlIsFromAccount = authoritativeRealizedPnl !== null;

  return (
    <Panel
      title={<>24h Fills<span className="panel-count">({Math.max(fillsTotal, fills.length)})</span></>}
      className="panel-span-8"
      loading={awaitingData}
      freshnessTsMs={undefined}
    >
      <div className="panel-toolbar">
        <label>
          Filter
          <input
            type="text"
            placeholder="order / side / price / pnl"
            value={fillFilter}
            onChange={(event) => updateSettings({ fillFilter: event.target.value })}
          />
        </label>
        <label>
          Side
          <select value={fillSide} onChange={(event) => updateSettings({ fillSide: event.target.value as "all" | "buy" | "sell" })}>
            <option value="all">All</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label>
          M/T
          <select
            value={fillMaker}
            onChange={(event) => updateSettings({ fillMaker: event.target.value as "all" | "maker" | "taker" })}
          >
            <option value="all">All</option>
            <option value="maker">Maker</option>
            <option value="taker">Taker</option>
          </select>
        </label>
      </div>
      <div className="panel-meta-row">
        <span
          className={`meta-pill ${totalPnl >= 0 ? "value-positive" : "value-negative"}`}
          title={pnlIsFromAccount ? "Source: account realized PnL" : "Source: sum of retained fill rows"}
        >
          Realized {formatSigned(totalPnl, 4)}{pnlIsFromAccount ? "" : "*"}
        </span>
        <span className="meta-pill">Notional {formatNumber(fillStats.notional, 2)}</span>
        <span className="meta-pill">Fees {formatNumber(fillStats.fees, 4)}</span>
        <span className="meta-pill">{fillStats.buys}B / {fillStats.sells}S</span>
        <span className="meta-pill">Maker {formatPct(fillStats.makerPct, 0)}</span>
        <span className="meta-pill">Shown {filteredFills.length}</span>
      </div>
      <div className="table-wrap table-tall">
        <table role="table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    scope="col"
                    key={header.id}
                    className={header.column.getCanSort() ? "sortable-header" : ""}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === "asc" ? <span className="sort-indicator">▲</span> : null}
                    {header.column.getIsSorted() === "desc" ? <span className="sort-indicator">▼</span> : null}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="empty-state-cell">No fills</td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row, idx) => {
                const ts = Number(row.original.timestamp_ms ?? 0);
                const isNew = idx === 0 && ts === newestTsRef.current && ts > 0;
                return (
                  <tr key={row.id} className={isNew ? "fill-row-new" : ""}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
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
