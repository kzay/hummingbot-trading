import { expect, test } from "@playwright/test";

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_CANDIDATES = {
  candidates: [
    {
      name: "atr_mm_v1",
      hypothesis: "ATR-based spread widens in high-volatility regimes to capture mean reversion.",
      adapter_mode: "atr_mm",
      lifecycle: "paper",
      best_score: 0.72,
      best_recommendation: "pass",
      experiment_count: 3,
    },
    {
      name: "pullback_v2",
      hypothesis: "Pullback entries after impulse moves with momentum confirmation.",
      adapter_mode: "pullback",
      lifecycle: "revise",
      best_score: 0.48,
      best_recommendation: "revise",
      experiment_count: 1,
    },
    {
      name: "smc_breakout_v1",
      hypothesis: "Smart money concept breakout above order blocks.",
      adapter_mode: "smc_mm",
      lifecycle: "candidate",
      best_score: null,
      best_recommendation: null,
      experiment_count: 0,
    },
  ],
};

const MOCK_CANDIDATE_DETAIL = {
  name: "atr_mm_v1",
  hypothesis: "ATR-based spread widens in high-volatility regimes to capture mean reversion.",
  adapter_mode: "atr_mm",
  entry_logic: "Enter when ATR > threshold and price is at band edge.",
  exit_logic: "Exit at mid-band or stop-loss at 2×ATR.",
  parameter_space: { atr_period: [14, 21], multiplier: [1.5, 2.5] },
  base_config: { trading_pair: "BTC-USDT", leverage: 1 },
  required_tests: ["oos_robustness", "fee_sensitivity"],
  metadata: { created_at: "2026-03-01T10:00:00Z", author: "llm-explorer" },
  lifecycle: {
    candidate_name: "atr_mm_v1",
    current_state: "paper",
    history: [
      {
        from_state: "candidate",
        to_state: "paper",
        timestamp: "2026-03-10T12:00:00Z",
        reason: "passed robustness",
      },
    ],
  },
  experiments: [
    {
      run_id: "run-001",
      candidate_name: "atr_mm_v1",
      timestamp: "2026-03-10T11:00:00Z",
      robustness_score: 0.72,
      recommendation: "pass",
      config_snapshot: {},
    },
  ],
  best_score: 0.72,
  best_recommendation: "pass",
  latest_report_path: "reports/atr_mm_v1/run-001.md",
};

const MOCK_EXPLORATIONS = {
  explorations: [
    {
      session_id: "session-abc123",
      status: "completed",
      iteration_count: 5,
      best_score: 0.68,
      best_candidate: "atr_mm_v2",
      created_at: "2026-03-20T09:00:00Z",
    },
    {
      session_id: "session-def456",
      status: "running",
      iteration_count: 2,
      best_score: null,
      best_candidate: "",
      created_at: "2026-03-23T08:00:00Z",
    },
  ],
};

// ── Setup helpers ─────────────────────────────────────────────────────────────

/** Mock the WebSocket so the app initialises without a real API */
async function addWsMock(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    class FakeWebSocket {
      url: string;
      readyState = 0;
      onopen: ((e: Event) => void) | null = null;
      onmessage: ((e: MessageEvent<string>) => void) | null = null;
      onerror: ((e: Event) => void) | null = null;
      onclose: ((e: CloseEvent) => void) | null = null;

      constructor(url: string) {
        this.url = url;
        window.setTimeout(() => {
          this.readyState = 1;
          this.onopen?.(new Event("open"));
        }, 0);
      }

      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }
      send() {}
    }
    Object.defineProperty(window, "WebSocket", {
      configurable: true,
      writable: true,
      value: FakeWebSocket,
    });
  });
}

async function mockBaseRoutes(page: import("@playwright/test").Page) {
  await page.route("**/health", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        mode: "shadow",
        redis_available: true,
        db_enabled: true,
        db_available: true,
        stream_age_ms: 250,
        fallback_active: false,
        metrics: { subscribers: 0, market_keys: 0, market_quote_keys: 0, market_depth_keys: 0, fills_keys: 0, paper_event_keys: 0, subscriber_drops: 0 },
      },
    }),
  );
  await page.route("**/api/v1/instances", (route) =>
    route.fulfill({ json: { instances: [], statuses: [] } }),
  );
}

async function mockResearchRoutes(page: import("@playwright/test").Page) {
  await page.route("**/api/research/candidates", (route) =>
    route.fulfill({ json: MOCK_CANDIDATES }),
  );
  await page.route("**/api/research/candidates/atr_mm_v1", (route) =>
    route.fulfill({ json: MOCK_CANDIDATE_DETAIL }),
  );
  await page.route("**/api/research/explorations", (route) =>
    route.fulfill({ json: MOCK_EXPLORATIONS }),
  );
  await page.route("**/api/research/explorations/**", (route) =>
    route.fulfill({
      json: {
        session_id: "session-abc123",
        status: "completed",
        iterations: [
          { iteration: 1, candidate_name: "atr_mm_v2", score: 0.55, recommendation: "revise", file: "iter-001.yaml" },
          { iteration: 2, candidate_name: "atr_mm_v2_b", score: 0.68, recommendation: "pass", file: "iter-002.yaml" },
        ],
        best_score: 0.68,
        best_candidate: "atr_mm_v2_b",
      },
    }),
  );
}

/** Navigate to the Research view via the sidebar button */
async function goToResearch(page: import("@playwright/test").Page) {
  await page.goto("/");
  // Wait for the sidebar to appear, then click Research
  const researchBtn = page.locator(".sidebar-nav-item", { hasText: "Research" });
  await expect(researchBtn).toBeVisible({ timeout: 10_000 });
  await researchBtn.click();
  // The Panel heading is an <h2> with role="heading"
  await expect(
    page.getByRole("heading", { name: "Strategy Scoreboard" }),
  ).toBeVisible({ timeout: 10_000 });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Research Page", () => {
  test.beforeEach(async ({ page }) => {
    await addWsMock(page);
    await mockBaseRoutes(page);
    await mockResearchRoutes(page);
  });

  // ── 1. Navigation ─────────────────────────────────────────────────────────

  test("sidebar shows Research button and clicking it opens the page", async ({ page }) => {
    await page.goto("/");

    const researchBtn = page.locator(".sidebar-nav-item", { hasText: "Research" });
    await expect(researchBtn).toBeVisible();

    await researchBtn.click();
    await expect(page.getByRole("heading", { name: "Strategy Scoreboard" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Exploration Sessions" })).toBeVisible();
  });

  test("keyboard shortcut 8 switches to Research view", async ({ page }) => {
    await page.goto("/");
    // Ensure focus is on the document body before sending key
    await page.locator("body").press("8");
    await expect(page.getByRole("heading", { name: "Strategy Scoreboard" })).toBeVisible({
      timeout: 10_000,
    });
  });

  // ── 2. Scoreboard ─────────────────────────────────────────────────────────

  test("scoreboard renders all three candidate rows", async ({ page }) => {
    await goToResearch(page);

    // Candidate names appear as table cells
    await expect(page.getByText("atr_mm_v1")).toBeVisible();
    await expect(page.getByText("pullback_v2")).toBeVisible();
    await expect(page.getByText("smc_breakout_v1")).toBeVisible();
  });

  test("lifecycle and recommendation badges render", async ({ page }) => {
    await goToResearch(page);

    // Lifecycle state badges
    const paperBadges = page.locator(".rs-badge", { hasText: "paper" });
    const reviseBadges = page.locator(".rs-badge", { hasText: "revise" });
    await expect(paperBadges.first()).toBeVisible();
    await expect(reviseBadges.first()).toBeVisible();

    // Recommendation badge
    const passBadge = page.locator(".rs-badge", { hasText: "pass" });
    await expect(passBadge.first()).toBeVisible();
  });

  test("score bars render for candidates with scores", async ({ page }) => {
    await goToResearch(page);
    // atr_mm_v1 has score 0.72 → score fill div should be present
    const scoreFills = page.locator(".rs-score-fill");
    await expect(scoreFills.first()).toBeVisible();
  });

  // ── 3. Candidate detail view ──────────────────────────────────────────────

  test("clicking a candidate row opens the detail view", async ({ page }) => {
    await goToResearch(page);

    // Click the atr_mm_v1 row (click on the table row via the name cell text)
    await page.getByText("atr_mm_v1").first().click();

    // Detail heading h3 should appear (exact: true avoids matching the Panel <h2> "Research › atr_mm_v1")
    await expect(page.getByRole("heading", { name: "atr_mm_v1", exact: true })).toBeVisible();

    // Lifecycle history shows the transition
    await expect(page.getByText("candidate")).toBeVisible();
    await expect(page.getByText("passed robustness")).toBeVisible();

    // Experiment row
    await expect(page.getByText("run-001")).toBeVisible();
  });

  test("back button from detail view returns to scoreboard", async ({ page }) => {
    await goToResearch(page);
    await page.getByText("atr_mm_v1").first().click();
    await expect(page.getByRole("heading", { name: "atr_mm_v1", exact: true })).toBeVisible();

    // Click the ← Back button
    await page.locator(".rs-back-btn").click();
    await expect(page.getByRole("heading", { name: "Strategy Scoreboard" })).toBeVisible();
  });

  // ── 4. Exploration sessions ───────────────────────────────────────────────

  test("exploration sessions panel renders both sessions", async ({ page }) => {
    await goToResearch(page);

    // session IDs are truncated to 12 chars in the table
    await expect(page.getByText("session-abc1")).toBeVisible();
    await expect(page.getByText("session-def4")).toBeVisible();

    // Status badges
    await expect(page.locator(".rs-badge", { hasText: "completed" }).first()).toBeVisible();
    await expect(page.locator(".rs-badge", { hasText: "running" }).first()).toBeVisible();
  });

  test("clicking exploration row opens exploration detail view", async ({ page }) => {
    await goToResearch(page);

    // Click the session-abc123 row (truncated to 12 chars in the table: "session-abc1")
    await page.getByText("session-abc1").first().click();

    // Exploration detail: Panel title is "Exploration › session-abc1" and h3 says "Exploration Session"
    await expect(page.getByRole("heading", { name: "Exploration Session", exact: true })).toBeVisible();

    // The Back button is present
    await expect(page.locator(".rs-back-btn")).toBeVisible();
  });

  // ── 5. Refresh ────────────────────────────────────────────────────────────

  test("Refresh button re-fetches candidates", async ({ page }) => {
    let fetchCount = 0;
    await page.route("**/api/research/candidates", (route) => {
      fetchCount++;
      return route.fulfill({ json: MOCK_CANDIDATES });
    });

    await goToResearch(page);
    const countBefore = fetchCount;

    await page.getByRole("button", { name: /Refresh|Loading/i }).click();
    // Give a moment for the fetch to fire
    await page.waitForTimeout(300);
    expect(fetchCount).toBeGreaterThan(countBefore);
  });
});
