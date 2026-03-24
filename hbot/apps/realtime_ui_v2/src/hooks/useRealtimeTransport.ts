import { useEffect, useRef } from "react";

import { useDashboardStore, pruneRuntimeEventsBuffer } from "../store/useDashboardStore";
import {
  HEALTH_REFRESH_MS,
  STATE_REFRESH_MS,
  AUTH_REST_ONLY_REFRESH_MS,
  PRUNE_RUNTIME_EVENTS_MS,
  SELECTION_RESTART_DEBOUNCE_MS,
} from "../constants";
import {
  type TransportContext,
  setRestOnlyMode,
  createWsManager,
} from "./useWebSocketManager";
import { type RestFallback, createRestFallback } from "./useRestFallback";

export function useRealtimeTransport(): void {
  const apiBase = useDashboardStore((state) => state.settings.apiBase);
  const apiToken = useDashboardStore((state) => state.settings.apiToken);
  const instanceName = useDashboardStore((state) => state.settings.instanceName);
  const timeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const restartTransportRef = useRef<(() => void) | null>(null);
  const transportReadyRef = useRef(false);
  const selectionSignatureRef = useRef("");

  useEffect(() => {
    const authBlocksWs = apiToken.trim().length > 0;
    const stateRefreshMs = authBlocksWs ? AUTH_REST_ONLY_REFRESH_MS : STATE_REFRESH_MS;

    const ctx: TransportContext = {
      stopped: false,
      apiDisabled: false,
      authBlocksWs,
      restOnlyNoticeSent: false,
      hasConnectedOnce: false,
    };

    // Circular callbacks: WS needs rest refresh; REST needs WS close. Break with a slot filled
    // immediately after both objects exist (effect-local, not a hook ref).
    const restSlot: { current: RestFallback | null } = { current: null };
    const wsManager = createWsManager(ctx, {
      refreshLiveState: () => Promise.resolve(restSlot.current?.refreshLiveState()),
    });
    const restFallback = createRestFallback(ctx, {
      closeSocket: (manual) => wsManager.closeSocket(manual),
    });
    restSlot.current = restFallback;

    const restartTransport = () => {
      restFallback.clearStateRequest();
      wsManager.closeSocket(true);
      useDashboardStore.getState().resetLiveData();
      if (!ctx.apiDisabled) {
        if (ctx.authBlocksWs) {
          setRestOnlyMode(ctx);
        } else {
          wsManager.connect();
        }
        void restFallback.refreshLiveState();
      }
    };

    restartTransportRef.current = () => {
      if (ctx.stopped) {
        return;
      }
      restartTransport();
    };
    transportReadyRef.current = true;
    {
      const initialSettings = useDashboardStore.getState().settings;
      selectionSignatureRef.current =
        `${initialSettings.instanceName.trim()}|${String(initialSettings.timeframeS)}`;
    }

    useDashboardStore.getState().resetLiveData();
    void restFallback.refreshHealth().finally(() => {
      if (ctx.stopped || ctx.apiDisabled || ctx.hasConnectedOnce) {
        return;
      }
      if (ctx.authBlocksWs) {
        setRestOnlyMode(ctx);
      } else {
        wsManager.connect();
      }
      void restFallback.refreshLiveState();
    });

    const healthTimerId = window.setInterval(() => {
      void restFallback.refreshHealth();
    }, HEALTH_REFRESH_MS);
    const stateTimerId = window.setInterval(() => {
      if (ctx.authBlocksWs || restFallback.shouldRefreshLiveState()) {
        void restFallback.refreshLiveState();
      }
    }, stateRefreshMs);
    const pruneTimerId = window.setInterval(() => {
      pruneRuntimeEventsBuffer();
    }, PRUNE_RUNTIME_EVENTS_MS);

    return () => {
      ctx.stopped = true;
      restartTransportRef.current = null;
      transportReadyRef.current = false;
      window.clearInterval(healthTimerId);
      window.clearInterval(stateTimerId);
      window.clearInterval(pruneTimerId);
      wsManager.cancelFlush();
      restFallback.clearStateRequest();
      wsManager.closeSocket(true);
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
