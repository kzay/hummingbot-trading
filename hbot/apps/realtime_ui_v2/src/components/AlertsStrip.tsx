import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { gateTone } from "../utils/presentation";

export function AlertsStrip() {
  const alerts = useDashboardStore(useShallow((state) => state.alerts));

  const activeAlerts = useMemo(
    () =>
      (Array.isArray(alerts) ? alerts : [])
        .filter((entry) => String(entry.title ?? entry.detail ?? "").trim())
        .slice(0, 4),
    [alerts],
  );

  if (activeAlerts.length === 0) {
    return null;
  }

  return (
    <section className="alerts-strip">
      {activeAlerts.map((alert, index) => (
        <article key={`${String(alert.title ?? "alert")}-${index}`} className="alert-card">
          <span className={`pill ${gateTone(String(alert.severity ?? ""))}`}>{String(alert.severity ?? "alert")}</span>
          <div className="alert-copy">
            <strong>{String(alert.title ?? "Alert")}</strong>
            <span>{String(alert.detail ?? "")}</span>
          </div>
        </article>
      ))}
    </section>
  );
}
