import { useMemo } from "react";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type { UiFill } from "../types/realtime";
import { formatNumber, formatRelativeTs, formatSigned } from "../utils/format";
import { sideTone } from "../utils/presentation";
import { Panel } from "./Panel";

function normalizeFill(fill: UiFill): UiFill {
  return {
    ...fill,
    timestamp_ms: Number(fill.timestamp_ms ?? fill.ts ?? 0) || 0,
    side: String(fill.side ?? "").toUpperCase(),
    price: Number(fill.price ?? 0) || 0,
    amount_base: Number(fill.amount_base ?? fill.amount ?? 0) || 0,
    realized_pnl_quote: Number(fill.realized_pnl_quote ?? 0) || 0,
    notional_quote: Number(fill.notional_quote ?? 0) || 0,
    is_maker: Boolean(fill.is_maker),
  };
}

export function FillsPanel() {
  const { fillFilter, fillMaker, fillSide, fills, fillsTotal } = useDashboardStore(
    useShallow((state) => ({
      fillFilter: state.settings.fillFilter,
      fillMaker: state.settings.fillMaker,
      fillSide: state.settings.fillSide,
      fills: state.fills,
      fillsTotal: state.fillsTotal,
    })),
  );
  const updateSettings = useDashboardStore((state) => state.updateSettings);

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
            <div>
              <div>{value ? new Date(value).toLocaleTimeString() : "n/a"}</div>
              <div className="subvalue">{formatRelativeTs(value)}</div>
            </div>
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
        cell: ({ row }) => formatNumber(row.getValue("price"), 4),
      },
      {
        accessorKey: "amount_base",
        header: "Amount",
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
        header: "Pnl",
        cell: ({ row }) => {
          const value = Number(row.getValue("realized_pnl_quote") || 0);
          const className = value > 0 ? "value-positive" : value < 0 ? "value-negative" : "value-neutral";
          return <span className={className}>{formatSigned(value, 4)}</span>;
        },
      },
      {
        accessorFn: (row) => (row.is_maker ? "maker" : "taker"),
        id: "maker",
        header: "Maker",
        cell: ({ row }) => {
          const maker = String(row.getValue("maker") || "taker");
          return <span className={`pill ${maker === "maker" ? "good" : "neutral"}`}>{maker}</span>;
        },
      },
      {
        accessorKey: "order_id",
        header: "Order",
        cell: ({ row }) => <span className="mono">{String(row.getValue("order_id") ?? "")}</span>,
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filteredFills.slice(-120).reverse(),
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Panel title="Fills" subtitle="Realtime fills with side and maker/taker filter stack." className="panel-span-12">
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
          Maker
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
        <span className="meta-pill">Shown {filteredFills.length}</span>
        <span className="meta-pill">Buffered {fills.length}</span>
        <span className="meta-pill">Total {Math.max(fillsTotal, fills.length)}</span>
      </div>
      <div className="table-wrap table-tall">
        <table>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={8}>No fills match the current filter stack.</td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
