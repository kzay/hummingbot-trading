import { z } from "zod";
import type {
  CandidateDetail,
  ExplorationSession,
  LaunchExplorationRequest,
  LaunchExplorationResponse,
  ResearchCandidate,
} from "../types/research";
import { buildHeaders, fetchWithTimeout } from "./fetch";

const ResearchCandidateSchema = z.object({
  name: z.string(),
  hypothesis: z.string(),
  adapter_mode: z.string(),
  lifecycle: z.string(),
  best_score: z.number().nullable(),
  best_recommendation: z.string().nullable(),
  experiment_count: z.number(),
});

const LifecycleTransitionSchema = z.object({
  from_state: z.string(),
  to_state: z.string(),
  timestamp: z.string(),
  reason: z.string(),
});

const ExperimentEntrySchema = z.object({
  run_id: z.string(),
  candidate_name: z.string(),
  timestamp: z.string(),
  robustness_score: z.number().nullable(),
  recommendation: z.string().nullable(),
  config_snapshot: z.record(z.string(), z.unknown()).optional(),
});

const CandidateDetailSchema = z.object({
  name: z.string(),
  hypothesis: z.string(),
  adapter_mode: z.string(),
  entry_logic: z.string(),
  exit_logic: z.string(),
  parameter_space: z.record(z.string(), z.unknown()),
  base_config: z.record(z.string(), z.unknown()),
  required_tests: z.array(z.string()),
  metadata: z.record(z.string(), z.unknown()),
  lifecycle: z.object({
    candidate_name: z.string(),
    current_state: z.string(),
    history: z.array(LifecycleTransitionSchema),
  }),
  experiments: z.array(ExperimentEntrySchema),
  best_score: z.number().nullable(),
  best_recommendation: z.string().nullable(),
  latest_report_path: z.string(),
});

const ExplorationSessionSchema = z.object({
  session_id: z.string(),
  status: z.enum(["running", "completed", "failed", "cancelled", "timed_out", "unknown"]),
  iteration_count: z.number(),
  best_score: z.number().nullable(),
  best_candidate: z.string(),
  created_at: z.string(),
  launch_params: z.record(z.string(), z.unknown()).optional(),
});

const LaunchExplorationResponseSchema = z.object({
  session_id: z.string(),
  status: z.string(),
  pid: z.number(),
  provider: z.string(),
  iterations: z.number(),
});

function url(apiBase: string, path: string): string {
  return `${apiBase.replace(/\/$/, "")}${path}`;
}

export async function fetchCandidates(
  apiBase: string,
  token: string,
): Promise<ResearchCandidate[]> {
  const res = await fetchWithTimeout(url(apiBase, "/api/research/candidates"), {
    headers: buildHeaders(token),
  });
  if (!res.ok) throw new Error(`Candidates fetch failed: ${res.status}`);
  const data = await res.json();
  return z.parse(z.array(ResearchCandidateSchema), data.candidates ?? []);
}

export async function fetchCandidateDetail(
  apiBase: string,
  token: string,
  name: string,
): Promise<CandidateDetail> {
  const res = await fetchWithTimeout(
    url(apiBase, `/api/research/candidates/${encodeURIComponent(name)}`),
    { headers: buildHeaders(token) },
  );
  if (!res.ok) throw new Error(`Candidate detail failed: ${res.status}`);
  return z.parse(CandidateDetailSchema, await res.json()) as CandidateDetail;
}

export async function fetchReport(
  apiBase: string,
  token: string,
  candidateName: string,
  runId: string,
): Promise<string> {
  const res = await fetchWithTimeout(
    url(
      apiBase,
      `/api/research/reports/${encodeURIComponent(candidateName)}/${encodeURIComponent(runId)}`,
    ),
    { headers: buildHeaders(token) },
  );
  if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
  return res.text();
}

export async function fetchExplorations(
  apiBase: string,
  token: string,
): Promise<ExplorationSession[]> {
  const res = await fetchWithTimeout(
    url(apiBase, "/api/research/explorations"),
    { headers: buildHeaders(token) },
  );
  if (!res.ok) throw new Error(`Explorations fetch failed: ${res.status}`);
  const data = await res.json();
  return z.parse(z.array(ExplorationSessionSchema), data.explorations ?? []) as ExplorationSession[];
}

export async function fetchExplorationDetail(
  apiBase: string,
  token: string,
  sessionId: string,
): Promise<Record<string, unknown>> {
  const res = await fetchWithTimeout(
    url(apiBase, `/api/research/explorations/${encodeURIComponent(sessionId)}`),
    { headers: buildHeaders(token) },
  );
  if (!res.ok) throw new Error(`Exploration detail failed: ${res.status}`);
  return res.json();
}

export async function launchExploration(
  apiBase: string,
  token: string,
  config: LaunchExplorationRequest,
): Promise<LaunchExplorationResponse> {
  const res = await fetchWithTimeout(
    url(apiBase, "/api/research/explorations"),
    {
      method: "POST",
      headers: buildHeaders(token),
      body: JSON.stringify(config),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Launch failed: ${res.status}`);
  }
  return z.parse(LaunchExplorationResponseSchema, await res.json()) as LaunchExplorationResponse;
}

export async function cancelExploration(
  apiBase: string,
  token: string,
  sessionId: string,
): Promise<void> {
  const res = await fetchWithTimeout(
    url(apiBase, `/api/research/explorations/${encodeURIComponent(sessionId)}/cancel`),
    {
      method: "POST",
      headers: buildHeaders(token),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Cancel failed: ${res.status}`);
  }
}

export function explorationLogUrl(
  apiBase: string,
  sessionId: string,
  token: string,
): string {
  const base = url(
    apiBase,
    `/api/research/explorations/${encodeURIComponent(sessionId)}/log`,
  );
  return token.trim()
    ? `${base}?token=${encodeURIComponent(token.trim())}`
    : base;
}
