import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. Playwright starts `next dev` (which proxies /api → FastAPI via the BFF rewrites),
 * so the auth flow runs against the real backend. **A running FastAPI on :8000 + Postgres is
 * required** — start it separately (`uvicorn quantvista.api.app:app`) before `npm run e2e`.
 * Not wired into CI (needs the full stack + browser binaries).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
