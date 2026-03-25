export const MAX_EVENT_LINES = 100;
export const MAX_PAYLOAD_RECORDS = 20;
export const MAX_FILLS = 220;
export const MAX_CANDLES = 300;
export const RUNTIME_EVENT_RETENTION_MS = 5 * 60 * 1000;
export const MAX_RUNTIME_EVENTS = 600;

export const HEALTH_REFRESH_MS = 30_000;
export const STATE_REFRESH_MS = 60_000;
export const AUTH_REST_ONLY_REFRESH_MS = 5_000;
export const STATE_REFRESH_STALE_AFTER_MS = 120_000;
export const PRUNE_RUNTIME_EVENTS_MS = 30_000;
export const SELECTION_RESTART_DEBOUNCE_MS = 300;
export const MARKET_QUOTE_THROTTLE_MS = 200;
export const MARKET_DEPTH_THROTTLE_MS = 333;

export const WS_PENDING_MESSAGES_CAP = 500;

/** Fallback when `window` is unavailable (tests, SSR). Prefer `getDefaultApiBase()` in the browser. */
export const DEFAULT_API_BASE = "http://localhost:9910";

/**
 * When served by the nginx reverse-proxy the API is available on the same
 * origin (nginx proxies /api/ and /health to realtime-ui-api:9910).
 * Only fall back to the explicit :9910 port during local dev (Vite on :5173).
 */
export function getDefaultApiBase(): string {
  if (typeof window === "undefined" || !window.location?.hostname) {
    return DEFAULT_API_BASE;
  }
  const { protocol, hostname, port } = window.location;
  const isDevServer = port === "5173" || port === "5174";
  if (isDevServer) {
    return `${protocol}//${hostname}:9910`;
  }
  return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
}
