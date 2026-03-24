import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardStore } from "../store/useDashboardStore";
import { InstancesPreviewStrip } from "./InstancesPreviewStrip";

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

function mockFetchWithInstances(statuses: Record<string, unknown>[]) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({ statuses }),
    status: 200,
    headers: new Headers(),
  } as Response);
}

describe("InstancesPreviewStrip", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  it("shows realized and unrealized when no open-equity delta exists", async () => {
    mockFetchWithInstances([
      {
        instance_name: "bot1",
        freshness: "live",
        trading_pair: "BTC-USDT",
        equity_quote: 1050,
        realized_pnl_quote: 42.5,
        unrealized_pnl_quote: -10.3,
      },
    ]);

    render(<InstancesPreviewStrip />);

    await screen.findByText("Realized");
    const realizedValue = await screen.findByText("+42.5");
    expect(realizedValue).toBeInTheDocument();

    const unrealizedValue = screen.getByText("-10.3");
    expect(unrealizedValue).toBeInTheDocument();
  });

  it("labels equity delta rows as vs open", async () => {
    mockFetchWithInstances([
      {
        instance_name: "bot1",
        freshness: "live",
        trading_pair: "BTC-USDT",
        equity_quote: 1050,
        equity_delta_open_quote: 12.5,
        unrealized_pnl_quote: -10.3,
      },
    ]);

    render(<InstancesPreviewStrip />);

    await screen.findByText("Vs Open");
    expect(await screen.findByText("+12.5")).toBeInTheDocument();
  });

  it("shows negative realized PnL with correct sign", async () => {
    mockFetchWithInstances([
      {
        instance_name: "bot1",
        freshness: "live",
        equity_quote: 950,
        realized_pnl_quote: -25.3,
        unrealized_pnl_quote: 0,
      },
    ]);

    render(<InstancesPreviewStrip />);

    const pnlValue = await screen.findByText("-25.3");
    expect(pnlValue).toBeInTheDocument();
  });

  it("shows n/a for unrealized when field is missing", async () => {
    mockFetchWithInstances([
      {
        instance_name: "bot1",
        freshness: "live",
        equity_quote: 1000,
        realized_pnl_quote: 5,
      },
    ]);

    render(<InstancesPreviewStrip />);

    await screen.findByText("bot1");
    const unrealizedLabel = screen.getByText("Unrealized");
    const wrapper = unrealizedLabel.parentElement!;
    const valueEl = wrapper.querySelector(".instance-preview-value");
    expect(valueEl?.textContent).toBe("n/a");
  });

  it("marks the active instance card", async () => {
    mockFetchWithInstances([
      { instance_name: "bot1", freshness: "live", equity_quote: 100, equity_delta_open_quote: 1 },
      { instance_name: "bot2", freshness: "live", equity_quote: 200, equity_delta_open_quote: 2 },
    ]);

    render(<InstancesPreviewStrip />);

    const bot1 = await screen.findByText("bot1");
    const card1 = bot1.closest("button");
    expect(card1?.className).toContain("active");

    const bot2 = screen.getByText("bot2");
    const card2 = bot2.closest("button");
    expect(card2?.className).not.toContain("active");
  });
});
