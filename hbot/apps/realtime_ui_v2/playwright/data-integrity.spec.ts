import { expect, test } from "@playwright/test";

/**
 * Live dashboard data-integrity test.
 * Scrapes displayed values from the UI and compares against the internal API.
 *
 * Run with:
 *   PLAYWRIGHT_EXTERNAL_SERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:8088 \
 *     npx playwright test playwright/data-integrity.spec.ts --headed
 */

const apiBase =
  (process.env.PLAYWRIGHT_API_BASE || "").trim() || "http://127.0.0.1:9910";

const BOTS_TO_CHECK = ["bot1", "bot2", "bot3", "bot7"];

/* ── helpers ─────────────────────────────────────────────────────────── */

function parseLocaleNumber(s: string): number {
  const cleaned = s
    .replace(/[+\s]/g, "")
    .replace(/,/g, "")
    .replace(/[×x%]/g, "")
    .replace(/~/g, "")
    .trim();
  if (cleaned === "n/a" || cleaned === "—" || cleaned === "") return NaN;
  return Number(cleaned);
}

function approxEqual(
  a: number,
  b: number,
  label: string,
  tolerancePct = 2,
  toleranceAbs = 0.02,
): string | null {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (a === 0 && b === 0) return null;
  const diff = Math.abs(a - b);
  const base = Math.max(Math.abs(a), Math.abs(b), 1e-12);
  const pctDiff = (diff / base) * 100;
  if (diff <= toleranceAbs) return null;
  if (pctDiff <= tolerancePct) return null;
  return `${label}: UI=${a} vs API=${b} (diff=${diff.toFixed(6)}, ${pctDiff.toFixed(2)}%)`;
}

async function scrapeKvPanel(
  panel: import("@playwright/test").Locator,
): Promise<Record<string, string>> {
  const result: Record<string, string> = {};
  const cards = panel.locator(".kv-card");
  const count = await cards.count();
  for (let i = 0; i < count; i++) {
    const label = (await cards.nth(i).locator(".kv-label").textContent()) ?? "";
    const value = (await cards.nth(i).locator(".kv-value").textContent()) ?? "";
    result[label.trim()] = value.trim();
  }
  return result;
}

async function scrapeDlCard(
  card: import("@playwright/test").Locator,
): Promise<Record<string, string>> {
  const result: Record<string, string> = {};
  const dts = card.locator("dt");
  const dds = card.locator("dd");
  const count = await dts.count();
  for (let i = 0; i < count; i++) {
    const key = (await dts.nth(i).textContent()) ?? "";
    const val = (await dds.nth(i).textContent()) ?? "";
    result[key.trim()] = val.trim();
  }
  return result;
}

async function scrapeTableRows(
  table: import("@playwright/test").Locator,
): Promise<Array<Record<string, string>>> {
  const rows: Array<Record<string, string>> = [];
  const headers: string[] = [];
  const ths = table.locator("thead th");
  const thCount = await ths.count();
  for (let i = 0; i < thCount; i++) {
    const text = ((await ths.nth(i).textContent()) ?? "").replace(/[▲▼]/g, "").trim();
    headers.push(text);
  }
  const trs = table.locator("tbody tr");
  const trCount = await trs.count();
  for (let r = 0; r < trCount; r++) {
    const tds = trs.nth(r).locator("td");
    const tdCount = await tds.count();
    if (tdCount === 1) {
      const text = ((await tds.first().textContent()) ?? "").trim();
      if (text.startsWith("No ") || text.startsWith("Waiting")) continue;
    }
    const row: Record<string, string> = {};
    for (let c = 0; c < Math.min(tdCount, headers.length); c++) {
      row[headers[c]] = ((await tds.nth(c).textContent()) ?? "").trim();
    }
    rows.push(row);
  }
  return rows;
}

interface ApiState {
  instanceName: string;
  tradingPair: string;
  side: string;
  qty: number;
  entry: number;
  equity: number;
  realizedPnl: number;
  controllerState: string;
  regime: string;
  fillsCount: number;
  fillsTotal: number;
  fills: Array<{
    side: string;
    price: number;
    amount_base: number;
    realized_pnl_quote: number;
    is_maker: boolean;
    order_id: string;
    timestamp_ms: number;
  }>;
  ordersCount: number;
  orders: Array<{
    side: string;
    price: number;
    amount: number;
    state: string;
    order_id: string;
  }>;
  depthBids: number;
  depthAsks: number;
  bestBid: number;
  bestAsk: number;
  midPrice: number;
}

async function fetchApiState(
  request: import("@playwright/test").APIRequestContext,
  bot: string,
): Promise<ApiState> {
  const url = `${apiBase}/api/v1/state?instance_name=${bot}`;
  const res = await request.get(url, { timeout: 10_000 });
  const d = await res.json();

  const stream = d.stream ?? {};
  const pos = stream.position ?? {};
  const acct = d.summary?.account ?? {};
  const key = stream.key ?? {};
  const depth = stream.depth ?? {};
  const market = stream.market ?? {};

  const rawFills = Array.isArray(stream.fills) ? stream.fills : [];
  const rawOrders = Array.isArray(stream.open_orders) ? stream.open_orders : [];

  return {
    instanceName: bot,
    tradingPair: key.trading_pair ?? market.trading_pair ?? "",
    side: String(pos.side ?? "").toLowerCase() || "flat",
    qty: Math.abs(Number(pos.quantity ?? 0)),
    entry: Number(pos.avg_entry_price ?? 0),
    equity: Number(acct.equity_quote ?? 0),
    realizedPnl: Number(acct.realized_pnl_quote ?? 0),
    controllerState: String(acct.controller_state ?? "").toLowerCase(),
    regime: String(acct.regime ?? "").toLowerCase(),
    fillsCount: rawFills.length,
    fillsTotal: Number(stream.fills_total ?? rawFills.length),
    fills: rawFills.map((f: Record<string, unknown>) => ({
      side: String(f.side ?? "").toUpperCase(),
      price: Number(f.price ?? 0),
      amount_base: Number(f.amount_base ?? f.amount ?? 0),
      realized_pnl_quote: Number(f.realized_pnl_quote ?? 0),
      is_maker: Boolean(f.is_maker),
      order_id: String(f.order_id ?? ""),
      timestamp_ms: Number(f.timestamp_ms ?? 0),
    })),
    ordersCount: rawOrders.length,
    orders: rawOrders.map((o: Record<string, unknown>) => ({
      side: String(o.side ?? "").toUpperCase(),
      price: Number(o.price ?? 0),
      amount: Number(o.amount ?? o.quantity ?? o.amount_base ?? 0),
      state: String(o.state ?? ""),
      order_id: String(o.order_id ?? o.client_order_id ?? ""),
    })),
    depthBids: Array.isArray(depth.bids) ? depth.bids.length : 0,
    depthAsks: Array.isArray(depth.asks) ? depth.asks.length : 0,
    bestBid: Number(depth.best_bid ?? 0),
    bestAsk: Number(depth.best_ask ?? 0),
    midPrice: Number(market.mid_price ?? 0),
  };
}

async function switchToBot(
  page: import("@playwright/test").Page,
  bot: string,
): Promise<boolean> {
  const strip = page.locator("button").filter({ hasText: new RegExp(bot, "i") });
  const count = await strip.count();
  for (let i = 0; i < count; i++) {
    const text = (await strip.nth(i).textContent()) ?? "";
    if (text.toLowerCase().includes(bot)) {
      await strip.nth(i).click();
      return true;
    }
  }
  const current = await page
    .locator(".topbar-instance-name")
    .textContent()
    .catch(() => "");
  return current?.toLowerCase().includes(bot) ?? false;
}

/* ── tests ───────────────────────────────────────────────────────────── */

test.describe("Data integrity: UI vs API", () => {
  for (const bot of BOTS_TO_CHECK) {
    test(`${bot}: position, equity, fills, orders, depth match API`, async ({
      page,
      request,
    }, testInfo) => {
      const consoleErrors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });

      await page.goto("/", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.waitForTimeout(5_000);

      const switched = await switchToBot(page, bot);
      if (!switched) {
        console.log(`[${bot}] Could not switch — skipping`);
        return;
      }

      await page.waitForTimeout(5_000);

      const api = await fetchApiState(request, bot);
      console.log(
        `\n[${bot}] API: side=${api.side} qty=${api.qty.toFixed(6)} entry=${api.entry.toFixed(2)} equity=${api.equity.toFixed(2)} state=${api.controllerState} fills=${api.fillsCount} orders=${api.ordersCount} depth=${api.depthBids}b/${api.depthAsks}a mid=${api.midPrice.toFixed(2)}`,
      );

      const mismatches: string[] = [];

      // ──────────────────────────────────────────────────────────────
      // 1. Position panel
      // ──────────────────────────────────────────────────────────────
      const posPanel = page.locator('section:has(h2:text("Position"))');
      if ((await posPanel.count()) > 0) {
        const kv = await scrapeKvPanel(posPanel);
        console.log(`[${bot}] UI Position:`, kv);

        const uiSide = (kv["Side"] ?? "").toLowerCase();
        const uiQty = parseLocaleNumber(kv["Qty"] ?? "0");
        const uiEntry = parseLocaleNumber(kv["Entry"] ?? "0");

        if (uiSide !== api.side) {
          mismatches.push(`Position.Side: UI="${uiSide}" vs API="${api.side}"`);
        }
        const qtyCheck = approxEqual(uiQty, api.qty, "Position.Qty", 1, 1e-8);
        if (qtyCheck) mismatches.push(qtyCheck);

        if (api.side !== "flat" && api.entry > 0) {
          const entryCheck = approxEqual(uiEntry, api.entry, "Position.Entry", 0.5, 0.01);
          if (entryCheck) mismatches.push(entryCheck);
        }
      } else {
        console.log(`[${bot}] Position panel not found`);
      }

      // ──────────────────────────────────────────────────────────────
      // 2. Account / Equity / PnL panel
      // ──────────────────────────────────────────────────────────────
      const pnlPanel = page.locator('section:has(h2:text("24h Equity"))');
      if ((await pnlPanel.count()) > 0) {
        const equityCard = pnlPanel.locator("article.summary-card").first();
        const equityText = await equityCard.locator(".summary-value").first().textContent();
        const uiEquity = parseLocaleNumber(equityText ?? "0");
        console.log(`[${bot}] UI Equity: ${uiEquity}`);

        const eqCheck = approxEqual(uiEquity, api.equity, "Equity", 1, 0.5);
        if (eqCheck) mismatches.push(eqCheck);

        // PnL card
        const pnlCard = pnlPanel.locator("article.summary-card").nth(1);
        if ((await pnlCard.count()) > 0) {
          const pnlDl = await scrapeDlCard(pnlCard);
          console.log(`[${bot}] UI PnL card:`, pnlDl);

          const uiRealized = parseLocaleNumber(pnlDl["Realized"] ?? "0");
          if (Number.isFinite(uiRealized) && Number.isFinite(api.realizedPnl)) {
            const rpnlCheck = approxEqual(uiRealized, api.realizedPnl, "RealizedPnL", 5, 0.01);
            if (rpnlCheck) mismatches.push(rpnlCheck);
          }
        }

        // Risk card
        const riskCard = pnlPanel.locator("article.summary-card").nth(2);
        if ((await riskCard.count()) > 0) {
          const riskDl = await scrapeDlCard(riskCard);
          console.log(`[${bot}] UI Risk:`, riskDl);

          const uiController = (riskDl["Controller"] ?? "").toLowerCase().replace(/_/g, " ");
          const apiController = api.controllerState.replace(/_/g, " ");
          if (uiController && apiController && uiController !== apiController && uiController !== "n/a") {
            mismatches.push(`Controller: UI="${uiController}" vs API="${apiController}"`);
          }
        }
      }

      // ──────────────────────────────────────────────────────────────
      // 3. Fills panel
      // ──────────────────────────────────────────────────────────────
      const fillsPanel = page.locator('section:has(h2:text("Fills"))');
      if ((await fillsPanel.count()) > 0) {
        // Extract fill count from heading: "24h Fills(N)"
        const fillsHeading = await fillsPanel.locator("h2").textContent();
        const fillCountMatch = fillsHeading?.match(/\((\d+)\)/);
        const uiFillsTotal = fillCountMatch ? parseInt(fillCountMatch[1], 10) : -1;
        console.log(`[${bot}] UI Fills heading: "${fillsHeading?.trim()}" (count=${uiFillsTotal})`);

        // Compare fill counts
        if (uiFillsTotal >= 0) {
          const apiTotal = Math.max(api.fillsTotal, api.fillsCount);
          if (uiFillsTotal !== apiTotal && Math.abs(uiFillsTotal - apiTotal) > 1) {
            mismatches.push(`Fills count: UI=${uiFillsTotal} vs API=${apiTotal} (tolerance 1)`);
          }
        }

        // Meta row: Realized PnL, Notional, Fees, B/S counts, Maker %
        const metaPills = fillsPanel.locator(".meta-pill");
        const metaCount = await metaPills.count();
        const metaValues: Record<string, string> = {};
        for (let i = 0; i < metaCount; i++) {
          const text = ((await metaPills.nth(i).textContent()) ?? "").trim();
          const [label, ...rest] = text.split(/\s+/);
          metaValues[label] = rest.join(" ");
        }
        console.log(`[${bot}] UI Fills meta:`, metaValues);

        // Check B/S split matches API
        const bsText = Object.entries(metaValues).find(([_, v]) => /\d+B\s*\/\s*\d+S/.test(v));
        if (bsText) {
          const bsMatch = bsText[1].match(/(\d+)B\s*\/\s*(\d+)S/);
          if (bsMatch) {
            const uiBuys = parseInt(bsMatch[1], 10);
            const uiSells = parseInt(bsMatch[2], 10);
            const apiBuys = api.fills.filter((f) => f.side === "BUY").length;
            const apiSells = api.fills.filter((f) => f.side === "SELL").length;
            if (uiBuys !== apiBuys || uiSells !== apiSells) {
              mismatches.push(`Fills B/S: UI=${uiBuys}B/${uiSells}S vs API=${apiBuys}B/${apiSells}S`);
            }
          }
        }

        // Scrape fill table rows
        const fillTable = fillsPanel.locator("table[role='table']");
        if ((await fillTable.count()) > 0) {
          const fillRows = await scrapeTableRows(fillTable);
          console.log(`[${bot}] UI Fill rows: ${fillRows.length}`);

          if (fillRows.length > 0 && api.fills.length > 0) {
            // Compare first fill row (most recent, table is reversed)
            const uiFirst = fillRows[0];
            const apiSorted = [...api.fills].sort((a, b) => b.timestamp_ms - a.timestamp_ms);
            const apiFirst = apiSorted[0];

            const uiFillSide = (uiFirst["Side"] ?? "").toUpperCase();
            if (uiFillSide && apiFirst.side && uiFillSide !== apiFirst.side) {
              mismatches.push(`Fill[0].Side: UI="${uiFillSide}" vs API="${apiFirst.side}"`);
            }

            const uiFillPrice = parseLocaleNumber(uiFirst["Price"] ?? "0");
            const fillPriceCheck = approxEqual(uiFillPrice, apiFirst.price, "Fill[0].Price", 0.1, 0.01);
            if (fillPriceCheck) mismatches.push(fillPriceCheck);

            const uiFillQty = parseLocaleNumber(uiFirst["Qty"] ?? "0");
            const fillQtyCheck = approxEqual(uiFillQty, apiFirst.amount_base, "Fill[0].Qty", 1, 1e-8);
            if (fillQtyCheck) mismatches.push(fillQtyCheck);
          }
        }
      } else {
        console.log(`[${bot}] Fills panel not found`);
      }

      // ──────────────────────────────────────────────────────────────
      // 4. Orders panel
      // ──────────────────────────────────────────────────────────────
      const ordersPanel = page.locator('section:has(h2:text("Orders"))');
      if ((await ordersPanel.count()) > 0) {
        const ordersHeading = await ordersPanel.locator("h2").textContent();
        const orderCountMatch = ordersHeading?.match(/\((\d+)/);
        const uiOrdersCount = orderCountMatch ? parseInt(orderCountMatch[1], 10) : -1;
        console.log(`[${bot}] UI Orders heading: "${ordersHeading?.trim()}" (count=${uiOrdersCount})`);

        if (uiOrdersCount >= 0 && uiOrdersCount !== api.ordersCount) {
          mismatches.push(`Orders count: UI=${uiOrdersCount} vs API=${api.ordersCount}`);
        }

        const ordersTable = ordersPanel.locator("table[role='table']");
        if ((await ordersTable.count()) > 0) {
          const orderRows = await scrapeTableRows(ordersTable);
          console.log(`[${bot}] UI Order rows: ${orderRows.length}`);

          if (orderRows.length > 0 && api.orders.length > 0) {
            const uiFirstOrder = orderRows[0];
            const apiFirstOrder = api.orders[0];

            const uiOrderSide = (uiFirstOrder["Side"] ?? "").toUpperCase();
            if (uiOrderSide && apiFirstOrder.side && uiOrderSide !== apiFirstOrder.side) {
              mismatches.push(`Order[0].Side: UI="${uiOrderSide}" vs API="${apiFirstOrder.side}"`);
            }

            const uiOrderPrice = parseLocaleNumber(uiFirstOrder["Price"] ?? "0");
            const orderPriceCheck = approxEqual(uiOrderPrice, apiFirstOrder.price, "Order[0].Price", 0.5, 0.01);
            if (orderPriceCheck) mismatches.push(orderPriceCheck);
          }

          if (orderRows.length === 0 && api.ordersCount === 0) {
            console.log(`[${bot}] Orders: both UI and API show 0 — consistent`);
          }
        }
      } else {
        console.log(`[${bot}] Orders panel not found`);
      }

      // ──────────────────────────────────────────────────────────────
      // 5. Depth ladder panel
      // ──────────────────────────────────────────────────────────────
      const depthPanel = page.locator('section:has(h2:text("Depth"))');
      if ((await depthPanel.count()) > 0) {
        const depthMetaPills = depthPanel.locator(".meta-pill");
        const depthMetaCount = await depthMetaPills.count();
        const depthMeta: Record<string, string> = {};
        for (let i = 0; i < depthMetaCount; i++) {
          const text = ((await depthMetaPills.nth(i).textContent()) ?? "").trim();
          const spaceIdx = text.indexOf(" ");
          if (spaceIdx > 0) {
            depthMeta[text.slice(0, spaceIdx)] = text.slice(spaceIdx + 1);
          }
        }
        console.log(`[${bot}] UI Depth meta:`, depthMeta);

        const depthTable = depthPanel.locator("table");
        if ((await depthTable.count()) > 0) {
          const depthRows = await scrapeTableRows(depthTable);
          console.log(`[${bot}] UI Depth rows: ${depthRows.length}`);

          // Verify depth data is present when API has it
          if (api.depthBids > 0 || api.depthAsks > 0) {
            if (depthRows.length === 0) {
              mismatches.push(`Depth: API has ${api.depthBids}b/${api.depthAsks}a but UI shows none`);
            } else {
              // Compare top-of-book (first row)
              const firstRow = depthRows[0];
              const uiBidPrice = parseLocaleNumber(firstRow["Bid"] ?? "0");
              const uiAskPrice = parseLocaleNumber(firstRow["Ask"] ?? "0");

              if (api.bestBid > 0) {
                const bidCheck = approxEqual(uiBidPrice, api.bestBid, "Depth.BestBid", 0.1, 1);
                if (bidCheck) mismatches.push(bidCheck);
              }
              if (api.bestAsk > 0) {
                const askCheck = approxEqual(uiAskPrice, api.bestAsk, "Depth.BestAsk", 0.1, 1);
                if (askCheck) mismatches.push(askCheck);
              }
            }
          } else {
            console.log(`[${bot}] Depth: API has no depth data, UI rows=${depthRows.length}`);
          }
        }
      } else {
        console.log(`[${bot}] Depth panel not found`);
      }

      // ──────────────────────────────────────────────────────────────
      // 6. Market data (chart panel mid price)
      // ──────────────────────────────────────────────────────────────
      const posKv = (await posPanel.count()) > 0 ? await scrapeKvPanel(posPanel) : {};
      const uiMark = parseLocaleNumber(posKv["Mark"] ?? "0");
      if (Number.isFinite(uiMark) && uiMark > 0 && api.midPrice > 0) {
        const markCheck = approxEqual(uiMark, api.midPrice, "MarketMidPrice", 0.5, 5);
        if (markCheck) {
          console.log(`[${bot}] Mark/Mid price drift (not a mismatch, just FYI): ${markCheck}`);
        }
      }

      // ──────────────────────────────────────────────────────────────
      // 7. TopBar instance name + pair
      // ──────────────────────────────────────────────────────────────
      const topbarInstance = page.locator(".topbar-instance-name");
      if ((await topbarInstance.count()) > 0) {
        const instanceText = (await topbarInstance.textContent()) ?? "";
        if (!instanceText.toLowerCase().includes(bot)) {
          mismatches.push(`TopBar instance: expected "${bot}" in "${instanceText}"`);
        }
        if (api.tradingPair && !instanceText.includes(api.tradingPair)) {
          mismatches.push(`TopBar pair: expected "${api.tradingPair}" in "${instanceText}"`);
        }
      }

      // ──────────────────────────────────────────────────────────────
      // Screenshot + report
      // ──────────────────────────────────────────────────────────────
      const shotPath = testInfo.outputPath(`${bot}-data-integrity.png`);
      await page.screenshot({ path: shotPath, fullPage: true });
      await testInfo.attach(`${bot}-screenshot`, {
        path: shotPath,
        contentType: "image/png",
      });

      if (consoleErrors.length > 0) {
        console.log(`[${bot}] Browser console errors:`, consoleErrors.slice(0, 5));
      }

      if (mismatches.length > 0) {
        console.log(`\n[${bot}] *** MISMATCHES ***:`);
        for (const m of mismatches) console.log(`  ✗ ${m}`);
      } else {
        console.log(`[${bot}] ✓ All checks PASSED`);
      }

      expect(
        mismatches,
        `Data mismatches for ${bot}:\n${mismatches.join("\n")}`,
      ).toHaveLength(0);
    });
  }
});
