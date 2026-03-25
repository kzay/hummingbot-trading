import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";

const REGIME_LABELS: Record<number, string> = {
  0: "Neutral (Low Vol)",
  1: "Neutral (High Vol)",
  2: "Trending Up",
  3: "Trending Down",
};

const DIRECTION_LABELS: Record<number, string> = {
  [-1]: "Bearish",
  0: "Neutral",
  1: "Bullish",
};

const FEATURE_GROUPS: Record<string, string[]> = {
  "Returns & Price": [
    "return_1m", "return_5m", "return_15m", "return_1h",
    "close_in_range_1m", "close_in_range_5m", "close_in_range_15m", "close_in_range_1h",
    "body_ratio_1m", "body_ratio_5m", "body_ratio_15m", "body_ratio_1h",
  ],
  "Volatility": [
    "atr_1m", "atr_5m", "atr_15m", "atr_1h",
    "atr_ratio_5m_1m", "atr_ratio_15m_1m", "atr_ratio_1h_1m",
    "realized_vol_15m", "realized_vol_1h", "realized_vol_4h",
    "parkinson_vol", "garman_klass_vol", "vol_of_vol",
    "atr_pctl_24h", "atr_pctl_7d", "range_expansion",
  ],
  "Momentum": [
    "bb_position_1m", "rsi_1m", "adx_1m",
    "trend_alignment_1m_5m", "trend_alignment_1m_15m", "trend_alignment_1m_1h",
  ],
  "Sentiment": [
    "funding_rate", "funding_momentum", "annualized_funding",
    "ls_ratio", "ls_ratio_momentum",
  ],
  "Temporal": [
    "hour_sin", "hour_cos", "day_sin", "day_cos",
    "session_flag", "minutes_since_funding",
  ],
};

function formatFeatureValue(name: string, value: number): string {
  if (name.startsWith("return_") || name.includes("momentum") || name === "funding_rate") {
    return (value * 100).toFixed(4) + "%";
  }
  if (name.startsWith("atr_pctl") || name.includes("ratio") || name === "range_expansion") {
    return value.toFixed(4);
  }
  if (name.startsWith("rsi_") || name.startsWith("adx_")) {
    return value.toFixed(1);
  }
  if (name.startsWith("atr_") || name.startsWith("realized_vol") || name.includes("vol")) {
    return value.toFixed(6);
  }
  return value.toFixed(4);
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return "var(--green, #2ecc71)";
  if (confidence >= 0.5) return "var(--yellow, #f39c12)";
  return "var(--red, #e74c3c)";
}

function PredictionCard({ modelType, pred, version }: {
  modelType: string;
  pred: Record<string, unknown>;
  version: string;
}) {
  const isClassifier = pred.class !== undefined;
  const confidence = Number(pred.confidence ?? 0);
  const deploymentReady = pred.deployment_ready !== false;
  const missingFeatures = (pred.missing_features as string[] | undefined) ?? [];

  let displayLabel: string;
  let displayValue: string;

  if (isClassifier) {
    const cls = Number(pred.class);
    if (modelType === "regime") {
      displayLabel = REGIME_LABELS[cls] ?? `Class ${cls}`;
    } else if (modelType === "direction") {
      displayLabel = DIRECTION_LABELS[cls] ?? `Class ${cls}`;
    } else {
      displayLabel = `Class ${cls}`;
    }
    displayValue = `${(confidence * 100).toFixed(1)}%`;
  } else {
    displayLabel = Number(pred.value ?? 0).toFixed(4);
    displayValue = "";
  }

  const probabilities = pred.probabilities as Record<string, number> | undefined;

  return (
    <div style={{
      background: "var(--bg-panel, #1a1a2e)",
      borderRadius: 8,
      padding: "12px 16px",
      border: `1px solid ${deploymentReady ? "var(--border, #333)" : "rgba(231, 76, 60, 0.4)"}`,
      opacity: deploymentReady ? 1 : 0.6,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{
          fontWeight: 700, fontSize: "0.85rem",
          textTransform: "capitalize", color: "var(--text, #fff)",
        }}>{modelType}</span>
        {!deploymentReady && (
          <span style={{
            fontSize: "0.65rem", fontWeight: 600,
            color: "var(--red, #e74c3c)",
            background: "rgba(231, 76, 60, 0.15)",
            padding: "2px 6px", borderRadius: 3,
            textTransform: "uppercase",
          }}>GATED</span>
        )}
      </div>

      <div style={{ fontSize: "1.3rem", fontWeight: 700, color: "var(--text, #fff)", marginBottom: 4 }}>
        {displayLabel}
      </div>

      {isClassifier && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <div style={{
            flex: 1, height: 4, background: "rgba(255,255,255,0.1)",
            borderRadius: 2, overflow: "hidden",
          }}>
            <div style={{
              height: "100%", width: `${confidence * 100}%`,
              background: confidenceColor(confidence),
              borderRadius: 2, transition: "width 0.3s ease",
            }} />
          </div>
          <span style={{ fontSize: "0.75rem", fontWeight: 600, color: confidenceColor(confidence) }}>
            {displayValue}
          </span>
        </div>
      )}

      {probabilities && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {Object.entries(probabilities).map(([cls, prob]) => {
            let label: string;
            if (modelType === "regime") label = REGIME_LABELS[Number(cls)] ?? cls;
            else if (modelType === "direction") label = DIRECTION_LABELS[Number(cls)] ?? cls;
            else label = cls;
            return (
              <span key={cls} style={{
                fontSize: "0.65rem", padding: "1px 5px", borderRadius: 3,
                background: Number(cls) === Number(pred.class) ? "rgba(46, 204, 113, 0.2)" : "rgba(255,255,255,0.05)",
                color: Number(cls) === Number(pred.class) ? "var(--green, #2ecc71)" : "var(--muted, #888)",
              }}>
                {label}: {(prob * 100).toFixed(1)}%
              </span>
            );
          })}
        </div>
      )}

      <div style={{
        display: "flex", justifyContent: "space-between", marginTop: 8,
        fontSize: "0.65rem", color: "var(--muted, #666)",
      }}>
        <span>v{version?.split("T")[0] ?? "?"}</span>
        {missingFeatures.length > 0 && (
          <span title={missingFeatures.join(", ")}>{missingFeatures.length} features missing</span>
        )}
      </div>
    </div>
  );
}

export function MlFeaturesPanel() {
  const { mlFeatures } = useDashboardStore(
    useShallow((state) => ({
      mlFeatures: state.mlFeatures,
    })),
  );

  const ml = mlFeatures as Record<string, unknown> | null;
  const hasData =
    ml &&
    typeof ml === "object" &&
    (("features" in ml && ml.features && Object.keys(ml.features as object).length > 0) ||
      ("predictions" in ml && ml.predictions && Object.keys(ml.predictions as object).length > 0));

  const groupedFeatures = useMemo(() => {
    if (!hasData) return null;
    const features = (ml!.features ?? {}) as Record<string, number>;
    const grouped: Record<string, [string, number][]> = {};
    const assigned = new Set<string>();

    for (const [groupName, keys] of Object.entries(FEATURE_GROUPS)) {
      const items: [string, number][] = [];
      for (const k of keys) {
        if (k in features) {
          items.push([k, features[k]]);
          assigned.add(k);
        }
      }
      if (items.length > 0) grouped[groupName] = items;
    }

    const other: [string, number][] = [];
    for (const [k, v] of Object.entries(features)) {
      if (!assigned.has(k)) other.push([k, v]);
    }
    if (other.length > 0) grouped["Other"] = other;

    return grouped;
  }, [hasData, ml]);

  if (!hasData) {
    return (
      <section className="panel panel-span-12">
        <header className="panel-header">
          <h2 className="panel-title">ML Features & Predictions</h2>
        </header>
        <div className="panel-content">
          <p>No ML features data available. Ensure ml-feature-service is running and connected.</p>
        </div>
      </section>
    );
  }

  const {
    exchange = "Unknown",
    trading_pair = "Unknown",
    timestamp_ms,
    predictions = {},
    model_versions = {},
  } = ml as Record<string, unknown>;

  const predEntries = Object.entries(predictions as Record<string, Record<string, unknown>>);
  const versions = model_versions as Record<string, string>;
  const dateStr = timestamp_ms ? new Date(Number(timestamp_ms)).toLocaleString() : "Unknown";

  return (
    <section className="panel panel-span-12">
      <header className="panel-header">
        <h2 className="panel-title">ML Features & Predictions</h2>
        <div className="panel-controls">
          <span className="source-badge">{String(exchange)} / {String(trading_pair)}</span>
          <span className="source-badge">{dateStr}</span>
        </div>
      </header>
      <div className="panel-content">
        {/* Predictions row */}
        {predEntries.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: `repeat(${Math.min(predEntries.length, 3)}, 1fr)`,
            gap: 12, marginBottom: 16,
          }}>
            {predEntries.map(([modelType, pred]) => (
              <PredictionCard
                key={modelType}
                modelType={modelType}
                pred={pred}
                version={versions[modelType] ?? "unknown"}
              />
            ))}
          </div>
        )}

        {/* Grouped features */}
        {groupedFeatures && (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 12,
          }}>
            {Object.entries(groupedFeatures).map(([groupName, items]) => (
              <div key={groupName} className="panel" style={{ margin: 0 }}>
                <header className="panel-header" style={{ padding: "6px 12px" }}>
                  <h3 className="panel-title" style={{ fontSize: "0.75rem" }}>{groupName}</h3>
                </header>
                <div className="panel-content" style={{ padding: 0, maxHeight: 240, overflowY: "auto" }}>
                  <table className="data-table" style={{ fontSize: "0.72rem" }}>
                    <tbody>
                      {items.map(([name, value]) => (
                        <tr key={name}>
                          <td className="align-left" style={{ padding: "3px 8px", fontFamily: "var(--font-mono, monospace)" }}>{name}</td>
                          <td className="align-right" style={{ padding: "3px 8px" }}>{formatFeatureValue(name, value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
