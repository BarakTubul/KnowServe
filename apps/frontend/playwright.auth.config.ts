import { defineConfig } from '@playwright/test';

/**
 * M1 auth flows against the Firebase Auth Emulator (localhost:9099, project demo-knowserve).
 *   pnpm --filter @knowserve/frontend e2e:auth
 * By default the API is a contract-faithful fake installed with page.route (tests/e2e/support/fake-api.ts).
 * With E2E_REAL_API=1 the specs call the real API through the Vite proxy (:8000) instead, and the specs
 * that need controls the API does not expose are marked fixme (see each spec).
 * Isolation for the real API: use a FRESH database per run and start the API with
 * KS_DEMO_START_LIMIT=1000, otherwise the 5-per-hour Demo limit of earlier runs (the counters
 * persist) rate-limits later Try Demo starts. Commands: see tests/e2e/README.md.
 */
const port = Number(process.env['E2E_AUTH_PORT'] ?? 5199);
const emulator = process.env['E2E_FIREBASE_AUTH_EMULATOR_URL'] ?? 'http://localhost:9099';

export default defineConfig({
  testDir: '../../tests/e2e',
  testMatch: 'auth.*.spec.ts',
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
          VITE_FIREBASE_AUTH_EMULATOR_URL: emulator,
        },
      },
});
