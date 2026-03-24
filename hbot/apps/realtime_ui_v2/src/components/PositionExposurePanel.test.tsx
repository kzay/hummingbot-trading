import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useDashboardStore } from "../store/useDashboardStore";
import { PositionExposurePanel } from "./PositionExposurePanel";

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

describe("PositionExposurePanel", () => {
  beforeEach(() => {
    resetStore();
  });

  function markConnected() {
    useDashboardStore.setState((prev) => ({
      connection: { ...prev.connection, lastMessageTsMs: Date.now() },
      source: "test",
    }));
  }

  it("renders without crash when position is null/undefined (default empty)", () => {
    markConnected();
    useDashboardStore.setState({
      position: {},
      market: {},
      depth: {},
    });

    render(<PositionExposurePanel />);

    expect(screen.getByText("Position")).toBeInTheDocument();
    expect(screen.getByText("flat")).toBeInTheDocument();
  });

  it("renders without crash with a valid position", () => {
    markConnected();
    useDashboardStore.setState({
      position: {
        quantity: 0.005,
        side: "long",
        avg_entry_price: 95_000,
        unrealized_pnl: 12.5,
      },
      market: { mid_price: 95_200 },
      depth: { best_bid: 95_199, best_ask: 95_201 },
      orders: [],
    });

    render(<PositionExposurePanel />);

    expect(screen.getByText("Position")).toBeInTheDocument();
    expect(screen.getByText("long")).toBeInTheDocument();
  });

  it("renders without crash when position has zero values", () => {
    markConnected();
    useDashboardStore.setState({
      position: {
        quantity: 0,
        side: "flat",
        avg_entry_price: 0,
        unrealized_pnl: 0,
      },
      market: { mid_price: 0 },
      depth: { best_bid: 0, best_ask: 0 },
      orders: [],
    });

    render(<PositionExposurePanel />);

    expect(screen.getByText("Position")).toBeInTheDocument();
    expect(screen.getByText("flat")).toBeInTheDocument();
  });
});
