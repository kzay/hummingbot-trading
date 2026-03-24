import { useDashboardStore } from "../store/useDashboardStore";
import { parseHealthPayload, parseRestStatePayload } from "../utils/realtimeParsers";
import { buildHeaders } from "../utils/fetch";
import { STATE_REFRESH_STALE_AFTER_MS } from "../constants";
import { type TransportContext, setRestOnlyMode } from "./useWebSocketManager";

// ─── REST fallback factory ───────────────────────────────────────────────

export interface RestCallbacks {
  closeSocket: (isManualClose: boolean) => void;
}

export interface RestFallback {
  refreshHealth: () => Promise<void>;
  refreshLiveState: () => Promise<void>;
  shouldRefreshLiveState: () => boolean;
  clearStateRequest: () => void;
}

export function createRestFallback(
  ctx: TransportContext,
  callbacks: RestCallbacks,
): RestFallback {
  let stateAbortController: AbortController | null = null;

  const clearStateRequest = () => {
    if (stateAbortController) {
      stateAbortController.abort();
      stateAbortController = null;
    }
  };

  const refreshHealth = async () => {
    const store = useDashboardStore.getState();
    const { apiBase: base, apiToken: token } = store.settings;
    try {
      const response = await fetch(`${base}/health`, {
        headers: buildHeaders(token),
      });
      if (!response.ok) {
        throw new Error(`health HTTP ${response.status}`);
      }
      const health = parseHealthPayload(await response.json());
      ctx.apiDisabled =
        String(health.status ?? health.mode ?? "").trim().toLowerCase() === "disabled";
      useDashboardStore.getState().setHealth({
        status: health.status ?? "unknown",
        streamAgeMs: Number(health.stream_age_ms ?? 0) || null,
        dbAvailable: Boolean(health.db_available),
        redisAvailable: Boolean(health.redis_available),
        fallbackActive: Boolean(health.fallback_active),
      });
      if (ctx.apiDisabled) {
        clearStateRequest();
        callbacks.closeSocket(true);
        useDashboardStore.getState().setConnectionStatus("closed");
      } else if (ctx.authBlocksWs) {
        callbacks.closeSocket(true);
        setRestOnlyMode(ctx);
      }
    } catch (error) {
      ctx.apiDisabled = false;
      const message = error instanceof Error ? error.message : String(error);
      const nextStore = useDashboardStore.getState();
      nextStore.setHealth({
        status: "fail",
        streamAgeMs: null,
        dbAvailable: false,
        redisAvailable: false,
        fallbackActive: false,
      });
      nextStore.appendEventLine(`[health] ${message}`);
    }
  };

  const refreshLiveState = async () => {
    if (ctx.apiDisabled) {
      return;
    }
    const store = useDashboardStore.getState();
    const { apiBase: base, apiToken: token, instanceName: inst } = store.settings;
    if (!inst.trim()) {
      return;
    }
    clearStateRequest();
    const controller = new AbortController();
    stateAbortController = controller;
    const requestInstanceName = inst.trim();
    const params = new URLSearchParams();
    params.set("instance_name", requestInstanceName);
    try {
      const response = await fetch(`${base}/api/v1/state?${params.toString()}`, {
        headers: buildHeaders(token),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`state HTTP ${response.status}`);
      }
      const payload = parseRestStatePayload(await response.json());
      if (ctx.stopped || stateAbortController !== controller) {
        return;
      }
      useDashboardStore.getState().ingestRestState(payload, requestInstanceName);
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      useDashboardStore.getState().appendEventLine(`[state] ${message}`);
    } finally {
      if (stateAbortController === controller) {
        stateAbortController = null;
      }
    }
  };

  const shouldRefreshLiveState = () => {
    const store = useDashboardStore.getState();
    if (store.connection.status !== "connected") {
      return true;
    }
    const lastOrdersTsMs = Number(store.freshness.ordersTsMs || 0);
    if (!lastOrdersTsMs || Date.now() - lastOrdersTsMs >= STATE_REFRESH_STALE_AFTER_MS) {
      return true;
    }
    const lastMessageTsMs = Number(store.connection.lastMessageTsMs || 0);
    if (!lastMessageTsMs) {
      return true;
    }
    return Date.now() - lastMessageTsMs >= STATE_REFRESH_STALE_AFTER_MS;
  };

  return { refreshHealth, refreshLiveState, shouldRefreshLiveState, clearStateRequest };
}
