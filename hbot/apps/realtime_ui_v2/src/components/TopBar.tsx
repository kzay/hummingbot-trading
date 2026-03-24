import { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { getDefaultApiBase } from "../constants";
import { useDashboardStore } from "../store/useDashboardStore";

type ActiveView = "realtime" | "history" | "service" | "daily" | "weekly" | "journal" | "backtest" | "research";

const VIEW_OPTIONS: Array<{ id: ActiveView; label: string; shortcut: string }> = [
  { id: "realtime", label: "Realtime", shortcut: "1" },
  { id: "history", label: "History", shortcut: "2" },
  { id: "service", label: "Service", shortcut: "3" },
  { id: "daily", label: "Daily Review", shortcut: "4" },
  { id: "weekly", label: "Weekly Review", shortcut: "5" },
  { id: "journal", label: "Journal", shortcut: "6" },
  { id: "backtest", label: "Backtest", shortcut: "7" },
  { id: "research", label: "Research", shortcut: "8" },
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
    fallbackActive,
    tradingPair,
    selectedInstance,
  } = useDashboardStore(
    useShallow((state) => ({
      apiBase: state.settings.apiBase,
      apiToken: state.settings.apiToken,
      connectionStatus: state.connection.status,
      healthStatus: state.health.status,
      fallbackActive: state.summarySystem.fallback_active ?? false,
      tradingPair: state.market.trading_pair ?? "",
      selectedInstance: state.settings.instanceName ?? "",
    })),
  );

  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const apiBaseRef = useRef<HTMLInputElement | null>(null);
  const apiTokenRef = useRef<HTMLInputElement | null>(null);
  const pageMenuRef = useRef<HTMLDetailsElement | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (pageMenuRef.current?.open && !pageMenuRef.current.contains(e.target as Node)) {
        pageMenuRef.current.open = false;
      }
    };
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, []);

  const wsDisconnected = connectionStatus !== "connected" && apiToken.trim() === "";
  const isDegraded = fallbackActive || healthStatus === "degraded" || healthStatus === "error";
  const [utcStr, setUtcStr] = useState(() => new Date().toISOString().slice(11, 19));

  useEffect(() => {
    const tick = () => setUtcStr(new Date().toISOString().slice(11, 19));
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);

  const apply = () => {
    updateSettings({
      apiBase: (apiBaseRef.current?.value ?? apiBase).trim() || getDefaultApiBase(),
      apiToken: (apiTokenRef.current?.value ?? apiToken).trim(),
    });
    setSettingsOpen(false);
  };

  const getStatusColor = () => {
    switch (connectionStatus) {
      case "connected": return "var(--green)";
      case "connecting": 
      case "reconnecting": return "var(--yellow)";
      case "error":
      case "closed": return "var(--red)";
      default: return "var(--muted)";
    }
  };

  const getStatusLabel = () => {
    switch (connectionStatus) {
      case "connected": return "Connected";
      case "connecting": return "Connecting...";
      case "reconnecting": return "Reconnecting...";
      case "error": return "Error";
      case "closed": return "Disconnected";
      default: return "Idle";
    }
  };

  return (
    <>
      {wsDisconnected && (
        <div className="connection-lost-banner">
          Connection lost — reconnecting...
        </div>
      )}
      {isDegraded && !wsDisconnected && (
        <div className="degraded-banner" role="status">
          Degraded mode — {fallbackActive ? "using REST fallback, live stream unavailable" : `API health: ${healthStatus}`}
        </div>
      )}
      <header className="topbar">
        <div className="topbar-left">
          <div className="topbar-left-icon">₿</div>
          <div className="topbar-instance-name">
            {selectedInstance || "No Instance Selected"} 
            {tradingPair && <span className="topbar-instance-pair">- {tradingPair}</span>}
          </div>
        </div>

        <div className="topbar-right">
          <span className="utc-clock">{utcStr} UTC</span>
          <div style={{ position: "relative" }}>
            <button 
              className="connection-button" 
              onClick={() => setSettingsOpen(!settingsOpen)}
            >
              {getStatusLabel()} <span className="connection-status-dot" style={{ backgroundColor: getStatusColor(), boxShadow: `0 0 6px ${getStatusColor()}` }}></span>
            </button>
            
            {settingsOpen && (
              <div className="settings-dropdown" style={{
                position: "absolute", top: "100%", right: 0, marginTop: "8px", width: "320px", 
                background: "var(--bg-panel)", border: "1px solid var(--border-strong)", 
                borderRadius: "8px", padding: "16px", zIndex: 100,
                boxShadow: "0 10px 25px rgba(0,0,0,0.5)"
              }}>
                <div style={{ marginBottom: "12px", fontSize: "13px", fontWeight: 600 }}>Connection Settings</div>
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  <label style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "11px", color: "var(--muted)" }}>
                    API URL
                    <input ref={apiBaseRef} type="text" defaultValue={apiBase} style={{ padding: "6px 8px", background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "4px", color: "var(--text)" }} />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "11px", color: "var(--muted)" }}>
                    Token
                    <input ref={apiTokenRef} type="password" defaultValue={apiToken} placeholder="Optional bearer token" style={{ padding: "6px 8px", background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "4px", color: "var(--text)" }} />
                  </label>
                  <button onClick={apply} style={{ marginTop: "4px", padding: "8px", background: "var(--blue)", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontWeight: 600 }}>
                    Apply Connection
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
        
        {/* Hidden navigation details left in the dom to support view navigation shortcuts and logic */}
        <details className="page-menu" ref={pageMenuRef} style={{ display: 'none' }}>
          <summary aria-label="Open view navigation menu">Navigation</summary>
          <nav className="page-menu-list" aria-label="View navigation">
            {VIEW_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={`page-menu-item ${activeView === option.id ? "active" : ""}`.trim()}
                aria-label={`Switch to ${option.label} view`}
                aria-current={activeView === option.id ? "page" : undefined}
                onClick={() => {
                  onActiveViewChange(option.id);
                  if (pageMenuRef.current) pageMenuRef.current.open = false;
                }}
              >
                {option.label}<kbd>{option.shortcut}</kbd>
              </button>
            ))}
          </nav>
        </details>
      </header>
    </>
  );
}
