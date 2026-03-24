import { describe, expect, it } from "vitest";

import type { SummaryAccount, UiDepth, UiMarket, UiPosition } from "../types/realtime";

import { depthMid, currentMarkPrice, getLiveAccountMetrics, getDepthStats } from "./metrics";

function emptyMarket(overrides: Partial<UiMarket> = {}): UiMarket {
  return { mid_price: undefined, best_bid: undefined, best_ask: undefined, ...overrides };
}

function emptyDepth(overrides: Partial<UiDepth> = {}): UiDepth {
  return { best_bid: undefined, best_ask: undefined, bids: [], asks: [], ...overrides };
}

function emptyPosition(overrides: Partial<UiPosition> = {}): UiPosition {
  return { ...overrides };
}

function emptyAccount(overrides: Partial<SummaryAccount> = {}): SummaryAccount {
  return { ...overrides };
}

describe("depthMid", () => {
  it("returns midpoint from best_bid and best_ask", () => {
    expect(depthMid(emptyDepth({ best_bid: 100, best_ask: 102 }))).toBe(101);
  });

  it("falls back to first bid/ask price", () => {
    expect(
      depthMid(emptyDepth({ bids: [{ price: 50, size: 1 }], asks: [{ price: 52, size: 1 }] })),
    ).toBe(51);
  });

  it("returns bid only when ask missing", () => {
    expect(depthMid(emptyDepth({ best_bid: 100 }))).toBe(100);
  });

  it("returns ask only when bid missing", () => {
    expect(depthMid(emptyDepth({ best_ask: 102 }))).toBe(102);
  });

  it("returns null when empty", () => {
    expect(depthMid(emptyDepth())).toBeNull();
  });
});

describe("currentMarkPrice", () => {
  it("prefers market mid_price", () => {
    expect(currentMarkPrice(emptyMarket({ mid_price: 200 }), emptyDepth({ best_bid: 100, best_ask: 102 }), 150)).toBe(200);
  });

  it("falls back to latestMid", () => {
    expect(currentMarkPrice(emptyMarket(), emptyDepth(), 150)).toBe(150);
  });

  it("falls back to depthMid", () => {
    expect(currentMarkPrice(emptyMarket(), emptyDepth({ best_bid: 100, best_ask: 102 }), null)).toBe(101);
  });

  it("returns null when all sources empty", () => {
    expect(currentMarkPrice(emptyMarket(), emptyDepth(), null)).toBeNull();
  });
});

describe("getLiveAccountMetrics", () => {
  it("computes deltaVsOpenQuote when equity and open equity are available", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 1050, equity_open_quote: 1000, realized_pnl_quote: 0 }),
      emptyPosition(),
      emptyMarket({ mid_price: 100 }),
      emptyDepth(),
      null,
    );
    expect(result.deltaVsOpenQuote).toBe(50);
    expect(result.returnVsOpen).toBeCloseTo(0.05);
  });

  it("prefers realized plus unrealized for headline total PnL when components exist", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 999.96, equity_open_quote: 1000, realized_pnl_quote: 0.4598 }),
      emptyPosition({ quantity: 0.0031, avg_entry_price: 70469.9216, side: "long", unrealized_pnl: 0.3358 }),
      emptyMarket({ mid_price: 70578.25 }),
      emptyDepth(),
      null,
    );

    expect(result.unrealizedPnl).toBeCloseTo(0.3358, 4);
    expect(result.deltaVsOpenQuote).toBeCloseTo(-0.04, 2);
    expect(result.totalPnl).toBeCloseTo(0.7956, 4);
    expect(result.totalPnlSource).toBe("components");
  });

  it("computes unrealized PnL for long position", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 1000 }),
      emptyPosition({ quantity: 2, avg_entry_price: 90, side: "long" }),
      emptyMarket({ mid_price: 100 }),
      emptyDepth(),
      null,
    );
    expect(result.unrealizedPnl).toBe(20);
  });

  it("computes unrealized PnL for short position", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 1000 }),
      emptyPosition({ quantity: 2, avg_entry_price: 100, side: "short" }),
      emptyMarket({ mid_price: 90 }),
      emptyDepth(),
      null,
    );
    expect(result.unrealizedPnl).toBe(20);
  });

  it("returns null deltaVsOpen when equity_open_quote is missing", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 1000 }),
      emptyPosition(),
      emptyMarket(),
      emptyDepth(),
      null,
    );
    expect(result.deltaVsOpenQuote).toBeNull();
  });

  it("returns null returnVsOpen when equityOpenQuote is zero", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 100, equity_open_quote: 0 }),
      emptyPosition(),
      emptyMarket(),
      emptyDepth(),
      null,
    );
    expect(result.returnVsOpen).toBeNull();
  });

  it("falls back to realized plus unrealized when open equity is unavailable", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ realized_pnl_quote: 10 }),
      emptyPosition({ unrealized_pnl: -2 }),
      emptyMarket(),
      emptyDepth(),
      null,
    );

    expect(result.totalPnl).toBe(8);
    expect(result.totalPnlSource).toBe("components");
  });

  it("falls back to equity delta when realized and unrealized are unavailable", () => {
    const result = getLiveAccountMetrics(
      emptyAccount({ equity_quote: 1005, equity_open_quote: 1000 }),
      emptyPosition(),
      emptyMarket(),
      emptyDepth(),
      null,
    );

    expect(result.totalPnl).toBe(5);
    expect(result.totalPnlSource).toBe("equity_delta");
  });
});

describe("getDepthStats", () => {
  it("computes spread and spreadPct", () => {
    const stats = getDepthStats(emptyDepth({ best_bid: 100, best_ask: 100.02 }));
    expect(stats.spread).toBeCloseTo(0.02);
    expect(stats.spreadPct).toBeCloseTo(0.02, 2);
  });

  it("handles very small spread (BTC-level precision)", () => {
    const stats = getDepthStats(emptyDepth({ best_bid: 87000, best_ask: 87000.1 }));
    expect(stats.spread).toBeCloseTo(0.1);
    expect(stats.spreadPct).toBeGreaterThan(0);
    expect(stats.spreadPct).toBeLessThan(0.001);
  });

  it("computes bid/ask volume and imbalance", () => {
    const stats = getDepthStats(
      emptyDepth({
        best_bid: 100,
        best_ask: 101,
        bids: [
          { price: 100, size: 5 },
          { price: 99, size: 3 },
        ],
        asks: [{ price: 101, size: 2 }],
      }),
    );
    expect(stats.bidVolume).toBe(8);
    expect(stats.askVolume).toBe(2);
    expect(stats.imbalance).toBeCloseTo(0.6);
  });

  it("returns null spread when bid or ask missing", () => {
    const stats = getDepthStats(emptyDepth({ best_bid: 100 }));
    expect(stats.spread).toBeNull();
    expect(stats.spreadPct).toBeNull();
  });

  it("returns null imbalance when no volume", () => {
    const stats = getDepthStats(emptyDepth());
    expect(stats.imbalance).toBeNull();
    expect(stats.bidVolume).toBe(0);
    expect(stats.askVolume).toBe(0);
  });
});
