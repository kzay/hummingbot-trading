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

/** Realtime API on same host as the UI, port 9910 — avoids `localhost` vs `127.0.0.1` browser CORS mismatches. */
export function getDefaultApiBase(): string {
  if (typeof window === "undefined" || !window.location?.hostname) {
    return DEFAULT_API_BASE;
  }
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:9910`;
}
