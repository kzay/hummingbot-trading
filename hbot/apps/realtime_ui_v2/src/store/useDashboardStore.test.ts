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

  it("merges summary activity when market snapshot regresses but fill timestamps advance", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "market_quote",
      ts_ms: 5_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "market_quote",
        instance_name: "bot1",
        trading_pair: "BTC-USDT",
        mid_price: 100,
        best_bid: 99,
        best_ask: 101,
      },
    });

    store.ingestEventMessage({
      type: "event",
      event_type: "bot_fill",
      ts_ms: 5_200,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "bot_fill",
        instance_name: "bot1",
        trading_pair: "BTC-USDT",
        order_id: "fill-a",
        timestamp_ms: 5_200,
        side: "buy",
        price: 100,
        amount_base: 1,
        notional_quote: 100,
        fee_quote: 0.1,
        realized_pnl_quote: 0,
        is_maker: true,
      },
    });

    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            latest_market_ts_ms: 1_000,
            latest_fill_ts_ms: 6_000,
          },
          activity: {
            window_1h: { fill_count: 42, maker_ratio: 0.5 },
          },
        },
        stream: {
          market: {
            trading_pair: "BTC-USDT",
            mid_price: 90,
            best_bid: 89,
            best_ask: 91,
            timestamp_ms: 1_000,
          },
          fills: [
            {
              order_id: "fill-b",
              timestamp_ms: 6_000,
              side: "buy",
              price: 95,
              amount_base: 1,
              notional_quote: 95,
              fee_quote: 0.1,
              realized_pnl_quote: 0,
              is_maker: true,
            },
          ],
          fills_total: 2,
        },
      },
      "bot1",
    );

    const state = useDashboardStore.getState();
    expect(state.market.mid_price).toBe(100);
    expect(state.fills[0]?.order_id).toBe("fill-b");
    expect(state.summaryActivity.window_1h).toEqual({
      fill_count: 42,
      maker_ratio: 0.5,
    });
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

  it("ingests paper_exchange_event order_fill as a fill", () => {
    const store = useDashboardStore.getState();

    expect(store.fills).toHaveLength(0);

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 5_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "order_fill",
        trading_pair: "BTC-USDT",
        order_id: "paper-fill-001",
        metadata: {
          side: "BUY",
          fill_price: "87000.5",
          fill_amount_base: "0.001",
          fill_notional_quote: "87.0005",
          fill_fee_quote: "0.0261",
          is_maker: "1",
        },
      },
    });

    const state = useDashboardStore.getState();
    expect(state.fills).toHaveLength(1);
    expect(state.fills[0]?.order_id).toBe("paper-fill-001");
    expect(state.fills[0]?.side).toBe("BUY");
    expect(state.fills[0]?.price).toBe(87_000.5);
    expect(state.fills[0]?.amount_base).toBeCloseTo(0.001);
    expect(state.fills[0]?.notional_quote).toBeCloseTo(87.0005);
    expect(state.fills[0]?.fee_quote).toBeCloseTo(0.0261);
    expect(state.fills[0]?.is_maker).toBe(true);
    expect(state.fillsTotal).toBe(1);
  });

  it("does not increment fillsTotal for duplicate fill events", () => {
    const store = useDashboardStore.getState();
    const duplicateEvent = {
      type: "event" as const,
      event_type: "bot_fill",
      ts_ms: 7_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "bot_fill",
        instance_name: "bot1",
        trading_pair: "BTC-USDT",
        order_id: "dup-fill-001",
        timestamp_ms: 7_000,
        side: "buy",
        price: 100,
        amount_base: 1,
        notional_quote: 100,
        fee_quote: 0.1,
        realized_pnl_quote: 1.25,
        is_maker: true,
      },
    };

    store.ingestEventMessage(duplicateEvent);
    store.ingestEventMessage(duplicateEvent);

    const state = useDashboardStore.getState();
    expect(state.fills).toHaveLength(1);
    expect(state.fillsTotal).toBe(1);
  });

  it("prefers an authoritative empty stream fill list over fallback fills", () => {
    const store = useDashboardStore.getState();

    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            latest_fill_ts_ms: 8_000,
          },
        },
        stream: {
          fills: [],
          fills_total: 0,
        },
        fallback: {
          fills: [
            {
              order_id: "fallback-fill",
              timestamp_ms: 7_500,
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
    expect(state.fills).toHaveLength(0);
    expect(state.fillsTotal).toBe(0);
  });

  it("replaces activity windows so omitted fields do not linger", () => {
    const store = useDashboardStore.getState();

    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            latest_fill_ts_ms: 9_000,
          },
          activity: {
            window_1h: {
              fill_count: 5,
              maker_ratio: 0.8,
              fees_quote: 1.2,
            },
          },
        },
      },
      "bot1",
    );

    expect(useDashboardStore.getState().summaryActivity.window_1h).toEqual({
      fill_count: 5,
      maker_ratio: 0.8,
      fees_quote: 1.2,
    });

    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            latest_fill_ts_ms: 9_500,
          },
          activity: {
            window_1h: {
              fill_count: 0,
            },
          },
        },
      },
      "bot1",
    );

    expect(useDashboardStore.getState().summaryActivity.window_1h).toEqual({
      fill_count: 0,
    });
  });

  it("does not ingest paper_exchange_event with non-fill command", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 5_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "cancel_order",
        trading_pair: "BTC-USDT",
        order_id: "cancel-001",
      },
    });

    expect(useDashboardStore.getState().fills).toHaveLength(0);
  });

  it("adds open order via submit_order event", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 10_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "submit_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-001",
        status: "processed",
        metadata: { side: "buy", price: "95000", amount_base: "0.01", order_state: "working" },
      },
    });

    const state = useDashboardStore.getState();
    expect(state.orders).toHaveLength(1);
    expect(state.orders[0].order_id).toBe("ord-001");
    expect(state.orders[0].side).toBe("BUY");
    expect(state.orders[0].state).toBe("working");
    expect(state.freshness.ordersTsMs).toBe(10_000);
  });

  it("updates existing order via subsequent submit_order (partially_filled)", () => {
    const store = useDashboardStore.getState();

    const baseEvent = (orderState: string) => ({
      type: "event" as const,
      event_type: "paper_exchange_event",
      ts_ms: 11_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "submit_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-002",
        status: "processed",
        metadata: { side: "sell", price: "96000", amount_base: "0.02", order_state: orderState },
      },
    });

    store.ingestEventMessage(baseEvent("working"));
    expect(useDashboardStore.getState().orders).toHaveLength(1);

    store.ingestEventMessage(baseEvent("partially_filled"));
    const state = useDashboardStore.getState();
    expect(state.orders).toHaveLength(1);
    expect(state.orders[0].state).toBe("partially_filled");
  });

  it("removes order via submit_order with terminal state", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 12_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "submit_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-003",
        status: "processed",
        metadata: { side: "buy", price: "94000", amount_base: "0.01", order_state: "working" },
      },
    });
    expect(useDashboardStore.getState().orders).toHaveLength(1);

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 12_500,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "submit_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-003",
        status: "processed",
        metadata: { side: "buy", price: "94000", amount_base: "0.01", order_state: "filled" },
      },
    });

    expect(useDashboardStore.getState().orders).toHaveLength(0);
  });

  it("removes order via cancel_order event", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 13_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "submit_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-004",
        status: "processed",
        metadata: { side: "sell", price: "97000", amount_base: "0.03", order_state: "working" },
      },
    });
    expect(useDashboardStore.getState().orders).toHaveLength(1);

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 13_500,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "cancel_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-004",
        status: "processed",
        metadata: {},
      },
    });

    expect(useDashboardStore.getState().orders).toHaveLength(0);
    expect(useDashboardStore.getState().freshness.ordersTsMs).toBe(13_500);
  });

  it("clears orders for pair via cancel_all event", () => {
    const store = useDashboardStore.getState();

    const submitOrder = (orderId: string, pair: string) =>
      store.ingestEventMessage({
        type: "event",
        event_type: "paper_exchange_event",
        ts_ms: 14_000,
        instance_name: "bot1",
        trading_pair: pair,
        event: {
          event_type: "paper_exchange_event",
          instance_name: "bot1",
          command: "submit_order",
          trading_pair: pair,
          order_id: orderId,
          status: "processed",
          metadata: { side: "buy", price: "90000", amount_base: "0.01", order_state: "working" },
        },
      });

    submitOrder("ord-010", "BTC-USDT");
    submitOrder("ord-011", "BTC-USDT");
    expect(useDashboardStore.getState().orders).toHaveLength(2);

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 14_500,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "cancel_all",
        trading_pair: "BTC-USDT",
        status: "processed",
        metadata: {},
      },
    });

    expect(useDashboardStore.getState().orders).toHaveLength(0);
  });

  it("removes order when order_fill arrives with filled state", () => {
    const store = useDashboardStore.getState();

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 15_000,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "submit_order",
        trading_pair: "BTC-USDT",
        order_id: "ord-020",
        status: "processed",
        metadata: { side: "buy", price: "93000", amount_base: "0.01", order_state: "working" },
      },
    });
    expect(useDashboardStore.getState().orders).toHaveLength(1);

    store.ingestEventMessage({
      type: "event",
      event_type: "paper_exchange_event",
      ts_ms: 15_500,
      instance_name: "bot1",
      trading_pair: "BTC-USDT",
      event: {
        event_type: "paper_exchange_event",
        instance_name: "bot1",
        command: "order_fill",
        trading_pair: "BTC-USDT",
        order_id: "ord-020",
        status: "processed",
        metadata: {
          side: "buy",
          fill_price: "93000",
          fill_amount_base: "0.01",
          fill_notional_quote: "930",
          fill_fee_quote: "0.5",
          realized_pnl_quote: "2.5",
          is_maker: "1",
          order_state: "filled",
        },
      },
    });

    const state = useDashboardStore.getState();
    expect(state.orders).toHaveLength(0);
    expect(state.fills).toHaveLength(1);
  });
});
