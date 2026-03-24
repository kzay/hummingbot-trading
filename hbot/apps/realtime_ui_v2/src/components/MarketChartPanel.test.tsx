import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardStore } from "../store/useDashboardStore";

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "CandlestickSeries",
  ColorType: { Solid: "Solid" },
  LineStyle: { Dashed: 1, Solid: 0 },
  createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
      update: vi.fn(),
      createPriceLine: vi.fn(() => ({})),
      removePriceLine: vi.fn(),
    })),
    subscribeCrosshairMove: vi.fn(),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  })),
}));

import { MarketChartPanel } from "./MarketChartPanel";

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

describe("MarketChartPanel", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  it("renders without crash when candles array is empty", () => {
    useDashboardStore.setState({
      candles: [],
      latestCandle: null,
      fills: [],
      orders: [],
      position: {},
      market: {},
      depth: {},
    });

    render(<MarketChartPanel />);

    expect(screen.getByText("Price Chart")).toBeInTheDocument();
    expect(screen.getByText("0 candles")).toBeInTheDocument();
  });

  it("renders without crash when market data is null/undefined", () => {
    useDashboardStore.setState({
      candles: [],
      latestCandle: null,
      fills: [],
      orders: [],
      position: {},
      market: { mid_price: undefined, best_bid: undefined, best_ask: undefined },
      depth: { best_bid: undefined, best_ask: undefined, bids: [], asks: [] },
    });

    render(<MarketChartPanel />);

    expect(screen.getByText("Price Chart")).toBeInTheDocument();
  });
});
