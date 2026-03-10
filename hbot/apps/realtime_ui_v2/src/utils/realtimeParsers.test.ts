import { describe, expect, it } from "vitest";

import { parseInstancesPayload, parseRestStatePayload, parseWsInboundMessage } from "./realtimeParsers";

describe("realtime parsers", () => {
  it("rejects malformed websocket payloads", () => {
    expect(() => parseWsInboundMessage({ type: "event", event: 7 })).toThrow(/websocket payload invalid/i);
  });

  it("rejects malformed instance payloads", () => {
    expect(() => parseInstancesPayload({ statuses: "bad" })).toThrow(/instances payload invalid/i);
  });

  it("accepts rest state payloads with runtime orders using null amount fields", () => {
    const payload = parseRestStatePayload({
      mode: "active",
      source: "stream",
      key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
      stream: {
        market: {
          trading_pair: "BTC-USDT",
          mid_price: 70500,
          timestamp_ms: 1000,
        },
        depth: {
          trading_pair: "BTC-USDT",
          best_bid: 70499.9,
          best_ask: 70500.1,
          timestamp_ms: 1000,
        },
        open_orders: [
          {
            order_id: "runtime-BTC-USDT-buy-1",
            side: "buy",
            price: 70499.9,
            amount: null,
            quantity: null,
            amount_base: null,
            state: "runtime",
            trading_pair: "BTC-USDT",
            updated_ts_ms: 1000,
          },
        ],
        fills_total: 326,
      },
      summary: {
        system: {
          stream_age_ms: 250,
          latest_market_ts_ms: 1000,
          latest_fill_ts_ms: 900,
        },
      },
    });

    expect(payload.stream?.open_orders).toHaveLength(1);
    expect(payload.stream?.open_orders?.[0]?.amount).toBeNull();
    expect(payload.stream?.fills_total).toBe(326);
  });

  it("accepts instance payload rows with null stream age", () => {
    const payload = parseInstancesPayload({
      instances: ["shared"],
      statuses: [
        {
          instance_name: "shared",
          freshness: "artifact",
          stream_age_ms: null,
          trading_pair: "",
          quoting_status: "",
          realized_pnl_quote: 0,
          equity_quote: 0,
          source_label: "artifacts",
          controller_id: "",
          orders_active: 0,
        },
      ],
    });

    expect(payload.statuses).toHaveLength(1);
    expect(payload.statuses?.[0]?.stream_age_ms).toBeNull();
  });
});
