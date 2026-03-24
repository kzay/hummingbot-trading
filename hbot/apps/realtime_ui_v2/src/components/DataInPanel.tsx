import { memo, useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore, getRuntimeEvents, getRuntimeEventsVersion } from "../store/useDashboardStore";
import { formatAgeMs, formatRelativeTs } from "../utils/format";
import { Panel } from "./Panel";

const NOW_REFRESH_MS = 3_000;

function countRecentEvents(events: { eventType: string; tsMs: number }[], windowMs: number, nowMs: number) {
  const cutoff = nowMs - windowMs;
  let quoteCount = 0;
  let depthCount = 0;
  let fillsCount = 0;
  let paperEvents = 0;
  let snapshots = 0;
  for (const entry of events) {
    if (entry.tsMs < cutoff) {
      continue;
    }
    if (entry.eventType === "market_quote") {
      quoteCount += 1;
      continue;
    }
    if (entry.eventType === "market_depth_snapshot") {
      depthCount += 1;
      continue;
    }
    if (entry.eventType === "bot_fill") {
      fillsCount += 1;
      continue;
    }
    if (entry.eventType === "paper_exchange_event") {
      paperEvents += 1;
      continue;
    }
    if (entry.eventType === "snapshot") {
      snapshots += 1;
    }
  }
  return {
    quoteCount,
    depthCount,
    fillsCount,
    paperEvents,
    all: quoteCount + depthCount + fillsCount + paperEvents + snapshots,
  };
}

function buildSparkline(events: { tsMs: number }[], nowMs: number): number[] {
  const bucketMs = 30_000;
  const bucketCount = 10;
  const output = Array.from({ length: bucketCount }, () => 0);
  const cutoff = nowMs - bucketMs * bucketCount;
  for (const entry of events) {
    if (entry.tsMs < cutoff) {
      continue;
    }
    const bucketIndex = Math.min(bucketCount - 1, Math.max(0, Math.floor((entry.tsMs - cutoff) / bucketMs)));
    output[bucketIndex] += 1;
  }
  return output;
}

export const DataInPanel = memo(function DataInPanel() {
  const {
    connectionStatus,
    wsSessionId,
    reconnectCount,
    parseErrorCount,
    droppedMessageCount,
    staleRestRejectCount,
    lastMessageTsMs,
    lastEventType,
    healthStatus,
    redisAvailable,
    dbAvailable,
    healthStreamAgeMs,
    fallbackActive,
    summaryStreamAgeMs,
    source,
    mode,
  } = useDashboardStore(
    useShallow((state) => ({
      connectionStatus: state.connection.status,
      wsSessionId: state.connection.wsSessionId,
      reconnectCount: state.connection.reconnectCount,
      parseErrorCount: state.connection.parseErrorCount,
      droppedMessageCount: state.connection.droppedMessageCount,
      staleRestRejectCount: state.freshness.staleRestRejectCount,
      lastMessageTsMs: state.connection.lastMessageTsMs,
      lastEventType: state.connection.lastEventType,
      healthStatus: state.health.status,
      redisAvailable: state.health.redisAvailable,
      dbAvailable: state.health.dbAvailable,
      healthStreamAgeMs: state.health.streamAgeMs,
      fallbackActive: state.health.fallbackActive,
      summaryStreamAgeMs: state.summarySystem.stream_age_ms,
      source: state.source,
      mode: state.mode,
    })),
  );
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [eventsVersion, setEventsVersion] = useState(() => getRuntimeEventsVersion());

  useEffect(() => {
    const tick = () => {
      if (!document.hidden) {
        setNowMs(Date.now());
        setEventsVersion(getRuntimeEventsVersion());
      }
    };
    const timerId = window.setInterval(tick, NOW_REFRESH_MS);
    return () => {
      window.clearInterval(timerId);
    };
  }, []);

  const runtimeEvents = getRuntimeEvents();
  const metrics = useMemo(() => {
    const windowMs = 60 * 1_000;
    return countRecentEvents(runtimeEvents, windowMs, nowMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventsVersion, nowMs]);
  const sparkline = useMemo(() => buildSparkline(runtimeEvents, nowMs), [eventsVersion, nowMs]); // eslint-disable-line react-hooks/exhaustive-deps
  const sparklineMax = Math.max(1, ...sparkline);
  const sparklinePoints = sparkline
    .map((value, index) => {
      const x = (index / Math.max(1, sparkline.length - 1)) * 100;
      const y = 28 - (value / sparklineMax) * 24;
      return `${x},${y}`;
    })
    .join(" ");

  const lastMessageAgeMs = lastMessageTsMs > 0 ? nowMs - lastMessageTsMs : null;
  const recentRuntimeEvents = runtimeEvents.slice(-20);
  const averageGapMs =
    recentRuntimeEvents.length > 1
      ? recentRuntimeEvents
          .slice(1)
          .reduce((accumulator, entry, index) => accumulator + Math.max(0, entry.tsMs - recentRuntimeEvents[index].tsMs), 0) /
        (recentRuntimeEvents.length - 1)
      : null;

  return (
    <Panel title="Data In" className="panel-span-6">
      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        <article className="metric-card">
          <h3>Flow</h3>
          <div className="metric-value">
            {metrics.all} <span style={{ fontSize: 11, color: "var(--muted)" }}>tracked evt/min</span>
          </div>
          <svg className="sparkline" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
            <polyline points={sparklinePoints} />
          </svg>
          <dl>
            <dt>Quotes</dt>
            <dd>{metrics.quoteCount}</dd>
            <dt>Depth</dt>
            <dd>{metrics.depthCount}</dd>
            <dt>Fills</dt>
            <dd>{metrics.fillsCount}</dd>
            <dt>Paper events</dt>
            <dd>{metrics.paperEvents}</dd>
          </dl>
        </article>

        <article className="metric-card">
          <h3>Transport</h3>
          <div className="metric-value">
            <span className={`pill ${connectionStatus === "connected" ? "ok" : connectionStatus === "connecting" ? "warn" : "fail"}`}>
              {connectionStatus}
            </span>
          </div>
          <dl>
            <dt>Session</dt>
            <dd>#{wsSessionId}</dd>
            <dt>Reconnects</dt>
            <dd>{reconnectCount}</dd>
            <dt>Parse errors</dt>
            <dd>{parseErrorCount}</dd>
            <dt>Dropped</dt>
            <dd>{droppedMessageCount}</dd>
            <dt>Stale REST ignored</dt>
            <dd>{staleRestRejectCount}</dd>
            <dt>Cadence</dt>
            <dd>{formatAgeMs(averageGapMs)}</dd>
          </dl>
        </article>

        <article className="metric-card">
          <h3>Freshness</h3>
          <div className={`metric-value ${lastMessageAgeMs !== null && lastMessageAgeMs > 10000 ? "value-negative" : lastMessageAgeMs !== null && lastMessageAgeMs > 5000 ? "value-warn" : ""}`}>
            {formatAgeMs(lastMessageAgeMs)}
          </div>
          <dl>
            <dt>Last message</dt>
            <dd>{formatRelativeTs(lastMessageTsMs)}</dd>
            <dt>Last event</dt>
            <dd>{lastEventType || "n/a"}</dd>
            <dt>Stream age</dt>
            <dd>{formatAgeMs(healthStreamAgeMs ?? summaryStreamAgeMs ?? null)}</dd>
            <dt>Fallback</dt>
            <dd>{fallbackActive ? "active" : "off"}</dd>
          </dl>
        </article>

        <article className="metric-card">
          <h3>Context</h3>
          <div className="metric-value">{mode || "n/a"}</div>
          <dl>
            <dt>Source</dt>
            <dd>{source || "n/a"}</dd>
            <dt>API status</dt>
            <dd>{healthStatus}</dd>
            <dt>Redis</dt>
            <dd>{redisAvailable ? "up" : "down"}</dd>
            <dt>DB</dt>
            <dd>{dbAvailable ? "up" : "down"}</dd>
          </dl>
        </article>
      </div>
    </Panel>
  );
});
