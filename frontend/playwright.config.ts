import { defineConfig } from '@playwright/test'


// One .NET host and disposable data directory per Playwright process. One worker preserves fixture isolation.
const port = Number(process.env.AUTHLENS_BROWSER_TEST_PORT || 18745)

export default defineConfig({
  testDir: './tests',
  // Only Playwright specs. tests/unit/*.test.ts are node:test files (npm run test:unit); the default pattern would import and run them here too.
  testMatch: '**/*.spec.ts',
  // Aggregate E2E budget includes browser/page fixtures and full user workflows.
  // Assertion timeouts and production startup deadlines remain independent.
  timeout: 120_000,
  workers: 1,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    extraHTTPHeaders: { 'X-SAP-Lens-Token': 'synthetic-browser-capability-0000000000000000' },
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {},
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'node ../scripts/browser-server.mjs',
    url: `http://127.0.0.1:${port}/health/ready`,
    reuseExistingServer: false,
    // SIGTERM lets the server remove its temporary configuration directory; the default is SIGKILL, which leaks it.
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
    timeout: 120000,
  },
})
