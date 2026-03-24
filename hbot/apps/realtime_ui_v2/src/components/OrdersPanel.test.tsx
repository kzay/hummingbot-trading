import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useDashboardStore } from "../store/useDashboardStore";
import { OrdersPanel } from "./OrdersPanel";

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

describe("OrdersPanel", () => {
  beforeEach(() => {
    resetStore();
  });

  function markConnected() {
    useDashboardStore.setState((prev) => ({
      connection: { ...prev.connection, lastMessageTsMs: Date.now() },
      source: "test",
    }));
  }

  it("renders without crash when orders array is empty", () => {
    markConnected();
    useDashboardStore.setState({ orders: [] });

    render(<OrdersPanel />);

    expect(screen.getByText("No orders")).toBeInTheDocument();
    expect(screen.getByText("Orders")).toBeInTheDocument();
  });

  it("renders without crash with 1 order", () => {
    markConnected();
    useDashboardStore.setState({
      orders: [
        {
          order_id: "ord-001",
          side: "buy",
          price: 95_000,
          amount: 0.01,
          state: "working",
        },
      ],
    });

    render(<OrdersPanel />);

    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.queryByText("No orders")).not.toBeInTheDocument();
  });

  it("renders without crash when order has null/undefined optional fields", () => {
    markConnected();
    useDashboardStore.setState({
      orders: [
        {
          order_id: undefined,
          client_order_id: undefined,
          side: undefined,
          price: null,
          amount: null,
          quantity: null,
          amount_base: null,
          state: undefined,
          is_estimated: undefined,
        },
      ],
    });

    render(<OrdersPanel />);

    expect(screen.getByText("Orders")).toBeInTheDocument();
    expect(screen.queryByText("No orders")).not.toBeInTheDocument();
  });
});
