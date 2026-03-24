import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useDashboardStore } from "../store/useDashboardStore";
import { FillsPanel } from "./FillsPanel";

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

describe("FillsPanel", () => {
  beforeEach(() => {
    resetStore();
  });

  function markConnected() {
    useDashboardStore.setState((prev) => ({
      connection: { ...prev.connection, lastMessageTsMs: Date.now() },
      source: "test",
    }));
  }

  it("renders without crash when fills array is empty", () => {
    markConnected();
    useDashboardStore.setState({ fills: [], fillsTotal: 0 });

    render(<FillsPanel />);

    expect(screen.getByText("No fills")).toBeInTheDocument();
    expect(screen.getByText("24h Fills")).toBeInTheDocument();
  });

  it("renders without crash with 1 fill", () => {
    markConnected();
    useDashboardStore.setState({
      fills: [
        {
          order_id: "fill-001",
          timestamp_ms: 1_700_000_000_000,
          side: "buy",
          price: 95_000,
          amount_base: 0.001,
          notional_quote: 95,
          fee_quote: 0.05,
          realized_pnl_quote: 1.25,
          is_maker: true,
        },
      ],
      fillsTotal: 1,
    });

    render(<FillsPanel />);

    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.queryByText("No fills")).not.toBeInTheDocument();
  });

  it("renders without crash when fill has null/undefined optional fields", () => {
    markConnected();
    useDashboardStore.setState({
      fills: [
        {
          order_id: undefined,
          timestamp_ms: undefined,
          side: undefined,
          price: undefined,
          amount_base: undefined,
          notional_quote: undefined,
          fee_quote: undefined,
          realized_pnl_quote: undefined,
          is_maker: undefined,
        },
      ],
      fillsTotal: 1,
    });

    render(<FillsPanel />);

    expect(screen.getByText("24h Fills")).toBeInTheDocument();
    expect(screen.queryByText("No fills")).not.toBeInTheDocument();
  });
});
