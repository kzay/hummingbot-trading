import { describe, expect, it } from "vitest";

import type { WsEventMessage } from "../types/realtime";
import { buildHeaders, fetchWithTimeout } from "../utils/fetch";
import { parseWsInboundMessage } from "../utils/realtimeParsers";
import { WS_PENDING_MESSAGES_CAP } from "../constants";

describe("buildHeaders", () => {
  it("returns Content-Type without token", () => {
    const headers = buildHeaders("");
    expect(headers).toEqual({ "Content-Type": "application/json" });
  });

  it("includes Authorization with a token", () => {
    const headers = buildHeaders("my-token");
    expect(headers).toEqual({
      "Content-Type": "application/json",
      Authorization: "Bearer my-token",
    });
  });

  it("trims whitespace from token", () => {
    const headers = buildHeaders("  tok  ");
    expect(headers).toEqual({
      "Content-Type": "application/json",
      Authorization: "Bearer tok",
    });
  });
});

describe("parseWsInboundMessage fast-path", () => {
  it("parses a market_quote event without Zod", () => {
    const raw = {
      type: "event",
      event_type: "market_quote",
      ts_ms: 1710000000000,
      event: { mid_price: "50000.5", best_bid: "50000", best_ask: "50001" },
    };
    const result = parseWsInboundMessage(raw);
    expect(result.type).toBe("event");
    expect((result as WsEventMessage).event_type).toBe("market_quote");
  });

  it("parses a market_depth_snapshot event without Zod", () => {
    const raw = {
      type: "event",
      event_type: "market_depth_snapshot",
      ts_ms: 1710000000000,
      event: { bids: [], asks: [] },
    };
    const result = parseWsInboundMessage(raw);
    expect(result.type).toBe("event");
  });

  it("falls back to Zod for snapshot messages", () => {
    const raw = {
      type: "snapshot",
      ts_ms: 1710000000000,
      instance_name: "bot_a",
    };
    const result = parseWsInboundMessage(raw);
    expect(result.type).toBe("snapshot");
  });

  it("falls back to Zod for keepalive messages", () => {
    const raw = { type: "keepalive", ts_ms: 1710000000000 };
    const result = parseWsInboundMessage(raw);
    expect(result.type).toBe("keepalive");
  });

  it("falls back to Zod for non-fast-path event types", () => {
    const raw = {
      type: "event",
      event_type: "fill",
      ts_ms: 1710000000000,
      event: { order_id: "abc" },
    };
    const result = parseWsInboundMessage(raw);
    expect(result.type).toBe("event");
  });
});

describe("WS_PENDING_MESSAGES_CAP constant", () => {
  it("is set to 500", () => {
    expect(WS_PENDING_MESSAGES_CAP).toBe(500);
  });
});

describe("fetchWithTimeout", () => {
  it("rejects on timeout", async () => {
    globalThis.fetch = (_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason));
      });

    await expect(
      fetchWithTimeout("http://localhost:9999/test", { timeoutMs: 50 }),
    ).rejects.toThrow();
  });
});
