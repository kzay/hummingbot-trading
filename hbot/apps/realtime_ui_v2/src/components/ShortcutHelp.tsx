import { useEffect, useRef } from "react";

interface ShortcutHelpProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS: Array<{ key: string; desc: string }> = [
  { key: "1–9", desc: "Switch view (Realtime, History, Service, Daily, Weekly, Journal, Backtest, Research, ML)" },
  { key: "T", desc: "Cycle candle timeframe" },
  { key: "[ / ]", desc: "Previous / next instance" },
  { key: "/", desc: "Focus search / filter input" },
  { key: "Space", desc: "Pause / resume event feed" },
  { key: "Esc", desc: "Close menus & modals" },
  { key: "?", desc: "Toggle this help overlay" },
];

export function ShortcutHelp({ open, onClose }: ShortcutHelpProps) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const modal = modalRef.current;
    if (modal) modal.focus();

    function trapFocus(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const focusable = modal?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", trapFocus);
    return () => document.removeEventListener("keydown", trapFocus);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="shortcut-overlay" onClick={onClose}>
      <div
        ref={modalRef}
        className="shortcut-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard Shortcuts"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="shortcut-modal-header">
          <h2>Keyboard Shortcuts</h2>
          <button type="button" className="alert-dismiss" onClick={onClose} aria-label="Close shortcuts">×</button>
        </div>
        <table>
          <tbody>
            {SHORTCUTS.map((s) => (
              <tr key={s.key}>
                <td style={{ textAlign: "left", paddingRight: 16 }}>
                  <kbd style={{ fontSize: 12, padding: "2px 8px" }}>{s.key}</kbd>
                </td>
                <td style={{ textAlign: "left", color: "var(--muted-strong)" }}>{s.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
