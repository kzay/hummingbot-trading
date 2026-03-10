import { useMemo } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { formatRelativeTs } from "../utils/format";
import { Panel } from "./Panel";

export function PayloadInspectorPanel() {
  const payloads = useDashboardStore((state) => state.payloads);
  const selectedPayloadId = useDashboardStore((state) => state.selectedPayloadId);
  const setSelectedPayloadId = useDashboardStore((state) => state.setSelectedPayloadId);

  const selectedPayload = useMemo(() => {
    if (!selectedPayloadId) {
      return null;
    }
    return payloads.find((payload) => payload.id === selectedPayloadId) ?? null;
  }, [payloads, selectedPayloadId]);
  const selectedPayloadJson = useMemo(
    () => (selectedPayload ? JSON.stringify(selectedPayload.payload, null, 2) : "Select a payload to inspect JSON."),
    [selectedPayload],
  );

  return (
    <Panel
      title="Payload Inspector"
      subtitle="Recent inbound websocket payloads for data-contract debugging."
      className="panel-span-12 payload-panel"
    >
      <div className="payload-list">
        {payloads.length === 0 ? (
          <div className="empty-state">No payloads received yet.</div>
        ) : (
          payloads
            .slice()
            .reverse()
            .map((payload) => (
              <button
                type="button"
                key={payload.id}
                className={`payload-item ${selectedPayload?.id === payload.id ? "active" : ""}`}
                onClick={() => setSelectedPayloadId(payload.id)}
              >
                <span className="payload-type">{payload.messageType}</span>
                <span className="payload-meta">{payload.eventType}</span>
                <span className="payload-meta">{formatRelativeTs(payload.receivedAtMs)}</span>
              </button>
            ))
        )}
      </div>
      <pre className="payload-json">{selectedPayloadJson}</pre>
    </Panel>
  );
}
