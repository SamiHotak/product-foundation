import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against the full running stack (make dev):
 * Next.js -> FastAPI -> Postgres, Redis and a real Celery worker.
 *
 *   make e2e                         (Windows: runs inside Docker, no Node needed)
 *   PLAYWRIGHT_BASE_URL=... npx playwright test
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "./tests/e2e",
  // The dev server compiles each page on first visit, so give it time.
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    navigationTimeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], launchOptions: { executablePath } },
      testIgnore: /mobile\.spec\.ts/,
    },
    {
      name: "phone",
      use: { ...devices["Pixel 7"], launchOptions: { executablePath } },
      testMatch: /mobile\.spec\.ts/,
    },
  ],
});
