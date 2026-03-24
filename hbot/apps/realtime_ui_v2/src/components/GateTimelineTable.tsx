import type { GateTimelineEntry } from "../types/realtime";
import { formatAgeMs, formatRelativeTs, formatTs } from "../utils/format";
import { gateTone } from "../utils/presentation";

interface GateTimelineTableProps {
  rows: GateTimelineEntry[];
  emptyMessage: string;
}

export function GateTimelineTable({ rows, emptyMessage }: GateTimelineTableProps) {
  const safeRows = Array.isArray(rows) ? rows : [];

  return (
    <div className="table-wrap table-tall">
      <table>
        <thead>
          <tr>
            <th scope="col">Start</th>
            <th scope="col">End</th>
            <th scope="col">Duration</th>
            <th scope="col">Status</th>
            <th scope="col">Reason</th>
            <th scope="col">State / Regime</th>
          </tr>
        </thead>
        <tbody>
          {safeRows.length === 0 ? (
            <tr>
              <td colSpan={6}>{emptyMessage}</td>
            </tr>
          ) : (
            safeRows.map((row, index) => (
              <tr key={`${row.start_ts || row.start_ts_ms || "start"}-${index}`}>
                <td>
                  <div>{formatTs(row.start_ts || row.start_ts_ms)}</div>
                  <div className="subvalue">{formatRelativeTs(row.start_ts || row.start_ts_ms)}</div>
                </td>
                <td>
                  <div>{formatTs(row.end_ts || row.end_ts_ms)}</div>
                  <div className="subvalue">{formatRelativeTs(row.end_ts || row.end_ts_ms)}</div>
                </td>
                <td>{formatAgeMs((Number(row.duration_seconds || 0) || 0) * 1000)}</td>
                <td>
                  <span className={`pill ${gateTone(String(row.quoting_status || ""))}`}>{String(row.quoting_status || "n/a")}</span>
                </td>
                <td>
                  <div>{String(row.quoting_reason || "n/a")}</div>
                  <div className="subvalue">Orders {String(row.orders_active ?? 0)}</div>
                </td>
                <td>
                  <div>
                    {String(row.controller_state || "n/a")} / {String(row.regime || "n/a").replaceAll("_", " ")}
                  </div>
                  <div className="subvalue">{String(row.risk_reasons || "no risk tags")}</div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
