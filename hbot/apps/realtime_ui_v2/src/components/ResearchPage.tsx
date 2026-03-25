import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Panel } from "./Panel";
import { useResearchData } from "../hooks/useResearchData";
import type {
  CandidateDetail,
  ExplorationSession,
  IterationEvent,
  ResearchCandidate,
} from "../types/research";
import type { LaunchExplorationRequest } from "../types/research";
import {
  cancelExploration,
  explorationLogUrl,
  fetchReport,
  launchExploration,
} from "../utils/researchApi";

function fmtScore(v: number | null | undefined, decimals = 1): string {
  if (v == null || !isFinite(v)) return "\u2014";
  return v.toFixed(decimals);
}

function recColor(rec: string | null | undefined): string {
  switch (rec) {
    case "pass": return "var(--clr-up, #26a69a)";
    case "revise": return "var(--clr-warn, #ffa726)";
    case "reject": return "var(--clr-dn, #ef5350)";
    default: return "var(--clr-muted, #777)";
  }
}

function lifecycleColor(state: string): string {
  switch (state) {
    case "promoted":
    case "paper": return "var(--clr-up, #26a69a)";
    case "revise":
    case "candidate": return "var(--clr-warn, #ffa726)";
    case "rejected": return "var(--clr-dn, #ef5350)";
    default: return "var(--clr-muted, #777)";
  }
}

function ScoreBar({ score, max = 100 }: { score: number | null; max?: number }) {
  const pct = score != null ? Math.min(100, Math.max(0, (score / max) * 100)) : 0;
  const barColor =
    pct >= 70 ? "var(--clr-up, #26a69a)" :
    pct >= 40 ? "var(--clr-warn, #ffa726)" :
    "var(--clr-dn, #ef5350)";

  return (
    <div className="rs-score-bar-wrap">
      <div className="rs-score-bar">
        <div className="rs-score-fill" style={{ width: `${pct}%`, background: barColor }} />
      </div>
      <span className="rs-score-val">{fmtScore(score)}</span>
    </div>
  );
}

function CandidateTable({ candidates, onSelect }: {
  candidates: ResearchCandidate[];
  onSelect: (name: string) => void;
}) {
  if (!candidates.length) {
    return <div className="panel-empty">No candidates found</div>;
  }

  return (
    <div className="rs-table-scroll">
      <table className="rs-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Hypothesis</th>
            <th>Adapter</th>
            <th>Lifecycle</th>
            <th>Score</th>
            <th>Rec.</th>
            <th>Runs</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.name} onClick={() => onSelect(c.name)} style={{ cursor: "pointer" }}>
              <td className="rs-name-cell">{c.name}</td>
              <td className="rs-hyp-cell" title={c.hypothesis}>
                {c.hypothesis.length > 60 ? `${c.hypothesis.slice(0, 57)}...` : c.hypothesis}
              </td>
              <td>{c.adapter_mode}</td>
              <td>
                <span className="rs-badge" style={{ background: lifecycleColor(c.lifecycle) }}>
                  {c.lifecycle}
                </span>
              </td>
              <td><ScoreBar score={c.best_score} /></td>
              <td>
                <span className="rs-badge" style={{ background: recColor(c.best_recommendation) }}>
                  {c.best_recommendation ?? "\u2014"}
                </span>
              </td>
              <td style={{ textAlign: "center" }}>{c.experiment_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidateDetailView({ detail, onBack, apiBase, token }: {
  detail: CandidateDetail;
  onBack: () => void;
  apiBase: string;
  token: string;
}) {
  const [reportMd, setReportMd] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const loadReport = useCallback(async (candidateName: string, runId: string) => {
    setReportLoading(true);
    try {
      const md = await fetchReport(apiBase, token, candidateName, runId);
      setReportMd(md);
    } catch {
      setReportMd("Failed to load report.");
    } finally {
      setReportLoading(false);
    }
  }, [apiBase, token]);

  return (
    <div className="rs-detail">
      <div className="rs-detail-header">
        <button className="rs-back-btn" onClick={onBack}>&larr; Back</button>
        <h3>{detail.name}</h3>
        <span className="rs-badge" style={{ background: lifecycleColor(detail.lifecycle.current_state) }}>
          {detail.lifecycle.current_state}
        </span>
      </div>

      <div className="rs-detail-grid">
        <div className="rs-detail-section">
          <div className="rs-section-title">Hypothesis</div>
          <p className="rs-hypothesis-text">{detail.hypothesis}</p>

          <div className="rs-section-title">Logic</div>
          <div className="rs-logic-block">
            <div><strong>Entry:</strong> {detail.entry_logic || "\u2014"}</div>
            <div><strong>Exit:</strong> {detail.exit_logic || "\u2014"}</div>
          </div>

          <div className="rs-section-title">Best Score</div>
          <ScoreBar score={detail.best_score} />
          {detail.best_recommendation && (
            <span className="rs-badge" style={{ background: recColor(detail.best_recommendation), marginTop: 6, display: "inline-block" }}>
              {detail.best_recommendation}
            </span>
          )}
        </div>

        <div className="rs-detail-section">
          <div className="rs-section-title">Experiments ({detail.experiments.length})</div>
          {detail.experiments.length > 0 ? (
            <div className="rs-table-scroll" style={{ maxHeight: 180 }}>
              <table className="rs-table rs-table-compact">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Score</th>
                    <th>Rec.</th>
                    <th>Report</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.experiments.map((exp, i) => (
                    <tr key={exp.run_id || i}>
                      <td className="rs-name-cell" title={exp.run_id}>{exp.run_id?.slice(0, 8) || `#${i + 1}`}</td>
                      <td>{fmtScore(exp.robustness_score)}</td>
                      <td>
                        <span className="rs-badge" style={{ background: recColor(exp.recommendation) }}>
                          {exp.recommendation ?? "\u2014"}
                        </span>
                      </td>
                      <td>
                        <button
                          className="rs-link-btn"
                          onClick={() => loadReport(detail.name, exp.run_id?.slice(0, 8) || "")}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel-empty">No experiments yet</div>
          )}

          {detail.lifecycle.history.length > 0 && (
            <>
              <div className="rs-section-title" style={{ marginTop: 12 }}>Lifecycle History</div>
              <div className="rs-lifecycle-list">
                {detail.lifecycle.history.map((t, i) => (
                  <div key={i} className="rs-lifecycle-entry">
                    <span className="rs-badge" style={{ background: lifecycleColor(t.from_state) }}>{t.from_state}</span>
                    <span className="rs-arrow">&rarr;</span>
                    <span className="rs-badge" style={{ background: lifecycleColor(t.to_state) }}>{t.to_state}</span>
                    <span className="rs-lifecycle-reason">{t.reason}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {reportLoading && <div className="panel-loading">Loading report...</div>}
      {reportMd && !reportLoading && (
        <div className="rs-report">
          <div className="rs-section-title">Evaluation Report</div>
          <pre className="rs-report-content">{reportMd}</pre>
        </div>
      )}
    </div>
  );
}

function explorationStatusColor(status: string): string {
  switch (status) {
    case "completed": return "var(--clr-up, #26a69a)";
    case "running": return "var(--clr-warn, #ffa726)";
    case "failed":
    case "timed_out": return "var(--clr-dn, #ef5350)";
    case "cancelled": return "var(--clr-muted, #777)";
    default: return "var(--clr-muted, #777)";
  }
}

function ExplorationTable({ sessions, onSelect, onRerun }: {
  sessions: ExplorationSession[];
  onSelect: (id: string) => void;
  onRerun: (params: Partial<LaunchExplorationRequest>) => void;
}) {
  if (!sessions.length) return <div className="panel-empty">No exploration sessions</div>;

  return (
    <div className="rs-table-scroll">
      <table className="rs-table">
        <thead>
          <tr>
            <th>Session</th>
            <th>Status</th>
            <th>Iterations</th>
            <th>Best Score</th>
            <th>Best Candidate</th>
            <th>Date</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.session_id} onClick={() => onSelect(s.session_id)} style={{ cursor: "pointer" }}>
              <td className="rs-name-cell">{s.session_id.slice(0, 12)}</td>
              <td>
                <span className="rs-badge" style={{ background: explorationStatusColor(s.status) }}>
                  {s.status}
                </span>
              </td>
              <td style={{ textAlign: "center" }}>{s.iteration_count}</td>
              <td>{fmtScore(s.best_score)}</td>
              <td>{s.best_candidate || "\u2014"}</td>
              <td>{s.created_at?.slice(0, 16).replace("T", " ") || "\u2014"}</td>
              <td onClick={(e) => e.stopPropagation()} style={{ whiteSpace: "nowrap" }}>
                {s.status !== "running" && (
                  <button
                    className="rs-rerun-btn"
                    title="Re-run with same parameters"
                    onClick={() => onRerun(s.launch_params ?? {})}
                  >
                    ↺ Re-run
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IterationCard({ ev }: { ev: IterationEvent }) {
  const [expanded, setExpanded] = useState(false);
  const fullText = ev.hypothesis_full || ev.hypothesis || "";
  const hasExtra = !!(ev.entry_logic || ev.exit_logic || (ev.parameter_space && Object.keys(ev.parameter_space).length > 0));
  const canExpand = hasExtra || fullText.length > 120;
  const blueprintColor = "var(--clr-accent, #89b4fa)";

  return (
    <div className={`rs-iter-card${ev.is_blueprint ? " rs-iter-card-blueprint" : ""}`}>
      {/* Header row */}
      <div className="rs-iter-card-header">
        <span className="rs-iter-num">#{ev.iteration}</span>
        <span className="rs-iter-name">{ev.candidate_name}</span>
        {ev.adapter_mode && (
          <span className="rs-badge rs-iter-adapter-badge">{ev.adapter_mode}</span>
        )}
        {ev.is_blueprint && (
          <span className="rs-badge" style={{ background: blueprintColor, color: "#1e1e2e", fontWeight: 700 }}>
            BLUEPRINT
          </span>
        )}
        {ev.recommendation && !ev.is_blueprint && (
          <span className="rs-badge" style={{ background: recColor(ev.recommendation) }}>
            {ev.recommendation}
          </span>
        )}
        <div className="rs-iter-score-area">
          <ScoreBar score={ev.is_blueprint ? null : ev.score} />
        </div>
      </div>

      {/* Hypothesis */}
      {fullText && (
        <div className={`rs-iter-hypothesis${expanded ? " rs-iter-hypothesis-expanded" : ""}`}>
          {fullText}
        </div>
      )}

      {/* Expand toggle */}
      {canExpand && (
        <button className="rs-iter-expand-btn" onClick={() => setExpanded((p) => !p)}>
          {expanded ? "\u25b2 Collapse" : "\u25bc Entry/Exit logic \u00b7 Parameter space"}
        </button>
      )}

      {/* Expanded detail */}
      {expanded && (
        <div className="rs-iter-detail">
          {ev.entry_logic && (
            <div className="rs-iter-logic">
              <span className="rs-iter-logic-label">Entry</span>
              {ev.entry_logic}
            </div>
          )}
          {ev.exit_logic && (
            <div className="rs-iter-logic">
              <span className="rs-iter-logic-label">Exit</span>
              {ev.exit_logic}
            </div>
          )}
          {ev.parameter_space && Object.keys(ev.parameter_space).length > 0 && (
            <div className="rs-iter-params-block">
              <div className="rs-iter-params-title">Parameter Space</div>
              <div className="rs-iter-params">
                {Object.entries(ev.parameter_space).map(([k, v]) => (
                  <span key={k} className="rs-param-chip">
                    <span className="rs-param-key">{k}</span>
                    <span className="rs-param-vals">{Array.isArray(v) ? `[${v.join(", ")}]` : String(v)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ExplorationLogPanel({ apiBase, token, sessionId }: {
  apiBase: string;
  token: string;
  sessionId: string;
}) {
  const [events, setEvents] = useState<IterationEvent[]>([]);
  const [done, setDone] = useState(false);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const url = explorationLogUrl(apiBase, sessionId, token);
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("iteration", (e) => {
      try {
        const iter = JSON.parse(e.data) as IterationEvent;
        setEvents((prev) => [...prev, iter]);
      } catch { /* skip */ }
    });
    es.addEventListener("done", (e) => {
      try {
        setSummary(JSON.parse(e.data));
      } catch { /* skip */ }
      setDone(true);
      es.close();
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return;
      es.close();
      setDone(true);
    };
    return () => es.close();
  }, [apiBase, token, sessionId]);

  const handleCancel = useCallback(async () => {
    setCancelling(true);
    try {
      await cancelExploration(apiBase, token, sessionId);
      setDone(true);
    } catch { /* ignore */ }
    setCancelling(false);
  }, [apiBase, token, sessionId]);

  const bestRec = summary?.best_recommendation as string | null | undefined;

  return (
    <div className="rs-exploration-log">
      {/* Toolbar */}
      <div className="rs-iter-toolbar">
        <span className="rs-section-title" style={{ margin: 0 }}>
          {done ? `Results \u2014 ${events.length} iteration${events.length !== 1 ? "s" : ""}` : "Live Iterations\u2026"}
        </span>
        {!done && (
          <button className="bt-btn" onClick={handleCancel} disabled={cancelling} style={{ fontSize: "0.75rem" }}>
            {cancelling ? "Cancelling\u2026" : "Cancel"}
          </button>
        )}
      </div>

      {/* Session summary card (shown once done) */}
      {done && summary && (
        <div className="rs-session-summary">
          <div className="rs-summary-item">
            <span className="rs-summary-label">Best Candidate</span>
            <span className="rs-summary-value rs-name-cell">
              {String(summary.best_observed_candidate || "\u2014")}
            </span>
          </div>
          <div className="rs-summary-item">
            <span className="rs-summary-label">Best Score</span>
            <span className="rs-summary-value">
              {fmtScore(summary.best_observed_score as number | null)}
            </span>
          </div>
          {bestRec && (
            <div className="rs-summary-item">
              <span className="rs-summary-label">Recommendation</span>
              <span className="rs-badge" style={{ background: recColor(bestRec), display: "inline-block", marginTop: 2 }}>
                {bestRec}
              </span>
            </div>
          )}
          <div className="rs-summary-item">
            <span className="rs-summary-label">Iterations</span>
            <span className="rs-summary-value">{String(summary.iterations ?? "\u2014")}</span>
          </div>
          {(summary.total_tokens_used as number) > 0 && (
            <div className="rs-summary-item">
              <span className="rs-summary-label">Tokens Used</span>
              <span className="rs-summary-value">
                {Number(summary.total_tokens_used).toLocaleString()}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Waiting state */}
      {!done && events.length === 0 && (
        <div className="panel-loading">Waiting for iteration events\u2026</div>
      )}

      {/* Iteration cards */}
      {events.length > 0 && (
        <div className="rs-iter-list">
          {events.map((ev) => (
            <IterationCard key={`${ev.iteration}-${ev.candidate_name}`} ev={ev} />
          ))}
        </div>
      )}
    </div>
  );
}

const ALL_ADAPTERS = [
  "atr_mm", "atr_mm_v2", "smc_mm", "combo_mm",
  "pullback", "pullback_v2", "momentum_scalper",
  "directional_mm", "simple",
] as const;

const DEFAULT_LAUNCH_CONFIG: LaunchExplorationRequest = {
  provider: "anthropic",
  iterations: 5,
  temperature: 0.7,
  adapters: [...ALL_ADAPTERS],
  skip_sweep: false,
  skip_walkforward: false,
  extra_context: "",
};

function LaunchExplorationModal({ onClose, onLaunched, apiBase, token, initialConfig }: {
  onClose: () => void;
  onLaunched: (sessionId: string) => void;
  apiBase: string;
  token: string;
  initialConfig?: Partial<LaunchExplorationRequest>;
}) {
  const [config, setConfig] = useState<LaunchExplorationRequest>({ ...DEFAULT_LAUNCH_CONFIG, ...initialConfig });
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLaunch = useCallback(async () => {
    setLaunching(true);
    setError(null);
    try {
      const res = await launchExploration(apiBase, token, config);
      onLaunched(res.session_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLaunching(false);
    }
  }, [apiBase, token, config, onLaunched]);

  const toggleAdapter = useCallback((adapter: string) => {
    setConfig((prev) => {
      const has = prev.adapters.includes(adapter);
      const next = has
        ? prev.adapters.filter((a) => a !== adapter)
        : [...prev.adapters, adapter];
      return { ...prev, adapters: next.length ? next : prev.adapters };
    });
  }, []);

  return (
    <div className="rs-modal-backdrop" onClick={onClose}>
      <div className="rs-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rs-modal-header">
          <h3>Launch Exploration</h3>
          <button className="rs-modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="rs-modal-body">
          <div className="rs-form-row">
            <label>Provider</label>
            <select
              value={config.provider}
              onChange={(e) => setConfig((p) => ({ ...p, provider: e.target.value as "anthropic" | "openai" }))}
            >
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>

          <div className="rs-form-row">
            <label>Iterations</label>
            <input
              type="number"
              min={1}
              max={20}
              value={config.iterations}
              onChange={(e) => setConfig((p) => ({ ...p, iterations: Math.max(1, Math.min(20, Number(e.target.value) || 1)) }))}
            />
          </div>

          <div className="rs-form-row">
            <label>Temperature</label>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={config.temperature}
              onChange={(e) => setConfig((p) => ({ ...p, temperature: Math.max(0, Math.min(2, Number(e.target.value) || 0.7)) }))}
            />
          </div>

          <div className="rs-form-row">
            <label>Adapters (LLM can also propose new ones)</label>
            <div className="rs-checkbox-group">
              {ALL_ADAPTERS.map((a) => (
                <label key={a} className="rs-checkbox-label">
                  <input
                    type="checkbox"
                    checked={config.adapters.includes(a)}
                    onChange={() => toggleAdapter(a)}
                  />
                  {a}
                </label>
              ))}
            </div>
            <span style={{ fontSize: "0.75rem", color: "#888", marginTop: 4, display: "block" }}>
              The LLM is free to invent new adapter architectures. Novel proposals are saved as blueprints for development.
            </span>
          </div>

          <div className="rs-form-row">
            <label className="rs-checkbox-label">
              <input
                type="checkbox"
                checked={config.skip_sweep}
                onChange={(e) => setConfig((p) => ({ ...p, skip_sweep: e.target.checked }))}
              />
              Skip parameter sweep
            </label>
          </div>

          <div className="rs-form-row">
            <label className="rs-checkbox-label">
              <input
                type="checkbox"
                checked={config.skip_walkforward}
                onChange={(e) => setConfig((p) => ({ ...p, skip_walkforward: e.target.checked }))}
              />
              Skip walk-forward
            </label>
          </div>

          <div className="rs-form-row">
            <label>Extra context</label>
            <input
              type="text"
              placeholder="e.g. high volatility regime"
              value={config.extra_context}
              onChange={(e) => setConfig((p) => ({ ...p, extra_context: e.target.value }))}
              maxLength={500}
            />
          </div>

          {error && <div className="panel-error" role="alert">{error}</div>}
        </div>

        <div className="rs-modal-footer">
          <button className="bt-btn" onClick={onClose} disabled={launching}>Cancel</button>
          <button className="bt-btn bt-btn-run" onClick={handleLaunch} disabled={launching}>
            {launching ? "Launching\u2026" : "Launch"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ResearchPage() {
  const {
    apiBase, apiToken, subView,
    candidates, explorations, selectedDetail, selectedExplorationId,
    error, loading, showLaunchModal, rerunConfig,
    refreshAll, handleCandidateSelect, handleExplorationSelect,
    handleBack, handleRerun, handleLaunched,
    openLaunchModal, closeLaunchModal,
  } = useResearchData();

  if (subView === "candidate-detail" && selectedDetail) {
    return (
      <Panel title={`Research \u203A ${selectedDetail.name}`} className="panel-span-12">
        <CandidateDetailView
          detail={selectedDetail}
          onBack={handleBack}
          apiBase={apiBase}
          token={apiToken}
        />
      </Panel>
    );
  }

  if (subView === "exploration-detail" && selectedExplorationId) {
    return (
      <>
        <Panel title={`Exploration \u203A ${selectedExplorationId.slice(0, 12)}`} className="panel-span-12">
          <div className="rs-detail-header">
            <button className="rs-back-btn" onClick={handleBack}>&larr; Back</button>
            <h3>Exploration Session</h3>
          </div>
          <ExplorationLogPanel
            apiBase={apiBase}
            token={apiToken}
            sessionId={selectedExplorationId}
          />
        </Panel>
      </>
    );
  }

  return (
    <>
      <Panel title="Strategy Scoreboard" className="panel-span-12">
        <div className="rs-toolbar">
          <button className="bt-btn bt-btn-run" onClick={() => void refreshAll()} disabled={loading}>
            {loading ? "Loading\u2026" : "Refresh"}
          </button>
        </div>
        {error && <div className="panel-error" role="alert">{error}</div>}
        <CandidateTable candidates={candidates} onSelect={handleCandidateSelect} />
      </Panel>

      <Panel title="Exploration Sessions" className="panel-span-12">
        <div className="rs-toolbar">
          <button className="bt-btn bt-btn-run" onClick={openLaunchModal}>
            New Exploration
          </button>
        </div>
        <ExplorationTable sessions={explorations} onSelect={handleExplorationSelect} onRerun={handleRerun} />
      </Panel>

      {showLaunchModal && (
        <LaunchExplorationModal
          onClose={closeLaunchModal}
          onLaunched={handleLaunched}
          apiBase={apiBase}
          token={apiToken}
          initialConfig={rerunConfig}
        />
      )}
    </>
  );
}
