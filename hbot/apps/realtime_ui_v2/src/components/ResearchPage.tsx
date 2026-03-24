import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useShallow } from "zustand/react/shallow";

import { Panel } from "./Panel";
import { useDashboardStore } from "../store/useDashboardStore";
import type {
  CandidateDetail,
  ExplorationSession,
  IterationEvent,
  ResearchCandidate,
} from "../types/research";
import {
  explorationLogUrl,
  fetchCandidateDetail,
  fetchCandidates,
  fetchExplorationDetail,
  fetchExplorations,
  fetchReport,
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

function ExplorationTable({ sessions, onSelect }: {
  sessions: ExplorationSession[];
  onSelect: (id: string) => void;
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
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.session_id} onClick={() => onSelect(s.session_id)} style={{ cursor: "pointer" }}>
              <td className="rs-name-cell">{s.session_id.slice(0, 12)}</td>
              <td>
                <span className="rs-badge" style={{ background: s.status === "completed" ? "var(--clr-up, #26a69a)" : "var(--clr-warn, #ffa726)" }}>
                  {s.status}
                </span>
              </td>
              <td style={{ textAlign: "center" }}>{s.iteration_count}</td>
              <td>{fmtScore(s.best_score)}</td>
              <td>{s.best_candidate || "\u2014"}</td>
              <td>{s.created_at?.slice(0, 16).replace("T", " ") || "\u2014"}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
  const preRef = useRef<HTMLPreElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
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

  useEffect(() => {
    if (autoScroll && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!preRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = preRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }, []);

  return (
    <div className="rs-exploration-log">
      <div className="rs-section-title">Live Iterations</div>
      <pre ref={preRef} className="rs-log-panel" onScroll={handleScroll}>
        {events.length
          ? events.map((ev) =>
              `[iter ${ev.iteration}] ${ev.candidate_name}  score=${fmtScore(ev.score)}  rec=${ev.recommendation ?? "\u2014"}`
            ).join("\n")
          : "Waiting for iteration events\u2026"}
      </pre>
      {!autoScroll && (
        <button
          className="bt-scroll-btn"
          onClick={() => {
            setAutoScroll(true);
            if (preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight;
          }}
        >
          &darr; Jump to bottom
        </button>
      )}
      {done && summary && (
        <div className="rs-summary-block">
          <strong>Session complete</strong>
          <span>Best: {String(summary.best_observed_candidate || "\u2014")} ({fmtScore(summary.best_observed_score as number | null)})</span>
          <span>Iterations: {String(summary.iterations ?? "\u2014")}</span>
        </div>
      )}
    </div>
  );
}

type ResearchSubView = "scoreboard" | "candidate-detail" | "exploration-detail";

export function ResearchPage() {
  const { apiBase, apiToken } = useDashboardStore(
    useShallow((s) => ({ apiBase: s.settings.apiBase, apiToken: s.settings.apiToken })),
  );

  const [subView, setSubView] = useState<ResearchSubView>("scoreboard");
  const [candidates, setCandidates] = useState<ResearchCandidate[]>([]);
  const [explorations, setExplorations] = useState<ExplorationSession[]>([]);
  const [selectedDetail, setSelectedDetail] = useState<CandidateDetail | null>(null);
  const [selectedExplorationId, setSelectedExplorationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cands, expls] = await Promise.all([
        fetchCandidates(apiBase, apiToken),
        fetchExplorations(apiBase, apiToken),
      ]);
      setCandidates(cands);
      setExplorations(expls);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apiBase, apiToken]);

  useEffect(() => { void refreshAll(); }, [refreshAll]);

  const handleCandidateSelect = useCallback(async (name: string) => {
    setError(null);
    try {
      const detail = await fetchCandidateDetail(apiBase, apiToken, name);
      setSelectedDetail(detail);
      setSubView("candidate-detail");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [apiBase, apiToken]);

  const handleExplorationSelect = useCallback((sessionId: string) => {
    setSelectedExplorationId(sessionId);
    setSubView("exploration-detail");
  }, []);

  const handleBack = useCallback(() => {
    setSubView("scoreboard");
    setSelectedDetail(null);
    setSelectedExplorationId(null);
  }, []);

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
        <ExplorationTable sessions={explorations} onSelect={handleExplorationSelect} />
      </Panel>
    </>
  );
}
