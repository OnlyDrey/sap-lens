import { defineConfig } from '@playwright/test'

// One server per Playwright process; scripts/test.py gives each parallel process its own port.
const port = Number(process.env.SAP_LENS_BROWSER_TEST_PORT || 18745)

export default defineConfig({
  testDir: './tests',
  // Aggregate E2E budget includes browser/page fixtures and full user workflows.
  // Assertion timeouts and production startup deadlines remain independent.
  timeout: 120_000,
  workers: 1,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {},
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python ../scripts/serve-browser-tests.py',
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 20000,
  },
})
