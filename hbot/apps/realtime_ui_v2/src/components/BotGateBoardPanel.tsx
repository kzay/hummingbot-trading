import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import { gatePriority, gateTone } from "../utils/presentation";
import { Panel } from "./Panel";

interface QuoteGate {
  key?: string;
  label?: string;
  status?: string;
  detail?: string;
}

export function BotGateBoardPanel() {
  const { quoteGatesInput, quotingStatus, quotingReason, regime, orderCount } = useDashboardStore(
    useShallow((state) => ({
      quoteGatesInput: state.summaryAccount.quote_gates,
      quotingStatus: state.summaryAccount.quoting_status,
      quotingReason: state.summaryAccount.quoting_reason,
      regime: state.summaryAccount.regime,
      orderCount: state.orders.length,
    })),
  );
  const quoteGates = useMemo(() => {
    const gates = (Array.isArray(quoteGatesInput) ? quoteGatesInput : []) as QuoteGate[];
    return gates
      .slice()
      .sort((left, right) => {
        const delta = gatePriority(String(left.status || "")) - gatePriority(String(right.status || ""));
        if (delta !== 0) {
          return delta;
        }
        return String(left.label || left.key || "").localeCompare(String(right.label || right.key || ""));
      });
  }, [quoteGatesInput]);

  const primaryGate = quoteGates.find((gate) => gatePriority(String(gate.status || "")) < 2) || null;

  return (
    <Panel title="Bot Gate Board" subtitle="Gate-by-gate quoting state for the selected bot instance." className="panel-span-8">
      <div className="panel-meta-row">
        <span className="meta-pill">Quote {String(quotingStatus || "n/a")}</span>
        <span className="meta-pill">{String(quotingReason || "No quoting reason")}</span>
        <span className="meta-pill">Orders {orderCount}</span>
        {regime ? (
          <span className={`pill ${gateTone(String(regime || ""))}`}>Regime {String(regime || "").replaceAll("_", " ")}</span>
        ) : null}
        {primaryGate ? <span className="meta-pill">Top gate {String(primaryGate.label || primaryGate.key || "gate")}</span> : null}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Gate</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {quoteGates.length === 0 ? (
              <tr>
                <td colSpan={3}>No gate status available.</td>
              </tr>
            ) : (
              quoteGates.map((gate, index) => (
                <tr
                  key={`${gate.key || gate.label || "gate"}-${index}`}
                  className={`gate-row ${index === 0 && gatePriority(String(gate.status || "")) < 2 ? "primary" : ""}`.trim()}
                >
                  <td>{String(gate.label || gate.key || "gate")}</td>
                  <td>
                    <span className={`pill ${gateTone(String(gate.status || ""))}`}>{String(gate.status || "n/a")}</span>
                  </td>
                  <td className="mono">{String(gate.detail || "")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
