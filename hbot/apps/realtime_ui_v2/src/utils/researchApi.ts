import type {
  CandidateDetail,
  ExplorationSession,
  ResearchCandidate,
} from "../types/research";
import { buildHeaders, fetchWithTimeout } from "./fetch";

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
  return data.candidates ?? [];
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
  return (await res.json()) as CandidateDetail;
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
  return data.explorations ?? [];
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
