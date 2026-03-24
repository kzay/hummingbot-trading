import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardStore } from "../store/useDashboardStore";
import { TopBar } from "./TopBar";

vi.mock("./InstancesPreviewStrip", () => ({
  InstancesPreviewStrip: () => <div>Instances preview</div>,
}));

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

describe("TopBar", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  it("stores API tokens in session storage only after apply", async () => {
    render(<TopBar activeView="realtime" onActiveViewChange={vi.fn()} />);
    fireEvent.click(screen.getByText("Connection settings"));
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "session-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply connection settings" }));

    expect(sessionStorage.getItem("hbV2ApiToken")).toBe("session-secret");
    expect(localStorage.getItem("hbV2ApiToken")).toBeNull();
    expect(screen.getByText(/session-only/i)).toBeInTheDocument();
  });

  it("prefers health stream age over summary age", () => {
    const store = useDashboardStore.getState();
    store.setHealth({ status: "ok", streamAgeMs: 2_000 });
    store.ingestRestState(
      {
        key: { instance_name: "bot1", trading_pair: "BTC-USDT" },
        summary: {
          system: {
            stream_age_ms: 1_000,
          },
        },
      },
      "bot1",
    );

    render(<TopBar activeView="realtime" onActiveViewChange={vi.fn()} />);

    expect(screen.getByText("Age 2.0 s")).toBeInTheDocument();
  });

  it("hides websocket reconnect banner in rest-only token mode", () => {
    const store = useDashboardStore.getState();
    store.updateSettings({ apiToken: "session-secret" });
    store.setConnectionStatus("closed");

    render(<TopBar activeView="realtime" onActiveViewChange={vi.fn()} />);

    expect(screen.queryByText(/Connection lost/i)).not.toBeInTheDocument();
  });
});
