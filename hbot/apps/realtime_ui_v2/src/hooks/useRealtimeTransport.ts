import { useEffect, useRef } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import type { WsEventMessage, WsInboundMessage, WsSnapshotMessage } from "../types/realtime";
import { parseHealthPayload, parseRestStatePayload, parseWsInboundMessage } from "../utils/realtimeParsers";

function buildHeaders(token: string): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

function buildWsUrl(apiBase: string, instanceName: string, timeframeS: number): string {
  const base = new URL(apiBase);
  const protocol = base.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${base.host}/api/v1/ws`);
  if (instanceName.trim()) {
    url.searchParams.set("instance_name", instanceName.trim());
  }
  url.searchParams.set("timeframe_s", String(timeframeS || 60));
  url.searchParams.set("limit", "300");
  return url.toString();
}

const HEALTH_REFRESH_MS = 30_000;
const STATE_REFRESH_MS = 60_000;
const AUTH_REST_ONLY_REFRESH_MS = 5_000;
const STATE_REFRESH_STALE_AFTER_MS = 20_000;
const PRUNE_RUNTIME_EVENTS_MS = 30_000;
const SELECTION_RESTART_DEBOUNCE_MS = 300;
const MARKET_QUOTE_THROTTLE_MS = 500;
const MARKET_DEPTH_THROTTLE_MS = 750;

const HIGH_FREQ_EVENT_TYPES = new Set([
  "market_quote",
  "market_snapshot",
  "market_depth_snapshot",
]);

interface PendingMessage {
  sessionId: number;
  receivedAtMs: number;
  message: WsInboundMessage;
}

export function useRealtimeTransport(): void {
  const apiBase = useDashboardStore((state) => state.settings.apiBase);
  const apiToken = useDashboardStore((state) => state.settings.apiToken);
  const instanceName = useDashboardStore((state) => state.settings.instanceName);
  const timeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const restartTransportRef = useRef<(() => void) | null>(null);
  const transportReadyRef = useRef(false);
  const selectionSignatureRef = useRef("");

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimerId: number | null = null;
    let healthTimerId: number | null = null;
    let stateTimerId: number | null = null;
    let pruneTimerId: number | null = null;
    let stateAbortController: AbortController | null = null;
    let stopped = false;
    let reconnectDelayMs = 1_500;
    let manualClose = false;
    let apiDisabled = false;
    let hasConnectedOnce = false;
    let lastMarketQuoteProcessedAtMs = 0;
    let lastMarketDepthProcessedAtMs = 0;
    let restOnlyNoticeSent = false;

    let pendingMessages: PendingMessage[] = [];
    let flushRafId: number | null = null;
    const authBlocksWs = apiToken.trim().length > 0;
    const stateRefreshMs = authBlocksWs ? AUTH_REST_ONLY_REFRESH_MS : STATE_REFRESH_MS;

    const setRestOnlyMode = () => {
      const store = useDashboardStore.getState();
      store.setConnectionStatus("closed");
      if (!restOnlyNoticeSent) {
        store.appendEventLine("[ws] browser websocket auth is unsupported with bearer tokens; using HTTP polling only");
        restOnlyNoticeSent = true;
      }
    };

    const flushPendingMessages = () => {
      flushRafId = null;
      if (stopped || pendingMessages.length === 0) {
        return;
      }
      const batch = pendingMessages;
      pendingMessages = [];

      const store = useDashboardStore.getState();
      const activeSessionId = store.connection.wsSessionId;
      let needsLiveStateRefresh = false;
      let lastReceivedType = "";
      let latestSnapshot: PendingMessage | null = null;
      let latestMarketSnapshot: PendingMessage | null = null;
      let latestQuote: PendingMessage | null = null;
      let latestDepth: PendingMessage | null = null;
      const remainingMessages: PendingMessage[] = [];

      for (const pendingMessage of batch) {
        if (pendingMessage.sessionId !== activeSessionId) {
          continue;
        }
        const safe = pendingMessage.message as { type?: unknown; event_type?: unknown };
        const messageType = String(safe.type ?? "").trim();
        if (messageType === "snapshot") {
          latestSnapshot = pendingMessage;
          continue;
        }
        if (messageType === "event") {
          const eventType = String((pendingMessage.message as WsEventMessage).event_type ?? "").trim();
          if (eventType === "market_snapshot") {
            latestMarketSnapshot = pendingMessage;
            continue;
          }
          if (eventType === "market_quote") {
            latestQuote = pendingMessage;
            continue;
          }
          if (eventType === "market_depth_snapshot") {
            latestDepth = pendingMessage;
            continue;
          }
        }
        remainingMessages.push(pendingMessage);
      }

      const processPendingMessage = (pendingMessage: PendingMessage) => {
        const message = pendingMessage.message;
        const safe = message as { type?: unknown; event_type?: unknown };
        const messageType = String(safe.type ?? "").trim();

        if (messageType === "snapshot") {
          store.ingestSnapshot(message as WsSnapshotMessage);
          lastReceivedType = "snapshot";
          return;
        }
        if (messageType === "event") {
          const eventMessage = message as WsEventMessage;
          const eventType = String(eventMessage.event_type ?? "").trim();
          if (eventType === "market_quote") {
            if (pendingMessage.receivedAtMs - lastMarketQuoteProcessedAtMs < MARKET_QUOTE_THROTTLE_MS) {
              return;
            }
            lastMarketQuoteProcessedAtMs = pendingMessage.receivedAtMs;
          }
          if (eventType === "market_depth_snapshot") {
            if (pendingMessage.receivedAtMs - lastMarketDepthProcessedAtMs < MARKET_DEPTH_THROTTLE_MS) {
              return;
            }
            lastMarketDepthProcessedAtMs = pendingMessage.receivedAtMs;
          }

          if (!HIGH_FREQ_EVENT_TYPES.has(eventType)) {
            store.pushPayloadRecord(message, pendingMessage.receivedAtMs);
          }

          store.ingestEventMessage(eventMessage);
          lastReceivedType = eventType || "event";

          if (eventType === "bot_fill" || eventType === "paper_exchange_event") {
            needsLiveStateRefresh = true;
          }
          return;
        }
        lastReceivedType = messageType || lastReceivedType;
      };

      if (latestSnapshot) {
        processPendingMessage(latestSnapshot);
      }
      remainingMessages.forEach(processPendingMessage);
      if (latestQuote) {
        processPendingMessage(latestQuote);
      } else if (latestMarketSnapshot) {
        processPendingMessage(latestMarketSnapshot);
      }
      if (latestDepth) {
        processPendingMessage(latestDepth);
      }

      if (lastReceivedType) {
        store.markMessageReceived(lastReceivedType);
      }

      if (needsLiveStateRefresh) {
        void refreshLiveState();
      }
    };

    const enqueueMessage = (message: WsInboundMessage, sessionId: number, receivedAtMs: number) => {
      pendingMessages.push({ message, sessionId, receivedAtMs });
      if (flushRafId === null) {
        flushRafId = requestAnimationFrame(flushPendingMessages);
      }
    };

    const cancelFlush = () => {
      if (flushRafId !== null) {
        cancelAnimationFrame(flushRafId);
        flushRafId = null;
      }
      pendingMessages = [];
    };

    const clearReconnectTimer = () => {
      if (reconnectTimerId !== null) {
        window.clearTimeout(reconnectTimerId);
        reconnectTimerId = null;
      }
    };

    const closeSocket = (isManualClose: boolean) => {
      manualClose = isManualClose;
      clearReconnectTimer();
      cancelFlush();
      if (ws) {
        try {
          ws.close();
        } catch {
          // no-op
        }
      }
      ws = null;
    };

    const restartTransport = () => {
      clearStateRequest();
      closeSocket(true);
      useDashboardStore.getState().resetLiveData();
      if (!apiDisabled) {
        if (authBlocksWs) {
          setRestOnlyMode();
        } else {
          connect();
        }
        void refreshLiveState();
      }
    };

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
        apiDisabled = String(health.status ?? health.mode ?? "").trim().toLowerCase() === "disabled";
        useDashboardStore.getState().setHealth({
          status: health.status ?? "unknown",
          streamAgeMs: Number(health.stream_age_ms ?? 0) || null,
          dbAvailable: Boolean(health.db_available),
          redisAvailable: Boolean(health.redis_available),
          fallbackActive: Boolean(health.fallback_active),
        });
        if (apiDisabled) {
          clearStateRequest();
          closeSocket(true);
          useDashboardStore.getState().setConnectionStatus("closed");
        } else if (authBlocksWs) {
          closeSocket(true);
          setRestOnlyMode();
        }
      } catch (error) {
        apiDisabled = false;
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
      if (apiDisabled) {
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
        if (stopped || stateAbortController !== controller) {
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
      const lastMessageTsMs = Number(store.connection.lastMessageTsMs || 0);
      if (!lastMessageTsMs) {
        return true;
      }
      return Date.now() - lastMessageTsMs >= STATE_REFRESH_STALE_AFTER_MS;
    };

    const scheduleReconnect = () => {
      clearReconnectTimer();
      if (stopped || apiDisabled) {
        return;
      }
      reconnectTimerId = window.setTimeout(() => {
        const store = useDashboardStore.getState();
        store.markReconnectAttempt();
        store.setConnectionStatus("reconnecting");
        if (authBlocksWs) {
          setRestOnlyMode();
          void refreshLiveState();
          return;
        }
        connect();
      }, reconnectDelayMs);
      reconnectDelayMs = Math.min(10_000, Math.round(reconnectDelayMs * 1.5));
    };

    const connect = () => {
      const store = useDashboardStore.getState();
      const { apiBase: base, apiToken: token, instanceName: inst, timeframeS: tf } = store.settings;
      if (!base.trim() || apiDisabled || ws !== null) {
        store.setConnectionStatus("closed");
        return;
      }
      if (token.trim()) {
        setRestOnlyMode();
        void refreshLiveState();
        return;
      }
      hasConnectedOnce = true;
      const sessionId = store.beginSession();
      manualClose = false;

      let url = "";
      try {
        url = buildWsUrl(base, inst, tf);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        store.setConnectionStatus("error");
        store.appendEventLine(`[ws] invalid api url: ${message}`);
        scheduleReconnect();
        return;
      }

      try {
        ws = new WebSocket(url);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        store.setConnectionStatus("error");
        store.appendEventLine(`[ws] connect failed: ${message}`);
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        if (stopped) {
          return;
        }
        const activeStore = useDashboardStore.getState();
        if (sessionId !== activeStore.connection.wsSessionId) {
          return;
        }
        reconnectDelayMs = 1_500;
        activeStore.markConnected();
        activeStore.appendEventLine("[ws] connected");
        void refreshLiveState();
      };

      ws.onmessage = (event) => {
        if (stopped) {
          return;
        }
        const activeStore = useDashboardStore.getState();
        if (sessionId !== activeStore.connection.wsSessionId) {
          return;
        }
        let message: WsInboundMessage;
        try {
          message = parseWsInboundMessage(JSON.parse(String(event.data)));
        } catch (error) {
          activeStore.markParseError();
          const message = error instanceof Error ? error.message : "invalid websocket payload";
          activeStore.appendEventLine(`[ws] ${message}`);
          return;
        }
        enqueueMessage(message, sessionId, Date.now());
      };

      ws.onerror = () => {
        if (stopped) {
          return;
        }
        const activeStore = useDashboardStore.getState();
        if (sessionId !== activeStore.connection.wsSessionId) {
          return;
        }
        activeStore.setConnectionStatus("error");
        activeStore.appendEventLine("[ws] error");
      };

      ws.onclose = () => {
        if (stopped) {
          return;
        }
        const activeStore = useDashboardStore.getState();
        if (sessionId !== activeStore.connection.wsSessionId) {
          return;
        }
        activeStore.setConnectionStatus(manualClose ? "closed" : "reconnecting");
        if (!manualClose) {
          activeStore.appendEventLine("[ws] disconnected; reconnecting");
          scheduleReconnect();
        }
      };
    };

    restartTransportRef.current = () => {
      if (stopped) {
        return;
      }
      restartTransport();
    };
    transportReadyRef.current = true;
    {
      const initialSettings = useDashboardStore.getState().settings;
      selectionSignatureRef.current = `${initialSettings.instanceName.trim()}|${String(initialSettings.timeframeS)}`;
    }

    useDashboardStore.getState().resetLiveData();
    void refreshHealth().finally(() => {
      if (!apiDisabled && !hasConnectedOnce) {
        if (authBlocksWs) {
          setRestOnlyMode();
        } else {
          connect();
        }
        void refreshLiveState();
      }
    });

    healthTimerId = window.setInterval(() => {
      void refreshHealth();
    }, HEALTH_REFRESH_MS);
    stateTimerId = window.setInterval(() => {
      if (authBlocksWs || shouldRefreshLiveState()) {
        void refreshLiveState();
      }
    }, stateRefreshMs);
    pruneTimerId = window.setInterval(() => {
      useDashboardStore.getState().pruneRuntimeEvents();
    }, PRUNE_RUNTIME_EVENTS_MS);

    return () => {
      stopped = true;
      restartTransportRef.current = null;
      transportReadyRef.current = false;
      if (healthTimerId !== null) {
        window.clearInterval(healthTimerId);
      }
      if (stateTimerId !== null) {
        window.clearInterval(stateTimerId);
      }
      if (pruneTimerId !== null) {
        window.clearInterval(pruneTimerId);
      }
      cancelFlush();
      clearStateRequest();
      closeSocket(true);
      useDashboardStore.getState().setConnectionStatus("closed");
    };
  }, [apiBase, apiToken]);

  useEffect(() => {
    const nextSelectionSignature = `${instanceName.trim()}|${String(timeframeS)}`;
    if (!transportReadyRef.current) {
      selectionSignatureRef.current = nextSelectionSignature;
      return;
    }
    if (selectionSignatureRef.current === nextSelectionSignature) {
      return;
    }
    const timeoutId = window.setTimeout(() => {
      selectionSignatureRef.current = nextSelectionSignature;
      restartTransportRef.current?.();
    }, SELECTION_RESTART_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [instanceName, timeframeS]);
}
