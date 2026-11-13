import { defineConfig } from '@playwright/test';

/**
 * M3 Admin flows in a real browser against a MOCKED API (tests/e2e/admin.mocked.spec.ts).
 *   pnpm --filter @knowserve/frontend e2e:admin
 * The API is a stateful page.route fake (tests/e2e/support/admin-fake-api.ts) with the documented shapes.
 * This is NOT backend evidence and does not exercise Firebase sign-in
 * (real authentication is covered by the M1 auth flows and the backend tests). No emulator is needed.
 */
const port = Number(process.env['E2E_ADMIN_PORT'] ?? 5197);

export default defineConfig({
  testDir: '../../tests/e2e',
  testMatch: 'admin.*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? `http://localhost:${port}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: process.env['E2E_BASE_URL']
    ? undefined
    : {
        command: `node node_modules/vite/bin/vite.js --port ${port} --strictPort`,
        url: `http://localhost:${port}`,
        reuseExistingServer: true,
        timeout: 60_000,
        env: {
          VITE_FIREBASE_API_KEY: 'fake-api-key',
          VITE_FIREBASE_AUTH_DOMAIN: 'localhost',
          VITE_FIREBASE_PROJECT_ID: 'demo-knowserve',
        },
      },
});
