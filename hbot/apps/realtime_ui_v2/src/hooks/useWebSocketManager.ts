import { useDashboardStore } from "../store/useDashboardStore";
import type { WsEventMessage, WsInboundMessage, WsSnapshotMessage } from "../types/realtime";
import { parseWsInboundMessage } from "../utils/realtimeParsers";
import {
  MARKET_QUOTE_THROTTLE_MS,
  MARKET_DEPTH_THROTTLE_MS,
  WS_PENDING_MESSAGES_CAP,
} from "../constants";

// ─── shared transport context ────────────────────────────────────────────

export interface TransportContext {
  stopped: boolean;
  apiDisabled: boolean;
  readonly authBlocksWs: boolean;
  restOnlyNoticeSent: boolean;
  hasConnectedOnce: boolean;
}

export function setRestOnlyMode(ctx: TransportContext): void {
  const store = useDashboardStore.getState();
  store.setConnectionStatus("closed");
  if (!ctx.restOnlyNoticeSent) {
    store.appendEventLine(
      "[ws] browser websocket auth is unsupported with bearer tokens; using HTTP polling only",
    );
    ctx.restOnlyNoticeSent = true;
  }
}

// ─── WS URL builder ─────────────────────────────────────────────────────

export function buildWsUrl(apiBase: string, instanceName: string, timeframeS: number): string {
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

// ─── internal constants & types ──────────────────────────────────────────

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

// ─── WS manager factory ─────────────────────────────────────────────────

export interface WsManagerCallbacks {
  refreshLiveState: () => Promise<void>;
}

export interface WsManager {
  connect: () => void;
  closeSocket: (isManualClose: boolean) => void;
  cancelFlush: () => void;
}

export function createWsManager(
  ctx: TransportContext,
  callbacks: WsManagerCallbacks,
): WsManager {
  let ws: WebSocket | null = null;
  let reconnectTimerId: number | null = null;
  let reconnectDelayMs = 1_500;
  let manualClose = false;
  let lastMarketQuoteProcessedAtMs = 0;
  let lastMarketDepthProcessedAtMs = 0;
  let pendingMessages: PendingMessage[] = [];
  let flushRafId: number | null = null;

  // ── message batching ───────────────────────────────────────────────────

  const flushPendingMessages = () => {
    flushRafId = null;
    if (ctx.stopped || pendingMessages.length === 0) {
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

    for (const pm of batch) {
      if (pm.sessionId !== activeSessionId) {
        continue;
      }
      const safe = pm.message as { type?: unknown; event_type?: unknown };
      const messageType = String(safe.type ?? "").trim();
      if (messageType === "snapshot") {
        latestSnapshot = pm;
        continue;
      }
      if (messageType === "event") {
        const et = String((pm.message as WsEventMessage).event_type ?? "").trim();
        if (et === "market_snapshot") { latestMarketSnapshot = pm; continue; }
        if (et === "market_quote") { latestQuote = pm; continue; }
        if (et === "market_depth_snapshot") { latestDepth = pm; continue; }
      }
      remainingMessages.push(pm);
    }

    const processPendingMessage = (pm: PendingMessage) => {
      const message = pm.message;
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
          if (pm.receivedAtMs - lastMarketQuoteProcessedAtMs < MARKET_QUOTE_THROTTLE_MS) {
            return;
          }
          lastMarketQuoteProcessedAtMs = pm.receivedAtMs;
        }
        if (eventType === "market_depth_snapshot") {
          if (pm.receivedAtMs - lastMarketDepthProcessedAtMs < MARKET_DEPTH_THROTTLE_MS) {
            return;
          }
          lastMarketDepthProcessedAtMs = pm.receivedAtMs;
        }

        if (!HIGH_FREQ_EVENT_TYPES.has(eventType)) {
          store.pushPayloadRecord(message, pm.receivedAtMs);
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
      void callbacks.refreshLiveState();
    }
  };

  const enqueueMessage = (message: WsInboundMessage, sessionId: number, receivedAtMs: number) => {
    if (pendingMessages.length >= WS_PENDING_MESSAGES_CAP) {
      pendingMessages.shift();
    }
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

  // ── connection management ──────────────────────────────────────────────

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
      try { ws.close(); } catch { /* no-op */ }
    }
    ws = null;
    if (isManualClose) {
      reconnectDelayMs = 1_500;
    }
  };

  const scheduleReconnect = () => {
    clearReconnectTimer();
    if (ctx.stopped || ctx.apiDisabled) {
      return;
    }
    reconnectTimerId = window.setTimeout(() => {
      const store = useDashboardStore.getState();
      store.markReconnectAttempt();
      store.setConnectionStatus("reconnecting");
      if (ctx.authBlocksWs) {
        setRestOnlyMode(ctx);
        void callbacks.refreshLiveState();
        return;
      }
      connect();
    }, reconnectDelayMs);
    reconnectDelayMs = Math.min(10_000, Math.round(reconnectDelayMs * 1.5));
  };

  const connect = () => {
    if (ctx.stopped) {
      return;
    }
    const store = useDashboardStore.getState();
    const { apiBase: base, apiToken: token, instanceName: inst, timeframeS: tf } = store.settings;
    if (!base.trim() || ctx.apiDisabled || ws !== null) {
      store.setConnectionStatus("closed");
      return;
    }
    if (token.trim()) {
      setRestOnlyMode(ctx);
      void callbacks.refreshLiveState();
      return;
    }
    ctx.hasConnectedOnce = true;
    const sessionId = store.beginSession();
    manualClose = false;

    let url = "";
    try {
      url = buildWsUrl(base, inst, tf);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      store.setConnectionStatus("error");
      store.appendEventLine(`[ws] invalid api url: ${msg}`);
      scheduleReconnect();
      return;
    }

    try {
      ws = new WebSocket(url);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      store.setConnectionStatus("error");
      store.appendEventLine(`[ws] connect failed: ${msg}`);
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      if (ctx.stopped) {
        return;
      }
      const activeStore = useDashboardStore.getState();
      if (sessionId !== activeStore.connection.wsSessionId) {
        return;
      }
      reconnectDelayMs = 1_500;
      activeStore.markConnected();
      activeStore.appendEventLine("[ws] connected");
      void callbacks.refreshLiveState();
    };

    ws.onmessage = (event) => {
      if (ctx.stopped) {
        return;
      }
      const activeStore = useDashboardStore.getState();
      if (sessionId !== activeStore.connection.wsSessionId) {
        return;
      }
      let parsed: WsInboundMessage;
      try {
        parsed = parseWsInboundMessage(JSON.parse(String(event.data)));
      } catch (error) {
        activeStore.markParseError();
        const msg = error instanceof Error ? error.message : "invalid websocket payload";
        activeStore.appendEventLine(`[ws] ${msg}`);
        return;
      }
      enqueueMessage(parsed, sessionId, Date.now());
    };

    ws.onerror = () => {
      if (ctx.stopped) {
        return;
      }
      const activeStore = useDashboardStore.getState();
      if (sessionId !== activeStore.connection.wsSessionId) {
        return;
      }
      ws = null; // Clear stale ref in case onclose doesn't fire (some environments)
      activeStore.setConnectionStatus("error");
      activeStore.appendEventLine("[ws] error");
    };

    ws.onclose = () => {
      if (ctx.stopped) {
        return;
      }
      const activeStore = useDashboardStore.getState();
      if (sessionId !== activeStore.connection.wsSessionId) {
        return;
      }
      
      ws = null; // Clear the old socket reference so reconnect can succeed

      activeStore.setConnectionStatus(manualClose ? "closed" : "reconnecting");
      if (!manualClose) {
        activeStore.appendEventLine("[ws] disconnected; reconnecting");
        scheduleReconnect();
      }
    };
  };

  return { connect, closeSocket, cancelFlush };
}
