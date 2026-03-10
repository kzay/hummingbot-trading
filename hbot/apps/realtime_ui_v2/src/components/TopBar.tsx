import { useMemo, useRef } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatAgeMs } from "../utils/format";
import { gateTone } from "../utils/presentation";
import { InstancesPreviewStrip } from "./InstancesPreviewStrip";

type ActiveView = "realtime" | "history" | "service" | "daily" | "weekly" | "journal";

const VIEW_OPTIONS: Array<{ id: ActiveView; label: string }> = [
  { id: "realtime", label: "Realtime" },
  { id: "history", label: "History" },
  { id: "service", label: "Service" },
  { id: "daily", label: "Daily Review" },
  { id: "weekly", label: "Weekly Review" },
  { id: "journal", label: "Journal" },
];

interface TopBarProps {
  activeView: ActiveView;
  onActiveViewChange: (view: ActiveView) => void;
}

export function TopBar({ activeView, onActiveViewChange }: TopBarProps) {
  const {
    apiBase,
    apiToken,
    connectionStatus,
    healthStatus,
    summaryStreamAgeMs,
    healthStreamAgeMs,
  } = useDashboardStore(
    useShallow((state) => ({
      apiBase: state.settings.apiBase,
      apiToken: state.settings.apiToken,
      connectionStatus: state.connection.status,
      healthStatus: state.health.status,
      summaryStreamAgeMs: state.summarySystem.stream_age_ms,
      healthStreamAgeMs: state.health.streamAgeMs,
    })),
  );
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const apiBaseRef = useRef<HTMLInputElement | null>(null);
  const apiTokenRef = useRef<HTMLInputElement | null>(null);

  const activeViewLabel = useMemo(
    () => VIEW_OPTIONS.find((option) => option.id === activeView)?.label ?? "Pages",
    [activeView],
  );
  const authHint = apiToken
    ? "Bearer token is session-only. Browser websocket auth is disabled, so live state uses HTTP polling."
    : "Websocket live stream active when the API allows unauthenticated browser connections.";

  const apply = () => {
    updateSettings({
      apiBase: (apiBaseRef.current?.value ?? apiBase).trim() || "http://localhost:9910",
      apiToken: (apiTokenRef.current?.value ?? apiToken).trim(),
    });
  };

  return (
    <header className="topbar">
      <div className="brand-row">
        <div className="brand">
          <h1>Kzay Capital</h1>
          <span className="chip">Realtime UI v2</span>
        </div>
        <details className="page-menu">
          <summary>Pages: {activeViewLabel}</summary>
          <div className="page-menu-list">
            {VIEW_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={`page-menu-item ${activeView === option.id ? "active" : ""}`.trim()}
                onClick={() => onActiveViewChange(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </details>
        <div className="status-row">
          <span className={`pill ${gateTone(connectionStatus)}`}>WS {connectionStatus}</span>
          <span className={`pill ${gateTone(healthStatus)}`}>API {healthStatus}</span>
        </div>
      </div>

      <div className="topbar-system-row">
        <span className="meta-pill">System status</span>
        <span className={`pill ${gateTone(connectionStatus)}`}>Websocket {connectionStatus}</span>
        <span className={`pill ${gateTone(healthStatus)}`}>API {healthStatus}</span>
        <span className="meta-pill">Stream age {formatAgeMs(summaryStreamAgeMs ?? healthStreamAgeMs ?? null)}</span>
        <span className="meta-pill">View {activeViewLabel}</span>
      </div>

      <InstancesPreviewStrip embedded />

      <details className="advanced-controls">
        <summary>Connection settings</summary>
        <div className="controls-grid">
          <label>
            API URL
            <input key={apiBase} ref={apiBaseRef} type="text" defaultValue={apiBase} placeholder="http://localhost:9910" />
          </label>
          <label>
            Token
            <input
              key={apiToken || "empty-token"}
              ref={apiTokenRef}
              type="password"
              defaultValue={apiToken}
              placeholder="Optional bearer token"
            />
          </label>
          <div className="button-row">
            <button type="button" onClick={apply}>
              Apply connection
            </button>
          </div>
        </div>
        <p className="settings-note">{authHint}</p>
      </details>
    </header>
  );
}
