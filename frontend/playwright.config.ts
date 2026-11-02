import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:19003',
    viewport: { width: 1280, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: '../.venv/bin/python ../tests/browser_server.py',
    url: 'http://127.0.0.1:19003/poe2guild/health',
    reuseExistingServer: false,
  },
})
