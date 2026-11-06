// M1-06 auth flows against the Firebase Auth Emulator. Run: pnpm --filter @knowserve/frontend e2e:auth
// Default: API = contract-faithful fake (support/fake-api.ts). E2E_REAL_API=1 targets the real API
// (needs KS_FIREBASE_AUTH_EMULATOR_HOST=localhost:9099 set together with the emulator); until the backend
// slices merge (routes are 501 stubs) every spec is test.fixme in that mode.
import { expect, test, type Page } from '@playwright/test';
import {
  PASSWORD,
  actionPath,
  createVerifiedUser,
  latestOobCode,
  uniqueEmail,
} from './support/emulator';
import { REAL_API, useApi } from './support/fake-api';

test.beforeEach(() => {
  test.fixme(REAL_API, 'Real API routes are 501 stubs until M1-02b/M1-04 merge; run with the fake.');
});

async function signIn(page: Page, email: string, password = PASSWORD) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

async function pickDepartment(page: Page, name: string) {
  await page.getByRole('button', { name, exact: true }).click();
  await expect(page.getByTestId('active-department')).toHaveText(name);
}

test('password signup, verify in a fresh browser, login, logout (FE-AUTH-02/03/07)', async ({
  page,
  browser,
}) => {
  await useApi(page);
  const email = uniqueEmail('signup');
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign up' }).click();
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible();

  // Unverified: continuing gives no session.
  await page.getByRole('button', { name: 'I have verified my email' }).click();
  await expect(page.getByText(/not verified yet/)).toBeVisible();

  // Verify in a brand-new browser context (no Firebase user there): "email verified", no session.
  const other = await browser.newContext();
  const tab = await other.newPage();
  const api = await useApi(tab);
  await tab.goto(actionPath('verifyEmail', await latestOobCode(email, 'VERIFY_EMAIL')));
  await expect(tab.getByRole('heading', { name: 'Email verified' })).toBeVisible();
  await expect(tab.getByRole('link', { name: 'Go to sign in' })).toBeVisible();
  expect(api?.calls.filter((c) => c === 'POST /v1/auth/session')).toHaveLength(0);
  await other.close();

  // Back in the original tab the explicit continue starts the session.
  await page.getByRole('button', { name: 'I have verified my email' }).click();
  await expect(page.getByTestId('dashboard-page')).toBeVisible();
  await expect(page.getByTestId('demo-mode-badge')).toHaveText('Demo Mode');

  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByTestId('status-page')).toBeVisible();
  await page.goto('/dashboard');
  await expect(page.getByTestId('login-page')).toBeVisible();

  // And a normal password login afterwards.
  await signIn(page, email);
  await expect(page.getByTestId('dashboard-page')).toBeVisible();
});

test('Google sign-in through the emulator provider popup (FE-AUTH-02, M1-AC03)', async ({
  page,
}) => {
  await useApi(page);
  await page.goto('/login');
  const popupPromise = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Continue with Google' }).click();
  const popup = await popupPromise;
  await popup.getByText('Add new account').click();
  await popup.getByRole('button', { name: /auto-generate/i }).click();
  await popup.getByRole('button', { name: /sign in with google/i }).click();
  await expect(page.getByTestId('dashboard-page')).toBeVisible();
  await expect(page.getByTestId('account-kind')).toContainText('Registered');
});

test('Try Demo, reload stays Demo, expired Demo starts a new one (FE-AUTH-08)', async ({
  page,
}) => {
  const api = await useApi(page);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Try Demo' }).click();
  await expect(page.getByTestId('demo-time-left')).toContainText('left');
  await expect(page.getByTestId('demo-mode-badge')).toBeVisible();
  await pickDepartment(page, 'Finance');

  await page.reload();
  await expect(page.getByTestId('account-kind')).toHaveText('Demo visitor');
  await expect(page.getByTestId('active-department')).toHaveText('Finance');

  // The Demo ages out on the server; the anonymous Firebase user is still in this tab.
  test.fixme(!api, 'Needs a way to age a Demo identity on the real API (clock control).');
  api?.expireCurrentDemo();
  await page.reload();
  await expect(page.getByTestId('login-page')).toBeVisible();
  await page.getByRole('button', { name: 'Try Demo' }).click();
  await expect(page.getByTestId('demo-time-left')).toBeVisible();
  expect(api?.calls.filter((c) => c === 'POST /v1/demo/start')).toHaveLength(3);
});

test('Demo becomes Registered keeping the same identity (FE-AUTH-13, AUTH-34)', async ({
  page,
}) => {
  const api = await useApi(page);
  test.fixme(!api, 'Fixture records per department need a backend seeding hook (M1-02b).');
  await page.goto('/login');
  await page.getByRole('button', { name: 'Try Demo' }).click();
  await pickDepartment(page, 'Legal');
  const demoUser = [...(api?.users.values() ?? [])][0];
  const demoId = demoUser?.id;

  const email = uniqueEmail('convert');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Create account with email' }).click();
  await expect(page.getByTestId('convert-pending')).toBeVisible();

  // Pending survives a reload, and the account is still a Demo until verified.
  await page.reload();
  await expect(page.getByTestId('convert-pending')).toBeVisible();
  await expect(page.getByTestId('account-kind')).toHaveText('Demo visitor');

  // Verify in this tab, come back, then the explicit check converts.
  await page.goto(actionPath('verifyEmail', await latestOobCode(email, 'VERIFY_EMAIL')));
  await expect(page.getByRole('heading', { name: 'Email verified' })).toBeVisible();
  await page.getByRole('link', { name: 'Back to KnowServe' }).click();
  await page.getByRole('button', { name: 'I have verified my email' }).click();
  await expect(page.getByTestId('registered-state')).toBeVisible();
  await expect(page.getByTestId('account-kind')).toContainText(email);
  await expect(page.getByTestId('active-department')).toHaveText('Legal');
  expect(api?.userByEmail(email)?.id).toBe(demoId);
});

test('Demo cannot take an email that already has an account (FE-AUTH-13 collision)', async ({
  page,
}) => {
  await useApi(page);
  const existing = uniqueEmail('taken');
  await createVerifiedUser(existing);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Try Demo' }).click();
  await pickDepartment(page, 'Finance');
  await page.getByLabel('Email').fill(existing);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Create account with email' }).click();
  await expect(page.getByTestId('convert-collision')).toContainText('will not be moved');
  await page.getByRole('button', { name: /Sign in to that account/ }).click();
  await expect(page.getByTestId('login-page')).toBeVisible();
});

test('the last department is restored at the next login (FE-AUTH-09)', async ({ page }) => {
  await useApi(page);
  const email = uniqueEmail('dept');
  await createVerifiedUser(email);
  await signIn(page, email);
  await expect(page.getByTestId('department-required')).toBeVisible();
  await pickDepartment(page, 'Engineering');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await signIn(page, email);
  await expect(page.getByTestId('active-department')).toHaveText('Engineering');
});

test('verifying later than the freshness window needs an explicit reauthentication (AUTH-13/30)', async ({
  page,
}) => {
  const api = await useApi(page);
  test.fixme(!api, 'Needs the real API started with KS_AUTH_MAX_AGE_SECONDS=2 (small window).');
  if (api) api.freshnessSeconds = 2;
  const email = uniqueEmail('late');
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign up' }).click();
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible();
  await page.waitForTimeout(3000);
  await page.goto(actionPath('verifyEmail', await latestOobCode(email, 'VERIFY_EMAIL')));
  await expect(page.getByRole('heading', { name: 'Email verified' })).toBeVisible();
  expect(api?.calls.filter((c) => c === 'POST /v1/auth/session')).toHaveLength(0);
  await page.getByRole('button', { name: 'Continue to KnowServe' }).click();
  await expect(page.getByTestId('reauth-panel')).toBeVisible();
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Confirm' }).click();
  await expect(page.getByTestId('dashboard-page')).toBeVisible();
});
