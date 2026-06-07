import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/visual',
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4177',
    trace: 'retain-on-failure'
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4177',
    url: 'http://127.0.0.1:4177',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000
  }
});
