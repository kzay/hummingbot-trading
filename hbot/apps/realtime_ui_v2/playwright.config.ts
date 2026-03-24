import { defineConfig } from "@playwright/test";

/** Set to 1/true when the UI is already served (e.g. Docker realtime-ui-web on :8088). */
const externalServer = ["1", "true", "yes"].includes(
  (process.env.PLAYWRIGHT_EXTERNAL_SERVER || "").toLowerCase(),
);

const baseURL =
  (process.env.PLAYWRIGHT_BASE_URL || "").trim() ||
  (externalServer ? "http://127.0.0.1:8088" : "http://127.0.0.1:4173");

export default defineConfig({
  testDir: "./playwright",
  timeout: externalServer ? 60_000 : 30_000,
  use: {
    baseURL,
    trace: externalServer ? "on" : "on-first-retry",
  },
  webServer: externalServer
    ? undefined
    : {
        command: "npm run preview -- --host 127.0.0.1 --port 4173",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
