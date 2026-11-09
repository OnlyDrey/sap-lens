import { defineConfig } from '@playwright/test'
import { PYTHON } from './tests/python'

// One server per Playwright process; scripts/run-tests.py gives each parallel process its own port.
const port = Number(process.env.SAP_LENS_BROWSER_TEST_PORT || 18745)

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
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {},
    trace: 'retain-on-failure',
  },
  webServer: {
    // `exec` makes the server a direct child of Playwright, so it can notice that Playwright is gone and exit (see serve-browser-tests.py).
    // The project's Python 3.12 (tests/python.ts), quoted for paths with spaces; never whatever `python` PATH resolves first.
    command: process.platform === 'win32' ? `"${PYTHON}" ../scripts/testing/serve-browser-tests.py` : `exec "${PYTHON}" ../scripts/testing/serve-browser-tests.py`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    // SIGTERM lets the server remove its temporary configuration directory; the default is SIGKILL, which leaks it.
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
    timeout: 20000,
  },
})
