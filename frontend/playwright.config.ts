import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  workers: 1,
  expect: { timeout: 30_000 },
  use: {
    baseURL: 'http://127.0.0.1:8080',
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : undefined,
  },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
})
