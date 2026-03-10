import { beforeEach, describe, expect, it } from "vitest";

import { useDashboardStore } from "./useDashboardStore";

function resetStore() {
  sessionStorage.clear();
  localStorage.clear();
  useDashboardStore.getState().updateSettings({
    apiBase: "http://localhost:9910",
    apiToken: "",
    instanceName: "bot1",
    timeframeS: 60,
    orderFilter: "",
    fillFilter: "",
    fillSide: "all",
    fillMaker: "all",
    eventFilter: "",
    feedPaused: false,
    autoScrollFeed: true,
  });
  useDashboardStore.getState().resetLiveData();
}

describe("useDashboardStore", () => {
  beforeEach(() => {
    resetStore();
  });

  it("keeps fresher websocket state when an older REST payload arrives later", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "market_quote",
      ts_ms: 2_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "market_quote",
        instance_name: "bot1",
        trading_pair: "BTC-USDT",
        mid_price: 101,
        best_bid: 100,
        best_ask: 102,
      },
    });

    store.ingestEventMessage({
      type: "event",
      event_type: "bot_fill",
      ts_ms: 2_200,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "bot_fill",
        instance_name: "bot1",
        trading_pair: "BTC-USDT",
        order_id: "fresh-fill",
        timestamp_ms: 2_200,
        side: "buy",
        price: 101,
        amount_base: 1,
        notional_quote: 101,
        fee_quote: 0.1,
        realized_pnl_quote: 0,
        is_maker: true,
      },
    });

    expect(useDashboardStore.getState().market.mid_price).toBe(101);
    expect(useDashboardStore.getState().freshness.marketTsMs).toBe(2_000);

    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            latest_market_ts_ms: 1_500,
            latest_fill_ts_ms: 1_500,
          },
        },
        stream: {
          market: {
            trading_pair: "BTC-USDT",
            mid_price: 99,
            best_bid: 98,
            best_ask: 100,
            timestamp_ms: 1_500,
          },
          fills: [
            {
              order_id: "stale-fill",
              timestamp_ms: 1_500,
              side: "sell",
              price: 99,
              amount_base: 1,
              notional_quote: 99,
              fee_quote: 0.1,
              realized_pnl_quote: -1,
              is_maker: false,
            },
          ],
          fills_total: 1,
        },
      },
      "bot1",
    );

    const state = useDashboardStore.getState();
    expect(state.market.mid_price).toBe(101);
    expect(state.fills).toHaveLength(1);
    expect(state.fills[0]?.order_id).toBe("fresh-fill");
    expect(state.freshness.staleRestRejectCount).toBe(1);
    expect(state.eventLines.some((line) => line.includes("ignored stale segments"))).toBe(true);
  });

  it("ignores shared depth events for a different pair than the selected instance state", () => {
    const store = useDashboardStore.getState();

    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            latest_market_ts_ms: 10_000,
          },
        },
        stream: {
          market: {
            trading_pair: "BTC-USDT",
            mid_price: 70_600,
            best_bid: 70_599.9,
            best_ask: 70_600.1,
            timestamp_ms: 10_000,
          },
          depth: {
            trading_pair: "BTC-USDT",
            best_bid: 70_599.8,
            best_ask: 70_600.2,
            bids: [{ price: 70_599.8, size: 1 }],
            asks: [{ price: 70_600.2, size: 1 }],
            timestamp_ms: 10_000,
          },
        },
      },
      "bot1",
    );

    store.ingestEventMessage({
      type: "event",
      event_type: "market_depth_snapshot",
      ts_ms: 10_500,
      trading_pair: "ETH-USDT",
      event: {
        event_type: "market_depth_snapshot",
        trading_pair: "ETH-USDT",
        best_bid: 2_063,
        best_ask: 2_063.01,
        bids: [{ price: 2_063, size: 1 }],
        asks: [{ price: 2_063.01, size: 1 }],
      },
    });

    const state = useDashboardStore.getState();
    expect(state.market.trading_pair).toBe("BTC-USDT");
    expect(state.depth.trading_pair).toBe("BTC-USDT");
    expect(state.depth.best_bid).toBe(70_599.8);
    expect(state.depth.best_ask).toBe(70_600.2);
    expect(state.connection.droppedMessageCount).toBe(1);
  });
});
