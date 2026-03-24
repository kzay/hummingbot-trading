export function buildHeaders(token: string): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit & { timeoutMs?: number },
): Promise<Response> {
  const { timeoutMs = 10_000, ...fetchInit } = init ?? {};
  const controller = new AbortController();
  const existingSignal = fetchInit.signal;

  if (existingSignal) {
    existingSignal.addEventListener("abort", () => controller.abort(existingSignal.reason));
  }

  const timer = setTimeout(() => controller.abort(new DOMException("Fetch timed out", "TimeoutError")), timeoutMs);
  try {
    return await fetch(input, { ...fetchInit, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}
