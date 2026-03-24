#!/usr/bin/env node
/**
 * Run Playwright against local Docker dashboard (default http://127.0.0.1:8088).
 * Optional: PLAYWRIGHT_BASE_URL, PLAYWRIGHT_API_BASE (default http://127.0.0.1:9910)
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const env = {
  ...process.env,
  PLAYWRIGHT_EXTERNAL_SERVER: "1",
  PLAYWRIGHT_BASE_URL: process.env.PLAYWRIGHT_BASE_URL?.trim() || "http://127.0.0.1:8088",
};

const extraArgs = process.argv.slice(2);
const pwArgs = ["playwright", "test", "playwright/dashboard-debug.spec.ts", "--headed", ...extraArgs];

const r = spawnSync("npx", pwArgs, {
  cwd: appDir,
  env,
  stdio: "inherit",
  shell: true,
});

process.exit(r.status ?? 1);
