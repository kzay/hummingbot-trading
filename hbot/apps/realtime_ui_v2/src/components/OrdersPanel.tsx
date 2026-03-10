import { useMemo } from "react";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type { UiOrder } from "../types/realtime";
import { formatNumber } from "../utils/format";
import { sideTone } from "../utils/presentation";
import { Panel } from "./Panel";

export function OrdersPanel() {
  const { orderFilter, orders } = useDashboardStore(
    useShallow((state) => ({
      orderFilter: state.settings.orderFilter,
      orders: state.orders,
    })),
  );
  const updateSettings = useDashboardStore((state) => state.updateSettings);

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

  const columns = useMemo<ColumnDef<UiOrder>[]>(
    () => [
      {
        accessorFn: (row) => row.order_id || row.client_order_id || "",
        id: "order_id",
        header: "Order ID",
        cell: ({ row }) => <span className="mono">{String(row.getValue("order_id"))}</span>,
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
        cell: ({ row }) => formatNumber(row.getValue("price"), 4),
      },
      {
        accessorFn: (row) => row.amount ?? row.quantity ?? row.amount_base ?? 0,
        id: "amount",
        header: "Amount",
        cell: ({ row }) => formatNumber(row.getValue("amount"), 6),
      },
      {
        accessorKey: "state",
        header: "State",
        cell: ({ row }) => String(row.getValue("state") ?? "n/a"),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filteredOrders.slice(0, 100),
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Panel title="Open Orders" subtitle="Realtime working orders with dedicated order filtering." className="panel-span-6">
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
      <div className="panel-meta-row">
        <span className="meta-pill">Shown {filteredOrders.length}</span>
        <span className="meta-pill">Total {orders.length}</span>
      </div>
      <div className="table-wrap">
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
                <td colSpan={5}>No orders match the current filter.</td>
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
