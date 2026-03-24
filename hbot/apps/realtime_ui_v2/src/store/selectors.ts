import { useShallow } from "zustand/react/shallow";
import { useDashboardStore } from "./useDashboardStore";

export function useMarketData() {
  return useDashboardStore(useShallow((s) => ({
    market: s.market,
    latestMid: s.latestMid,
    midPriceDirection: s.midPriceDirection,
    latestQuoteTsMs: s.latestQuoteTsMs,
  })));
}

export function usePositionData() {
  return useDashboardStore(useShallow((s) => ({
    position: s.position,
  })));
}

export function useFillsData() {
  return useDashboardStore(useShallow((s) => ({
    fills: s.fills,
    fillsTotal: s.fillsTotal,
  })));
}

export function useOrdersData() {
  return useDashboardStore(useShallow((s) => ({
    orders: s.orders,
  })));
}

export function useConnectionHealth() {
  return useDashboardStore(useShallow((s) => ({
    connection: s.connection,
    health: s.health,
    freshness: s.freshness,
  })));
}

export function useDepthData() {
  return useDashboardStore(useShallow((s) => ({
    depth: s.depth,
  })));
}

export function useCandleData() {
  return useDashboardStore(useShallow((s) => ({
    candles: s.candles,
    latestCandle: s.latestCandle,
    candleSeriesNonce: s.candleSeriesNonce,
  })));
}

export function useSummaryData() {
  return useDashboardStore(useShallow((s) => ({
    summarySystem: s.summarySystem,
    summaryActivity: s.summaryActivity,
    summaryAccount: s.summaryAccount,
    alerts: s.alerts,
  })));
}

export function useEventFeed() {
  return useDashboardStore(useShallow((s) => ({
    eventLines: s.eventLines,
    payloads: s.payloads,
    selectedPayloadId: s.selectedPayloadId,
  })));
}

export function useSettings() {
  return useDashboardStore(useShallow((s) => s.settings));
}

export function useInstances() {
  return useDashboardStore(useShallow((s) => ({
    instanceNames: s.instanceNames,
    instanceStatuses: s.instanceStatuses,
    instanceStatusesError: s.instanceStatusesError,
  })));
}
