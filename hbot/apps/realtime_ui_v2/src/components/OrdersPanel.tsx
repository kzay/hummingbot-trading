import { memo, useMemo, useState } from "react";
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
import type { UiOrder } from "../types/realtime";
import { formatNumber } from "../utils/format";
import { sideTone } from "../utils/presentation";
import { Panel } from "./Panel";

export const OrdersPanel = memo(function OrdersPanel() {
  const awaitingData = useDashboardStore((s) => s.connection.lastMessageTsMs === 0 && s.source === "");
  const { orderFilter, orders } = useDashboardStore(
    useShallow((state) => ({
      orderFilter: state.settings.orderFilter,
      orders: state.orders,
    })),
  );
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const [sorting, setSorting] = useState<SortingState>([]);

  const filteredOrders = useMemo(() => {
    const query = orderFilter.trim().toLowerCase();
    if (!query) {
      return orders;
    }
    return orders.filter((order) =>
      [
        order.order_id,
        order.client_order_id,
        order.side,
        order.price,
        order.amount,
        order.quantity,
        order.amount_base,
        order.state,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [orderFilter, orders]);

  const estimatedCount = useMemo(() => orders.filter((o) => o.is_estimated).length, [orders]);
  const liveCount = orders.length - estimatedCount;

  const columns = useMemo<ColumnDef<UiOrder>[]>(
    () => [
      {
        accessorFn: (row) => row.order_id || row.client_order_id || "",
        id: "order_id",
        header: "ID",
        cell: ({ row }) => {
          const fullId = String(row.getValue("order_id"));
          return (
            <span className="order-id-cell" title={fullId}>
              {fullId.length > 10 ? fullId.slice(0, 8) + "…" : fullId}
            </span>
          );
        },
      },
      {
        accessorKey: "side",
        header: "Side",
        cell: ({ row }) => {
          const side = String(row.getValue("side") ?? "").toUpperCase();
          return <span className={`pill ${sideTone(side)}`}>{side || "N/A"}</span>;
        },
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => {
          const estimated = row.original.is_estimated;
          const value = formatNumber(row.getValue("price"), 2);
          return estimated ? <span title="Estimated from book">~{value}</span> : value;
        },
      },
      {
        accessorFn: (row) => row.amount ?? row.quantity ?? row.amount_base ?? null,
        id: "amount",
        header: "Qty",
        cell: ({ row }) => {
          const val = row.getValue("amount");
          return val === null || val === undefined ? "—" : formatNumber(val, 6);
        },
      },
      {
        accessorKey: "state",
        header: "State",
        cell: ({ row }) => {
          const state = String(row.getValue("state") ?? "n/a");
          const estimated = row.original.is_estimated;
          if (estimated) {
            return <span className="pill warn" title={`Source: ${row.original.estimate_source || "runtime"}`}>est</span>;
          }
          return state;
        },
      },
    ],
    [],
  );

  const tableData = useMemo(() => filteredOrders.slice(0, 100), [filteredOrders]);

  const table = useReactTable({
    data: tableData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Panel
      title={<>Orders<span className="panel-count">({liveCount}{estimatedCount > 0 ? <span title="Estimated placeholder orders"> +{estimatedCount} est</span> : null})</span></>}
      className="panel-span-4"
      loading={awaitingData}
      freshnessTsMs={undefined}
    >
      <div className="panel-toolbar">
        <label>
          Filter
          <input
            type="text"
            placeholder="id / side / price / state"
            value={orderFilter}
            onChange={(event) => updateSettings({ orderFilter: event.target.value })}
          />
        </label>
      </div>
      <div className="table-wrap">
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
                <td colSpan={5} className="empty-state-cell">No orders</td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className={row.original.is_estimated ? "row-estimated" : ""}>
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
});
