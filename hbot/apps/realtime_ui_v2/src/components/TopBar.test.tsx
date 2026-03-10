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
    fireEvent.click(screen.getByRole("button", { name: "Apply connection" }));

    expect(sessionStorage.getItem("hbV2ApiToken")).toBe("session-secret");
    expect(localStorage.getItem("hbV2ApiToken")).toBeNull();
    expect(screen.getByText(/session-only/i)).toBeInTheDocument();
  });
});
