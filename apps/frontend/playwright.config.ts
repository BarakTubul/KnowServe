import { defineConfig } from '@playwright/test';

// E2E_BASE_URL is required by the specs themselves (they fail with a clear message if missing).
export default defineConfig({
  testDir: '../../tests/e2e',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env['E2E_BASE_URL'],
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
