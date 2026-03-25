import { expect, test } from "@playwright/test";

function buildState(instanceName: string) {
  return {
    mode: "shadow",
    source: "stream",
    summary: {
      system: {
        fallback_active: false,
        stream_age_ms: 250,
        latest_market_ts_ms: 2_000,
        latest_fill_ts_ms: 2_200,
        position_source_ts_ms: 2_000,
      },
      account: {
        controller_state: "running",
        regime: "range",
        realized_pnl_quote: instanceName === "bot2" ? 15.25 : 8.5,
        quoting_status: "live",
        risk_reasons: "",
        orders_active: 2,
      },
      activity: {
        fills_total: 1,
        latest_fill_ts_ms: 2_200,
        realized_pnl_total_quote: instanceName === "bot2" ? 15.25 : 8.5,
      },
      alerts: [],
    },
    stream: {
      market: {
        trading_pair: "BTC-USDT",
        mid_price: instanceName === "bot2" ? 102 : 101,
        best_bid: instanceName === "bot2" ? 101.5 : 100.5,
        best_ask: instanceName === "bot2" ? 102.5 : 101.5,
        timestamp_ms: 2_000,
      },
      depth: {
        trading_pair: "BTC-USDT",
        best_bid: instanceName === "bot2" ? 101.5 : 100.5,
        best_ask: instanceName === "bot2" ? 102.5 : 101.5,
        timestamp_ms: 2_000,
        bids: [{ price: instanceName === "bot2" ? 101.5 : 100.5, size: 1 }],
        asks: [{ price: instanceName === "bot2" ? 102.5 : 101.5, size: 1 }],
      },
      position: {
        trading_pair: "BTC-USDT",
        quantity: instanceName === "bot2" ? 0.2 : 0.1,
        side: "long",
        avg_entry_price: instanceName === "bot2" ? 100 : 99,
        unrealized_pnl: instanceName === "bot2" ? 1.75 : 0.8,
        source_ts_ms: 2_000,
      },
      open_orders: [
        {
          order_id: `${instanceName}-order-1`,
          side: "buy",
          price: instanceName === "bot2" ? 101 : 100,
          amount_base: 0.1,
          state: "open",
          trading_pair: "BTC-USDT",
          updated_ts_ms: 2_000,
        },
      ],
      fills: [
        {
          order_id: `${instanceName}-fill-1`,
          timestamp_ms: 2_200,
          side: "buy",
          price: instanceName === "bot2" ? 102 : 101,
          amount_base: 0.1,
          notional_quote: instanceName === "bot2" ? 10.2 : 10.1,
          fee_quote: 0.01,
          realized_pnl_quote: instanceName === "bot2" ? 15.25 : 8.5,
          is_maker: true,
        },
      ],
      fills_total: 1,
      key: {
        instance_name: instanceName,
        controller_id: `controller-${instanceName}`,
        trading_pair: "BTC-USDT",
      },
    },
    fallback: {
      minute: {
        mid: instanceName === "bot2" ? 102 : 101,
      },
    },
  };
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    class FakeWebSocket {
      url: string;
      readyState = 0;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;

      constructor(url: string) {
        this.url = url;
        window.setTimeout(() => {
          this.readyState = 1;
          this.onopen?.(new Event("open"));
          const instanceName = new URL(url).searchParams.get("instance_name") || "bot1";
          const payload = {
            type: "snapshot",
            ts_ms: 2_000,
            instance_name: instanceName,
            trading_pair: "BTC-USDT",
            state: (window as Window & { __hbBuildState?: (instanceName: string) => unknown }).__hbBuildState?.(instanceName),
            candles: [
              { bucket_ms: 1_000, open: 100, high: 101, low: 99, close: 100.5 },
              { bucket_ms: 2_000, open: 100.5, high: 102, low: 100, close: instanceName === "bot2" ? 102 : 101 },
            ],
          };
          this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
        }, 0);
      }

      close() {
        this.readyState = 3;
        this.onclose?.(new CloseEvent("close"));
      }

      send() {}
    }

    (window as Window & { __hbBuildState?: (instanceName: string) => unknown }).__hbBuildState = (instanceName: string) => ({
      mode: "shadow",
      source: "stream",
      summary: {
        system: {
          fallback_active: false,
          stream_age_ms: 250,
          latest_market_ts_ms: 2_000,
          latest_fill_ts_ms: 2_200,
          position_source_ts_ms: 2_000,
        },
        account: {
          controller_state: "running",
          regime: "range",
          realized_pnl_quote: instanceName === "bot2" ? 15.25 : 8.5,
          quoting_status: "live",
          risk_reasons: "",
          orders_active: 2,
        },
        activity: {
          fills_total: 1,
          latest_fill_ts_ms: 2_200,
          realized_pnl_total_quote: instanceName === "bot2" ? 15.25 : 8.5,
        },
        alerts: [],
      },
      stream: {
        market: {
          trading_pair: "BTC-USDT",
          mid_price: instanceName === "bot2" ? 102 : 101,
          best_bid: instanceName === "bot2" ? 101.5 : 100.5,
          best_ask: instanceName === "bot2" ? 102.5 : 101.5,
          timestamp_ms: 2_000,
        },
        depth: {
          trading_pair: "BTC-USDT",
          best_bid: instanceName === "bot2" ? 101.5 : 100.5,
          best_ask: instanceName === "bot2" ? 102.5 : 101.5,
          timestamp_ms: 2_000,
          bids: [{ price: instanceName === "bot2" ? 101.5 : 100.5, size: 1 }],
          asks: [{ price: instanceName === "bot2" ? 102.5 : 101.5, size: 1 }],
        },
        position: {
          trading_pair: "BTC-USDT",
          quantity: instanceName === "bot2" ? 0.2 : 0.1,
          side: "long",
          avg_entry_price: instanceName === "bot2" ? 100 : 99,
          unrealized_pnl: instanceName === "bot2" ? 1.75 : 0.8,
          source_ts_ms: 2_000,
        },
        open_orders: [
          {
            order_id: `${instanceName}-order-1`,
            side: "buy",
            price: instanceName === "bot2" ? 101 : 100,
            amount_base: 0.1,
            state: "open",
            trading_pair: "BTC-USDT",
            updated_ts_ms: 2_000,
          },
        ],
        fills: [
          {
            order_id: `${instanceName}-fill-1`,
            timestamp_ms: 2_200,
            side: "buy",
            price: instanceName === "bot2" ? 102 : 101,
            amount_base: 0.1,
            notional_quote: instanceName === "bot2" ? 10.2 : 10.1,
            fee_quote: 0.01,
            realized_pnl_quote: instanceName === "bot2" ? 15.25 : 8.5,
            is_maker: true,
          },
        ],
        fills_total: 1,
        key: {
          instance_name: instanceName,
          controller_id: `controller-${instanceName}`,
          trading_pair: "BTC-USDT",
        },
      },
      fallback: {
        minute: {
          mid: instanceName === "bot2" ? 102 : 101,
        },
      },
    });

    Object.defineProperty(window, "WebSocket", {
      configurable: true,
      writable: true,
      value: FakeWebSocket,
    });
  });

  await page.route("**/health", async (route) => {
    await route.fulfill({
      json: {
        status: "ok",
        mode: "shadow",
        redis_available: true,
        db_enabled: true,
        db_available: true,
        stream_age_ms: 250,
        fallback_active: false,
        metrics: {
          subscribers: 1,
          market_keys: 1,
          market_quote_keys: 1,
          market_depth_keys: 1,
          fills_keys: 1,
          paper_event_keys: 1,
          subscriber_drops: 0,
        },
      },
    });
  });

  await page.route("**/api/v1/instances", async (route) => {
    await route.fulfill({
      json: {
        instances: ["bot1", "bot2"],
        statuses: [
          {
            instance_name: "bot1",
            freshness: "live",
            stream_age_ms: 250,
            trading_pair: "BTC-USDT",
            quoting_status: "live",
            realized_pnl_quote: 8.5,
            equity_quote: 1008.5,
            source_label: "stream",
            controller_id: "controller-bot1",
            orders_active: 1,
          },
          {
            instance_name: "bot2",
            freshness: "live",
            stream_age_ms: 250,
            trading_pair: "BTC-USDT",
            quoting_status: "live",
            realized_pnl_quote: 15.25,
            equity_quote: 1015.25,
            source_label: "stream",
            controller_id: "controller-bot2",
            orders_active: 1,
          },
        ],
      },
    });
  });

  await page.route("**/api/v1/state?*", async (route) => {
    const url = new URL(route.request().url());
    const instanceName = url.searchParams.get("instance_name") || "bot1";
    await route.fulfill({
      json: buildState(instanceName),
    });
  });
});

test("loads the operator shell, checks service health, and switches instances", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Kzay Capital")).toBeVisible();
  await expect(page.getByText("API status")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Price Chart" })).toBeVisible();

  await page.getByRole("button", { name: "Service Monitor" }).click();
  await expect(page.getByRole("heading", { name: "Live Data Service" })).toBeVisible();

  await page.keyboard.press("1");
  await expect(page.getByRole("heading", { name: "Price Chart" })).toBeVisible();
  await page.locator(".instance-preview-card").nth(1).evaluate((element) => {
    (element as HTMLButtonElement).click();
  });

  await expect(page.locator('.instance-preview-card.active').getByText('bot2')).toBeVisible();
  await expect(page.getByRole("heading", { name: "Price Chart" })).toBeVisible();
});
