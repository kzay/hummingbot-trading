import { useDashboardStore } from "../store/useDashboardStore";
import type { ConnectionStatus } from "../types/realtime";

const STATUS_CONFIG: Record<ConnectionStatus, { dotClass: string; label: string }> = {
  connected: { dotClass: "green", label: "Connected" },
  connecting: { dotClass: "yellow", label: "Connecting\u2026" },
  reconnecting: { dotClass: "yellow", label: "Reconnecting\u2026" },
  error: { dotClass: "red", label: "Error" },
  closed: { dotClass: "red", label: "Disconnected" },
  idle: { dotClass: "gray", label: "Idle" },
};

export function ConnectionBadge() {
  const status = useDashboardStore((state) => state.connection.status);
  const { dotClass, label } = STATUS_CONFIG[status] ?? STATUS_CONFIG.idle;

  return (
    <span className="connection-badge" aria-live="polite" role="status">
      <span className={`dot ${dotClass}`} />
      {label}
    </span>
  );
}
