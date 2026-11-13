import { defineConfig } from '@playwright/test';

/**
 * CP6 local trial of the Admin frontend against the REAL local stack (tests/e2e/trial.admin.spec.ts).
 *   E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... pnpm --filter @knowserve/frontend e2e:trial
 * Needs the lead's harness: API :8000 (Vite proxies /api to it), Worker, queue stand-in, Firebase Auth
 * Emulator :9099 and an existing Admin account there. It is one sequential test with long waits for
 * processing; it is not part of any default or CI run. The mocked flows live in admin.mocked.spec.ts.
 */
const port = Number(process.env['E2E_TRIAL_PORT'] ?? 5199);
const emulator = process.env['E2E_FIREBASE_AUTH_EMULATOR_URL'] ?? 'http://localhost:9099';

export default defineConfig({
  testDir: '../../tests/e2e',
  testMatch: 'trial.*.spec.ts',
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
