import { useCallback, useMemo, useState } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { gateTone } from "../utils/presentation";

function alertKey(alert: { title?: unknown; severity?: unknown; detail?: unknown }): string {
  return `${String(alert.title ?? "")}\x00${String(alert.severity ?? "")}\x00${String(alert.detail ?? "")}`;
}

export function AlertsStrip() {
  const alerts = useDashboardStore((state) => state.alerts);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const activeAlerts = useMemo(
    () =>
      (Array.isArray(alerts) ? alerts : [])
        .filter((entry) => String(entry.title ?? entry.detail ?? "").trim())
        .slice(0, 6),
    [alerts],
  );

  const visibleAlerts = useMemo(
    () => activeAlerts.filter((alert) => !dismissed.has(alertKey(alert))),
    [activeAlerts, dismissed],
  );

  const dismiss = useCallback((key: string) => {
    setDismissed((prev) => new Set(prev).add(key));
  }, []);

  if (visibleAlerts.length === 0) {
    return null;
  }

  return (
    <section className="alerts-strip" role="alert" aria-live="polite" aria-atomic="true">
      {visibleAlerts.map((alert) => {
        const key = alertKey(alert);
        const severity = String(alert.severity ?? "").toLowerCase();
        const severityClass = severity === "fail" || severity === "error" || severity === "critical"
          ? "severity-fail"
          : severity === "warn" || severity === "warning"
            ? "severity-warn"
            : "";
        return (
          <article key={key} className={`alert-card ${severityClass}`.trim()}>
            <span className={`pill ${gateTone(String(alert.severity ?? ""))}`}>{String(alert.severity ?? "alert")}</span>
            <div className="alert-copy">
              <strong>{String(alert.title ?? "Alert")}</strong>
              <span>{String(alert.detail ?? "")}</span>
            </div>
            <button
              type="button"
              className="alert-dismiss"
              onClick={() => dismiss(key)}
              title="Dismiss"
              aria-label="Dismiss alert"
            >
              ×
            </button>
          </article>
        );
      })}
    </section>
  );
}
