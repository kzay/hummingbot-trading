import { useEffect, useState } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatAgeMs, formatNumber } from "../utils/format";
import { gateTone } from "../utils/presentation";
import type { HistoryPayload } from "../utils/realtimeParsers";
import { parseHistoryPayload } from "../utils/realtimeParsers";
import { Panel } from "./Panel";

const REQUEST_TIMEOUT_MS = 8_000;
const REFRESH_INTERVAL_MS = 30_000;

function buildHeaders(token: string): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

async function fetchJsonWithTimeout<T>(url: string, headers: HeadersInit, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { headers, signal });
  if (!response.ok) {
    throw new Error(`${new URL(url).pathname} HTTP ${response.status}`);
  }
  return parseHistoryPayload(await response.json()) as T;
}

export function HistoryMonitorPanel() {
  const apiBase = useDashboardStore((state) => state.settings.apiBase);
  const apiToken = useDashboardStore((state) => state.settings.apiToken);
  const histInstanceName = useDashboardStore((state) => state.settings.instanceName);
  const histTimeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const healthStatus = useDashboardStore((state) => state.health.status);
  const [payload, setPayload] = useState<HistoryPayload | null>(null);
  const [error, setError] = useState<string>("");
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    let activeController: AbortController | null = null;

    const refresh = async () => {
      if (!histInstanceName.trim()) {
        return;
      }
      if (String(healthStatus ?? "").trim().toLowerCase() === "disabled") {
        setPayload(null);
        setError("Realtime UI API mode is disabled.");
        timer = window.setTimeout(() => {
          void refresh();
        }, REFRESH_INTERVAL_MS);
        return;
      }
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      try {
        const params = new URLSearchParams();
        params.set("instance_name", histInstanceName.trim());
        params.set("timeframe_s", String(histTimeframeS || 60));
        params.set("limit", "300");
        const json = await fetchJsonWithTimeout<HistoryPayload>(
          `${apiBase}/api/v1/candles?${params.toString()}`,
          buildHeaders(apiToken),
          controller.signal,
        );
        if (cancelled) return;
        setPayload(json);
        setError("");
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        setPayload(null);
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
  }, [healthStatus, refreshNonce, apiBase, apiToken, histInstanceName, histTimeframeS]);

  const quality = payload?.quality ?? payload?.shadow?.provider?.quality ?? {};
  const parity = payload?.shadow?.parity ?? {};
  const anomalyCount =
    Number(parity.mismatched_buckets ?? 0) + Number(parity.missing_in_shared ?? 0) + Number(parity.missing_in_legacy ?? 0);
  const attentionLabel = error
    ? "fetch error"
    : anomalyCount > 0
      ? "parity drift"
      : String(quality.status ?? payload?.mode ?? "unknown");

  return (
    <>
      <Panel
        title="Shared History Monitor"
        subtitle="Read mode, source chain, and provider quality for the selected instance and pair."
        className="panel-span-12"
        actions={
          <div className="panel-actions-row">
            <div className="panel-meta-row">
              <span className="meta-pill">Instance {histInstanceName || "n/a"}</span>
              <span className="meta-pill">Pair {String(payload?.trading_pair || "n/a")}</span>
              <span className="meta-pill">Timeframe {histTimeframeS}s</span>
            </div>
            <button type="button" className="secondary" onClick={() => setRefreshNonce((value) => value + 1)}>
              Refresh history
            </button>
          </div>
        }
      >
        {error ? <div className="empty-state">History monitor unavailable: {error}</div> : null}
        <div className="metric-grid">
          <article className="metric-card">
            <h3>Read Path</h3>
            <div className="metric-value">{payload?.mode ?? "unknown"}</div>
            <dl>
              <dt>Source</dt>
              <dd className="mono">{payload?.source ?? "n/a"}</dd>
              <dt>DB Available</dt>
              <dd>{payload?.db_available ? "yes" : "no"}</dd>
              <dt>CSV Failover</dt>
              <dd>{payload?.csv_failover_used ? "used" : "off"}</dd>
              <dt>Source Chain</dt>
              <dd className="mono">{(payload?.source_chain ?? []).join(" -> ") || "n/a"}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Quality</h3>
            <div className="metric-value">{String(quality.status ?? "unknown")}</div>
            <dl>
              <dt>Freshness</dt>
              <dd>{formatAgeMs(quality.freshness_ms ?? null)}</dd>
              <dt>Coverage</dt>
              <dd>{formatNumber(Number(quality.coverage_ratio ?? 0) * 100, 1)}%</dd>
              <dt>Max Gap</dt>
              <dd>{formatNumber(quality.max_gap_s ?? 0, 0)} s</dd>
              <dt>Reason</dt>
              <dd>{String(quality.degraded_reason ?? "none")}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Bars</h3>
            <div className="metric-value">{formatNumber(quality.bars_returned ?? payload?.candles?.length ?? 0, 0)}</div>
            <dl>
              <dt>Returned</dt>
              <dd>{formatNumber(quality.bars_returned ?? payload?.candles?.length ?? 0, 0)}</dd>
              <dt>Requested</dt>
              <dd>{formatNumber(quality.bars_requested ?? 0, 0)}</dd>
              <dt>Provider Source</dt>
              <dd className="mono">{String(quality.source_used ?? "n/a")}</dd>
              <dt>Candle Rows</dt>
              <dd>{formatNumber(payload?.candles?.length ?? 0, 0)}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Shadow</h3>
            <div className="metric-value">{payload?.shadow ? "active" : "n/a"}</div>
            <dl>
              <dt>Mode</dt>
              <dd>{payload?.shadow?.mode ?? "n/a"}</dd>
              <dt>Mismatch</dt>
              <dd>{formatNumber(parity.mismatched_buckets ?? 0, 0)}</dd>
              <dt>Missing Shared</dt>
              <dd>{formatNumber(parity.missing_in_shared ?? 0, 0)}</dd>
              <dt>Max Close Delta</dt>
              <dd>{formatNumber(parity.max_abs_close_delta ?? 0, 8)}</dd>
            </dl>
          </article>
          <article className="metric-card">
            <h3>Attention</h3>
            <div className="metric-value">
              <span className={`pill ${gateTone(attentionLabel)}`}>{attentionLabel}</span>
            </div>
            <dl>
              <dt>Parity Issues</dt>
              <dd>{formatNumber(anomalyCount, 0)}</dd>
              <dt>Mismatched</dt>
              <dd>{formatNumber(parity.mismatched_buckets ?? 0, 0)}</dd>
              <dt>Missing Shared</dt>
              <dd>{formatNumber(parity.missing_in_shared ?? 0, 0)}</dd>
              <dt>Missing Legacy</dt>
              <dd>{formatNumber(parity.missing_in_legacy ?? 0, 0)}</dd>
            </dl>
          </article>
        </div>
      </Panel>

      <Panel
        title="History Details"
        subtitle="Detailed parity and quality fields returned by `/api/v1/candles`."
        className="panel-span-12"
      >
        <div className="table-wrap table-tall">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["quality.status", quality.status],
                ["quality.freshness_ms", quality.freshness_ms],
                ["quality.max_gap_s", quality.max_gap_s],
                ["quality.coverage_ratio", quality.coverage_ratio],
                ["quality.source_used", quality.source_used],
                ["quality.degraded_reason", quality.degraded_reason],
                ["quality.bars_returned", quality.bars_returned],
                ["quality.bars_requested", quality.bars_requested],
                ["parity.bucket_count_legacy", parity.bucket_count_legacy],
                ["parity.bucket_count_shared", parity.bucket_count_shared],
                ["parity.missing_in_shared", parity.missing_in_shared],
                ["parity.missing_in_legacy", parity.missing_in_legacy],
                ["parity.mismatched_buckets", parity.mismatched_buckets],
                ["parity.max_abs_close_delta", parity.max_abs_close_delta],
              ].map(([label, value]) => (
                <tr key={label}>
                  <td className="mono">{label}</td>
                  <td>
                    <span className={`pill ${gateTone(String(value ?? ""))}`}>{String(value ?? "n/a")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
