import { defineConfig } from '@playwright/test';

/**
 * M2 library flow in a real browser against a MOCKED API (tests/e2e/library.mocked.spec.ts).
 *   pnpm --filter @knowserve/frontend e2e:library
 * The API is a page.route fake with the documented response shapes; the PDF is a committed seed PDF
 * rendered by the real pdf.js. This is NOT backend evidence and does not exercise Firebase sign-in
 * (real authentication is covered by the M1 auth flows and the backend tests). No emulator is needed.
 */
const port = Number(process.env['E2E_LIBRARY_PORT'] ?? 5198);

export default defineConfig({
  testDir: '../../tests/e2e',
  testMatch: 'library.*.spec.ts',
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
