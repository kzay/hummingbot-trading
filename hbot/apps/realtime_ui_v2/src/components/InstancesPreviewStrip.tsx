import { useEffect, useMemo, useState } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { buildHeaders } from "../utils/fetch";
import { formatNumber, formatSigned } from "../utils/format";
import { signedClass } from "../utils/presentation";
import type { InstanceStatusRow } from "../utils/realtimeParsers";
import { parseInstancesPayload } from "../utils/realtimeParsers";

const REQUEST_TIMEOUT_MS = 8_000;
const REFRESH_INTERVAL_MS = 30_000;

interface InstancesPreviewStripProps {
  embedded?: boolean;
}

export function InstancesPreviewStrip({ embedded = false }: InstancesPreviewStripProps) {
  const apiBase = useDashboardStore((state) => state.settings.apiBase);
  const apiToken = useDashboardStore((state) => state.settings.apiToken);
  const instanceName = useDashboardStore((state) => state.settings.instanceName);
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const setInstanceNames = useDashboardStore((state) => state.setInstanceNames);
  const setInstanceStatuses = useDashboardStore((state) => state.setInstanceStatuses);
  const [rows, setRows] = useState<InstanceStatusRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    let activeController: AbortController | null = null;

    const refresh = async () => {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      try {
        const response = await fetch(`${apiBase}/api/v1/instances`, {
          headers: buildHeaders(apiToken),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`/api/v1/instances HTTP ${response.status}`);
        }
        const payload = parseInstancesPayload(await response.json());
        if (cancelled) {
          return;
        }
        const nextRows = Array.isArray(payload.statuses) ? payload.statuses : [];
        setRows(nextRows);
        setInstanceNames(nextRows.map((entry) => String(entry.instance_name ?? "")));
        setInstanceStatuses(nextRows);
        setError("");
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) {
          return;
        }
        setRows([]);
        setInstanceNames([]);
        setInstanceStatuses([], err instanceof Error ? err.message : String(err));
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        window.clearTimeout(timeoutId);
        if (!cancelled) {
          timer = window.setTimeout(() => {
            void refresh();
          }, REFRESH_INTERVAL_MS);
        }
      }
    };

    void refresh();

    return () => {
      cancelled = true;
      activeController?.abort();
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [apiBase, apiToken, setInstanceNames, setInstanceStatuses]);

  const sortedRows = useMemo(
    () =>
      [...rows].sort((left, right) =>
        String(left.instance_name ?? "").localeCompare(String(right.instance_name ?? "")),
      ),
    [rows],
  );

  if (!sortedRows.length && !error) {
    return null;
  }

  return (
    <section className={`instance-preview-strip ${embedded ? "embedded" : ""}`.trim()}>
      {!embedded && (
        <div className="instance-preview-header">
          <div>
            <h2>Instances</h2>
          </div>
          {error ? <span className="pill fail">{error}</span> : null}
        </div>
      )}
      <div className="instance-preview-grid">
        {sortedRows.map((row) => {
          const rowName = String(row.instance_name ?? "").trim();
          const isActive = rowName !== "" && rowName === instanceName;
          return (
            <button
              key={rowName || `instance-${String(row.trading_pair ?? "")}`}
              type="button"
              className={`instance-preview-card ${isActive ? "active" : ""}`.trim()}
              onClick={() => {
                if (!rowName) return;
                updateSettings({ instanceName: rowName });
              }}
            >
              <div className="instance-preview-topline">
                <div className="instance-preview-name-wrap">
                  <div className={`instance-preview-icon ${rowName === "shared" ? "shared" : ""}`}>
                    {rowName === "shared" ? "👥" : "₿"}
                  </div>
                  <span className="instance-preview-name">{rowName || "unknown"}</span>
                </div>
                <span className="instance-preview-status">LIVE</span>
              </div>
              <div className="instance-preview-values">
                <div className="instance-preview-row">
                  <span className="instance-preview-label">Equity</span>
                  <div className="instance-preview-value">{formatNumber(row.equity_quote, 2)}</div>
                </div>
                {row.equity_delta_open_quote !== undefined ? (
                  <div className="instance-preview-row">
                    <span className="instance-preview-label">Vs Open</span>
                    <div className={`instance-preview-value ${signedClass(row.equity_delta_open_quote)}`}>
                      {formatSigned(row.equity_delta_open_quote, 2)}
                    </div>
                  </div>
                ) : (
                  <div className="instance-preview-row">
                    <span className="instance-preview-label">Realized</span>
                    <div className={`instance-preview-value ${signedClass(row.realized_pnl_quote)}`}>
                      {formatSigned(row.realized_pnl_quote, 2)}
                    </div>
                  </div>
                )}
                <div className="instance-preview-row">
                  <span className="instance-preview-label">Unrealized</span>
                  <div className={`instance-preview-value ${signedClass(row.unrealized_pnl_quote)}`}>
                    {row.unrealized_pnl_quote != null ? formatSigned(row.unrealized_pnl_quote, 2) : "n/a"}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
