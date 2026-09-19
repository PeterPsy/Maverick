import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/ui', workers: 1, fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:4178', browserName: 'chromium', headless: true },
  webServer: { command: 'node tests/ui/server.mjs', url: 'http://127.0.0.1:4178', reuseExistingServer: false },
});
