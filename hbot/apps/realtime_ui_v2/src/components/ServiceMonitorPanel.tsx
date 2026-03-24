import { memo, useEffect, useMemo, useState } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { buildHeaders } from "../utils/fetch";
import { formatAgeMs, formatNumber } from "../utils/format";
import { gatePriority, gateTone } from "../utils/presentation";
import type { HealthPayload } from "../utils/realtimeParsers";
import { parseHealthPayload } from "../utils/realtimeParsers";
import { Panel } from "./Panel";

const REQUEST_TIMEOUT_MS = 8_000;
const REFRESH_INTERVAL_MS = 30_000;

export const ServiceMonitorPanel = memo(function ServiceMonitorPanel() {
  const apiBase = useDashboardStore((state) => state.settings.apiBase);
  const apiToken = useDashboardStore((state) => state.settings.apiToken);
  const selectedInstanceName = useDashboardStore((state) => state.settings.instanceName);
  const timeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const sharedHealthStatus = useDashboardStore((state) => state.health.status);
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const instanceStatuses = useDashboardStore((state) => state.instanceStatuses);
  const instanceStatusesError = useDashboardStore((state) => state.instanceStatusesError);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [error, setError] = useState<string>("");
  const [refreshNonce, setRefreshNonce] = useState(0);

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
        const headers = buildHeaders(apiToken);
        const response = await fetch(`${apiBase}/health`, {
          headers,
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`/health HTTP ${response.status}`);
        }
        const healthJson = parseHealthPayload(await response.json());
        if (cancelled) return;
        setHealth(healthJson);
        setError("");
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        setHealth(null);
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
  }, [refreshNonce, apiBase, apiToken]);

  const combinedError = error || instanceStatusesError;
  const rows = useMemo(
    () =>
      [...instanceStatuses].sort((left, right) => {
        const priorityDelta = gatePriority(String(left.freshness ?? "")) - gatePriority(String(right.freshness ?? ""));
        if (priorityDelta !== 0) {
          return priorityDelta;
        }
        return String(left.instance_name ?? "").localeCompare(String(right.instance_name ?? ""));
      }),
    [instanceStatuses],
  );
  const metrics = health?.metrics ?? {};
  const liveCount = rows.filter((row) => String(row.freshness ?? "").toLowerCase() === "live").length;
  const attentionCount = rows.filter((row) => gatePriority(String(row.freshness ?? "")) <= 1).length;
  const quotingCount = rows.filter((row) => gateTone(String(row.quoting_status ?? "")) === "ok").length;

  return (
    <>
      <Panel
        title="Live Data Service"
        subtitle="API status, transport freshness, fallback posture, and current buffer coverage."
        className="panel-span-12"
        actions={
          <button type="button" className="secondary" onClick={() => setRefreshNonce((value) => value + 1)}>
            Refresh service
          </button>
        }
      >
        {combinedError ? <div className="empty-state">Service monitor unavailable: {combinedError}</div> : null}
        <div className="metric-grid">
          <article className="metric-card">
            <h3>Service Status</h3>
            <div className="metric-value">{health?.status ?? sharedHealthStatus ?? "unknown"}</div>
            <dl>
              <dt>Mode</dt>
              <dd>{health?.mode ?? "n/a"}</dd>
              <dt>Redis</dt>
              <dd>{health?.redis_available ? "up" : "down"}</dd>
              <dt>DB</dt>
              <dd>{health?.db_enabled ? (health?.db_available ? "up" : "down") : "disabled"}</dd>
              <dt>Fallback</dt>
              <dd>{health?.fallback_active ? "active" : "off"}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Freshness</h3>
            <div className="metric-value">{formatAgeMs(health?.stream_age_ms ?? null)}</div>
            <dl>
              <dt>Tracked instances</dt>
              <dd>{instanceStatuses.length}</dd>
              <dt>Live instances</dt>
              <dd>{liveCount}</dd>
              <dt>Subscribers</dt>
              <dd>{metrics.subscribers ?? 0}</dd>
              <dt>Market keys</dt>
              <dd>{metrics.market_keys ?? 0}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Buffers</h3>
            <div className="metric-value">{formatNumber(metrics.market_quote_keys ?? 0, 0)}</div>
            <dl>
              <dt>Quote keys</dt>
              <dd>{metrics.market_quote_keys ?? 0}</dd>
              <dt>Depth keys</dt>
              <dd>{metrics.market_depth_keys ?? metrics.depth_keys ?? 0}</dd>
              <dt>Fill keys</dt>
              <dd>{metrics.fills_keys ?? 0}</dd>
              <dt>Paper keys</dt>
              <dd>{metrics.paper_event_keys ?? 0}</dd>
              <dt>Queue drops</dt>
              <dd>{metrics.subscriber_drops ?? 0}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Selection</h3>
            <div className="metric-value">{selectedInstanceName || "n/a"}</div>
            <dl>
              <dt>API</dt>
              <dd className="mono">{apiBase}</dd>
              <dt>Timeframe</dt>
              <dd>{timeframeS}s</dd>
              <dt>Token</dt>
              <dd>{apiToken ? "set" : "empty"}</dd>
              <dt>Rows</dt>
              <dd>{rows.length}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Attention</h3>
            <div className="metric-value">{attentionCount}</div>
            <dl>
              <dt>Needs attention</dt>
              <dd>{attentionCount}</dd>
              <dt>Quoting now</dt>
              <dd>{quotingCount}</dd>
              <dt>Live rows</dt>
              <dd>{liveCount}</dd>
              <dt>Fetch status</dt>
              <dd>{combinedError ? "error" : "ok"}</dd>
            </dl>
          </article>
        </div>
      </Panel>

      <Panel
        title="Instance Coverage"
        subtitle="Per-instance freshness, source path, and quoting state from `/api/v1/instances`."
        className="panel-span-12"
      >
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th scope="col">Instance</th>
                <th scope="col">Freshness</th>
                <th scope="col">Source</th>
                <th scope="col">Controller</th>
                <th scope="col">Pair</th>
                <th scope="col">Stream Age</th>
                <th scope="col">Quote</th>
                <th scope="col">Orders</th>
                <th scope="col">Realized</th>
                <th scope="col">Equity</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={11} className="empty-state">
                    No instance coverage rows available.
                  </td>
                </tr>
              ) : (
                rows.map((row, index) => {
                  const instanceName = String(row.instance_name ?? "").trim();
                  const isSelected = instanceName !== "" && instanceName === selectedInstanceName;
                  return (
                  <tr
                    key={`${String(row.instance_name ?? "instance")}-${index}`}
                    className={`instance-row ${isSelected ? "selected" : ""}`.trim()}
                  >
                    <td className="mono">{String(row.instance_name ?? "")}</td>
                    <td><span className={`pill ${gateTone(String(row.freshness ?? ""))}`}>{String(row.freshness ?? "n/a")}</span></td>
                    <td className="mono">{String(row.source_label ?? "")}</td>
                    <td>{String(row.controller_id ?? "")}</td>
                    <td>{String(row.trading_pair ?? "")}</td>
                    <td>{formatAgeMs(row.stream_age_ms ?? null)}</td>
                    <td><span className={`pill ${gateTone(String(row.quoting_status ?? ""))}`}>{String(row.quoting_status ?? "n/a")}</span></td>
                    <td>{formatNumber(row.orders_active ?? 0, 0)}</td>
                    <td>{formatNumber(row.realized_pnl_quote ?? 0, 2)}</td>
                    <td>{formatNumber(row.equity_quote ?? 0, 2)}</td>
                    <td>
                      <button
                        type="button"
                        className="secondary table-action-btn"
                        onClick={() => {
                          if (!instanceName) {
                            return;
                          }
                          updateSettings({ instanceName });
                        }}
                      >
                        {isSelected ? "Selected" : "Select"}
                      </button>
                    </td>
                  </tr>
                );
                })
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
});
