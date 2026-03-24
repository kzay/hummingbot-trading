import { describe, expect, it } from "vitest";

import type { UiMarket } from "../types/realtime";

import { candlePrice, pushCandleTick } from "./useDashboardStore";

describe("candlePrice", () => {
  it("prefers last_trade_price over mid_price", () => {
    const market: UiMarket = { last_trade_price: 87_500, mid_price: 87_450 };
    expect(candlePrice(market)).toBe(87_500);
  });

  it("falls back to mid_price when last_trade_price is missing", () => {
    const market: UiMarket = { mid_price: 87_450 };
    expect(candlePrice(market)).toBe(87_450);
  });

  it("falls back to mid_price when last_trade_price is null", () => {
    const market: UiMarket = { last_trade_price: null as unknown as number, mid_price: 87_450 };
    expect(candlePrice(market)).toBe(87_450);
  });

  it("returns null when both resolve to zero", () => {
    const market: UiMarket = { last_trade_price: 0, mid_price: 0 };
    expect(candlePrice(market)).toBeNull();
  });

  it("handles string values", () => {
    const market: UiMarket = { last_trade_price: "87500.5" };
    expect(candlePrice(market)).toBe(87_500.5);
  });

  it("returns null when both are missing", () => {
    expect(candlePrice({})).toBeNull();
  });

  it("returns null when both are non-numeric", () => {
    const market: UiMarket = { last_trade_price: "abc" as unknown as number, mid_price: "xyz" as unknown as number };
    expect(candlePrice(market)).toBeNull();
  });
});

describe("pushCandleTick (trade-price candle builder)", () => {
  const tf = 60;

  it("creates first candle from empty state", () => {
    const result = pushCandleTick([], null, 60_000, 100, tf);
    expect(result.candles).toHaveLength(1);
    expect(result.latestCandle).toBeTruthy();
    expect(result.latestCandle!.open).toBe(100);
    expect(result.latestCandle!.close).toBe(100);
  });

  it("updates existing candle in the same bucket", () => {
    const first = pushCandleTick([], null, 60_000, 100, tf);
    const second = pushCandleTick(first.candles, first.latestCandle, 65_000, 105, tf);
    expect(second.latestCandle!.open).toBe(100);
    expect(second.latestCandle!.close).toBe(105);
    expect(second.latestCandle!.high).toBe(105);
    expect(second.latestCandle!.low).toBe(100);
  });

  it("tracks high/low correctly through multiple updates", () => {
    let state = pushCandleTick([], null, 60_000, 100, tf);
    state = pushCandleTick(state.candles, state.latestCandle, 61_000, 110, tf);
    state = pushCandleTick(state.candles, state.latestCandle, 62_000, 95, tf);
    state = pushCandleTick(state.candles, state.latestCandle, 63_000, 102, tf);
    expect(state.latestCandle!.open).toBe(100);
    expect(state.latestCandle!.high).toBe(110);
    expect(state.latestCandle!.low).toBe(95);
    expect(state.latestCandle!.close).toBe(102);
  });

  it("creates a new candle when bucket changes", () => {
    const first = pushCandleTick([], null, 60_000, 100, tf);
    const second = pushCandleTick(first.candles, first.latestCandle, 120_000, 105, tf);
    expect(second.candles.length).toBeGreaterThanOrEqual(1);
    expect(second.latestCandle!.open).toBe(100);
    expect(second.latestCandle!.close).toBe(105);
    expect(second.latestCandle!.time).toBeGreaterThan(first.latestCandle!.time);
  });

  it("ignores zero price", () => {
    const result = pushCandleTick([], null, 60_000, 0, tf);
    expect(result.candles).toHaveLength(0);
    expect(result.latestCandle).toBeNull();
  });

  it("ignores NaN price", () => {
    const result = pushCandleTick([], null, 60_000, NaN, tf);
    expect(result.candles).toHaveLength(0);
    expect(result.latestCandle).toBeNull();
  });

  it("ignores Infinity price", () => {
    const result = pushCandleTick([], null, 60_000, Infinity, tf);
    expect(result.candles).toHaveLength(0);
    expect(result.latestCandle).toBeNull();
  });

  it("ignores older timestamp than current bucket", () => {
    const first = pushCandleTick([], null, 120_000, 100, tf);
    const second = pushCandleTick(first.candles, first.latestCandle, 60_000, 90, tf);
    expect(second.latestCandle!.close).toBe(100);
  });

  it("recovers from prior candle with zero close (no spike to 0)", () => {
    const badCandle = { time: 60, open: 0, high: 0, low: 0, close: 0 };
    const result = pushCandleTick([badCandle], badCandle, 120_000, 70_000, tf);
    expect(result.latestCandle!.open).toBe(70_000);
    expect(result.latestCandle!.high).toBe(70_000);
    expect(result.latestCandle!.low).toBe(70_000);
    expect(result.latestCandle!.close).toBe(70_000);
  });

  it("same-bucket update with zero OHLC uses valid price", () => {
    const badCandle = { time: 60, open: 0, high: 0, low: 0, close: 0 };
    const result = pushCandleTick([], badCandle, 60_000, 70_000, tf);
    expect(result.latestCandle!.open).toBe(70_000);
    expect(result.latestCandle!.low).toBe(70_000);
    expect(result.latestCandle!.high).toBe(70_000);
    expect(result.latestCandle!.close).toBe(70_000);
  });
});
