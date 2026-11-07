// M2 library flow in a real browser against a MOCKED API (M2-AC10, AC12, AC13, AC22 browser half).
// The API is a page.route fake that follows docs/contracts/openapi.json. It is NOT backend evidence,
// and it does not exercise Firebase sign-in: real authentication is covered by the M1 auth flows
// (tests/e2e/auth.flows.spec.ts) and the backend tests. The PDF is a committed seed PDF rendered by
// the real pdf.js.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

const SEED_PDF = readFileSync(
  join(__dirname, '../../apps/api/src/knowserve_api/seed/data/seed-company-handbook.pdf'),
);

const FIN = { id: '00000000-0000-4000-8000-000000000002', slug: 'finance', name: 'Finance' };
const ENG = { id: '00000000-0000-4000-8000-000000000003', slug: 'engineering', name: 'Engineering' };
const DEPARTMENTS = [FIN, ENG];

const FIN_DOC = {
  id: '11111111-1111-4111-8111-111111111111',
  title: 'Company Handbook (sample)',
  filename: 'seed-company-handbook.pdf',
  owner_department: { id: FIN.id, name: FIN.name },
  page_count: 2,
};
const ENG_DOC = {
  id: '22222222-2222-4222-8222-222222222222',
  title: 'Incident Runbook (sample)',
  filename: 'seed-incident-runbook.pdf',
  owner_department: { id: ENG.id, name: ENG.name },
  page_count: 2,
};
const VISIBLE = { [FIN.id]: [FIN_DOC], [ENG.id]: [ENG_DOC] } as Record<string, (typeof FIN_DOC)[]>;

interface Mock {
  active: typeof FIN;
  contentRequests: string[];
  documentListDepartments: string[];
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

function notFound(route: Route) {
  return json(route, 404, {
    error: { code: 'DOCUMENT_NOT_FOUND', message: 'This document is not available.', request_id: 'r' },
  });
}

async function installApi(page: Page): Promise<Mock> {
  const mock: Mock = { active: FIN, contentRequests: [], documentListDepartments: [] };
  const identity = () => ({
    kind: 'registered',
    user_id: '33333333-3333-4333-8333-333333333333',
    email: 'user@example.test',
    display_name: null,
    sign_in_provider: 'password',
    active_department: mock.active,
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    csrf_token: 'csrf-test',
  });
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, '');
    const method = route.request().method();
    if (method === 'GET' && path === '/v1/auth/me') return json(route, 200, identity());
    if (method === 'GET' && path === '/v1/departments') {
      return json(route, 200, { departments: DEPARTMENTS });
    }
    if (method === 'PUT' && path === '/v1/session/department') {
      const body = route.request().postDataJSON() as { department_id: string };
      mock.active = DEPARTMENTS.find((d) => d.id === body.department_id) ?? mock.active;
      return json(route, 200, identity());
    }
    if (method === 'GET' && path === '/v1/documents') {
      mock.documentListDepartments.push(mock.active.slug);
      return json(route, 200, {
        items: VISIBLE[mock.active.id] ?? [],
        next_cursor: null,
        has_more: false,
      });
    }
    const content = /^\/v1\/documents\/([^/]+)\/content$/.exec(path);
    const meta = /^\/v1\/documents\/([^/]+)$/.exec(path);
    const target = (content ?? meta)?.[1];
    const doc = (VISIBLE[mock.active.id] ?? []).find((d) => d.id === target);
    if (content) {
      mock.contentRequests.push(`${mock.active.slug}:${target}`);
      if (!doc) return notFound(route);
      return route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        headers: { 'cache-control': 'private, no-store', 'accept-ranges': 'none' },
        body: SEED_PDF,
      });
    }
    if (meta) return doc ? json(route, 200, doc) : notFound(route);
    return json(route, 404, { error: { code: 'NOT_FOUND', message: 'x', request_id: 'r' } });
  });
  return mock;
}

test('m2_ac10_ac13_library_lists_only_the_active_department_and_a_switch_never_shows_the_old_list', async ({
  page,
}) => {
  const mock = await installApi(page);
  await page.goto('/documents');
  await expect(page.getByTestId('library-page')).toBeVisible();
  await expect(page.getByText(FIN_DOC.title)).toBeVisible();
  await expect(page.getByText(ENG_DOC.title)).toHaveCount(0);

  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Change department' }).click();
  await page.getByRole('button', { name: /Engineering/ }).click();
  await page.getByTestId('library-link').click();

  await expect(page.getByText(ENG_DOC.title)).toBeVisible();
  await expect(page.getByText(FIN_DOC.title)).toHaveCount(0);
  expect(mock.documentListDepartments).toContain('engineering');
});

test('m2_ac12_viewer_renders_the_pdf_from_the_api_and_page_navigation_updates_the_url', async ({
  page,
}) => {
  const mock = await installApi(page);
  await page.goto(`/documents/${FIN_DOC.id}`);
  await expect(page.getByTestId('viewer-filename')).toHaveText(FIN_DOC.filename);
  await expect(page.getByTestId('viewer-header-page')).toContainText('1');
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 15_000 });

  await page.getByRole('button', { name: 'Next page' }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByTestId('viewer-header-page')).toContainText('2');

  // Only the API bytes URL was requested for the PDF (no storage host, no other origin).
  expect(mock.contentRequests.length).toBeGreaterThan(0);
  expect(new Set(mock.contentRequests)).toEqual(new Set([`finance:${FIN_DOC.id}`]));
});

test('m2_ac12_another_departments_document_shows_the_same_neutral_not_available_view', async ({
  page,
}) => {
  await installApi(page);
  await page.goto(`/documents/${ENG_DOC.id}`); // active department is Finance
  await expect(page.getByTestId('viewer-not-available')).toBeVisible();
  const forbidden = await page.getByTestId('viewer-not-available').innerText();

  await page.goto('/documents/99999999-9999-4999-8999-999999999999'); // unknown id
  await expect(page.getByTestId('viewer-not-available')).toBeVisible();
  expect(await page.getByTestId('viewer-not-available').innerText()).toBe(forbidden);
});

test('m2_ac22_language_selector_switches_to_hebrew_rtl_and_the_choice_is_kept_in_the_browser', async ({
  page,
}) => {
  await installApi(page);
  await page.goto('/documents');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');

  await page.getByTestId('language-selector').selectOption('he');
  await expect(page.locator('html')).toHaveAttribute('lang', 'he');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('heading', { name: 'מסמכים' })).toBeVisible();

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'he');
});
