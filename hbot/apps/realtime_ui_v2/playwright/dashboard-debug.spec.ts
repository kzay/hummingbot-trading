import { expect, test } from "@playwright/test";

/**
 * Live dashboard diagnostics (no API mocking). Use with Docker UI + API up, e.g.:
 *   node scripts/playwright-docker-debug.mjs
 * or:
 *   PLAYWRIGHT_EXTERNAL_SERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:8088 npx playwright test playwright/dashboard-debug.spec.ts --headed
 */
const apiBase = (process.env.PLAYWRIGHT_API_BASE || "").trim() || "http://127.0.0.1:9910";

test("live dashboard: health, shell, console + screenshot", async ({ page }, testInfo) => {
  const consoleLines: string[] = [];
  const problems: string[] = [];

  page.on("console", (msg) => {
    const line = `[${msg.type()}] ${msg.text()}`;
    consoleLines.push(line);
    if (msg.type() === "error") {
      problems.push(line);
    }
  });
  page.on("pageerror", (err) => {
    problems.push(`[pageerror] ${err.message}`);
  });

  const failedReq: string[] = [];
  page.on("requestfailed", (req) => {
    const err = req.failure()?.errorText || "failed";
    // App aborts in-flight /api/v1/state when a newer refresh starts (AbortController).
    if (err.includes("ERR_ABORTED") && req.url().includes("/api/v1/state")) {
      return;
    }
    failedReq.push(`${req.method()} ${req.url()} — ${err}`);
  });

  let healthBody = "";
  let healthStatus = 0;
  const healthUrl = `${apiBase.replace(/\/$/, "")}/health`;
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const healthRes = await page.request.get(healthUrl, { timeout: 10_000 });
      healthStatus = healthRes.status();
      healthBody = (await healthRes.text()).slice(0, 500);
      console.log(`\n[debug] GET ${healthUrl} -> ${healthStatus}`);
      console.log(healthBody ? healthBody.slice(0, 400) : "(empty body)");
      break;
    } catch (e) {
      if (attempt === 5) {
        problems.push(`[health] ${e instanceof Error ? e.message : String(e)}`);
        console.log(`\n[debug] GET ${healthUrl} failed after retries:`, e);
      } else {
        await page.waitForTimeout(2000);
      }
    }
  }

  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });

  await expect(page.locator("body")).toBeVisible();
  await expect(page.locator(".brand-text")).toBeVisible({ timeout: 20_000 });

  // Let WS + first poll settle
  await page.waitForTimeout(4_000);

  const shot = testInfo.outputPath("dashboard-debug-full.png");
  await page.screenshot({ path: shot, fullPage: true });
  await testInfo.attach("dashboard-full", { path: shot, contentType: "image/png" });

  console.log("\n--- browser console (last 40 lines) ---");
  console.log(consoleLines.slice(-40).join("\n") || "(none)");

  if (failedReq.length) {
    console.log("\n--- failed requests ---");
    console.log(failedReq.join("\n"));
    problems.push(...failedReq.map((r) => `[requestfailed] ${r}`));
  }

  if (problems.length) {
    console.log("\n--- problems (warnings only; test still passes) ---");
    console.log(problems.join("\n"));
  }

  expect(
    healthStatus,
    `Expected TCP /health from ${apiBase} (start realtime-ui-api or set PLAYWRIGHT_API_BASE)`,
  ).toBeGreaterThan(0);
  expect(healthStatus).toBeLessThan(600);
});
