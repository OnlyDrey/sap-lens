import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:18745',
    headless: true,
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {},
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python ../scripts/serve-browser-tests.py',
    url: 'http://127.0.0.1:18745/health',
    reuseExistingServer: false,
    timeout: 20000,
  },
})
