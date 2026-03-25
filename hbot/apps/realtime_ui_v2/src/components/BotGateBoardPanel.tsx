import { memo, useCallback, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type { BotGateGroup } from "../types/realtime";
import { gatePriority, gateTone } from "../utils/presentation";
import { Panel } from "./Panel";

interface QuoteGate {
  key?: string;
  label?: string;
  status?: string;
  detail?: string;
}

function BotGateSection({ group }: { group: BotGateGroup }) {
  const [expanded, setExpanded] = useState(false);
  const toggle = useCallback(() => setExpanded((prev) => !prev), []);

  const gates = useMemo(() => {
    return (group.gates ?? []).slice().sort((a, b) => {
      const delta = gatePriority(String(a.status || "")) - gatePriority(String(b.status || ""));
      if (delta !== 0) return delta;
      return String(a.label || a.key || "").localeCompare(String(b.label || b.key || ""));
    });
  }, [group.gates]);

  const failCount = gates.filter((g) => gatePriority(String(g.status || "")) === 0).length;
  const gateStateEntry = gates.find((g) => g.key === "gate_state");
  const headlineStatus = gateStateEntry?.status ?? (failCount > 0 ? "fail" : "pass");

  return (
    <div className="bot-gate-section">
      <button type="button" className="bot-gate-header" onClick={toggle} aria-expanded={expanded}>
        <span className="bot-gate-title">
          <span className="bot-gate-id">{group.bot_id}</span>
          <span className={`pill ${group.strategy_type === "mm" ? "ok" : "neutral"}`} style={{ fontSize: 9, marginLeft: 4 }}>
            {group.strategy_type}
          </span>
        </span>
        <span className={`pill ${gateTone(headlineStatus)}`} style={{ fontSize: 9, marginLeft: "auto", marginRight: 4 }}>
          {gateStateEntry ? String(gateStateEntry.detail || gateStateEntry.status || "") : "n/a"}
        </span>
        <span className="bot-gate-chevron" aria-hidden="true">{expanded ? "\u25B4" : "\u25BE"}</span>
      </button>
      {expanded && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Gate</th>
                <th scope="col">Status</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {gates.map((gate, i) => (
                <tr key={`${gate.key || "g"}-${i}`} className="gate-row">
                  <td>{String(gate.label || gate.key || "gate")}</td>
                  <td>
                    <span className={`pill ${gateTone(String(gate.status || ""))}`}>{String(gate.status || "n/a")}</span>
                  </td>
                  <td
                    className="mono"
                    title={String(gate.detail || "")}
                    style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  >
                    {String(gate.detail || "")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export const BotGateBoardPanel = memo(function BotGateBoardPanel() {
  const { quoteGatesInput, quotingStatus, regime, botGatesInput, hasConnected } = useDashboardStore(
    useShallow((state) => ({
      quoteGatesInput: state.summaryAccount.quote_gates,
      quotingStatus: state.summaryAccount.quoting_status,
      regime: state.summaryAccount.regime,
      botGatesInput: state.summaryAccount.bot_gates,
      hasConnected: state.connection.connectedAtMs > 0,
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

  const botGates = useMemo(() => {
    return (Array.isArray(botGatesInput) ? botGatesInput : []) as BotGateGroup[];
  }, [botGatesInput]);

  const failCount = quoteGates.filter((g) => gatePriority(String(g.status || "")) === 0).length;
  const warnCount = quoteGates.filter((g) => gatePriority(String(g.status || "")) === 1).length;
  const allClear = quoteGates.length > 0 && failCount === 0 && warnCount === 0;

  return (
    <Panel
      title={
        <>
          Gates
          {quoteGates.length > 0 && (
            <span className={`pill ${allClear ? "ok" : failCount > 0 ? "fail" : "warn"}`} style={{ marginLeft: 8, fontSize: 10 }}>
              {allClear ? "ALL PASS" : `${failCount + warnCount} blocked`}
            </span>
          )}
        </>
      }
      className="panel-span-4"
    >
      <div className="panel-meta-row">
        {regime ? (
          <span className={`pill ${gateTone(String(regime || ""))}`}>{String(regime || "").replaceAll("_", " ")}</span>
        ) : null}
        <span className="meta-pill">{String(quotingStatus || "n/a")}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Gate</th>
              <th scope="col">Status</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {quoteGates.length === 0 ? (
              <tr>
                <td colSpan={3}>{hasConnected ? "No gate status available." : "Loading\u2026"}</td>
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
                  <td className="mono" title={String(gate.detail || "")} style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {String(gate.detail || "")}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {botGates.length > 0 && (
        <div className="bot-gates-container" style={{ marginTop: 8 }}>
          {botGates.map((group) => (
            <BotGateSection key={group.bot_id} group={group} />
          ))}
        </div>
      )}
    </Panel>
  );
});
