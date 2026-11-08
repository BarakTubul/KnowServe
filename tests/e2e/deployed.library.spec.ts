// M2-AC16: deployed smoke for the document library through the Pages proxy, real API, real R2.
//   E2E_BASE_URL=https://<pages host> pnpm --filter @knowserve/frontend exec playwright test deployed.library.spec.ts
// It starts one Demo visitor (a temporary user, cleaned up by the Demo retention job), picks
// Finance, reads seeded documents, makes a Range request and checks that a document the department
// cannot see gives the same neutral 404 as an unknown id. It writes nothing else and deletes nothing.
// Run by hand after the production seed (docs/milestones/M2/tasks.md); it is not part of the PR gate.
import { expect, test } from '@playwright/test';

const HANDBOOK = 'b0a26034-3f08-5d5c-91b0-9ec4b3a8e291'; // all five departments
const BUDGET = '3031b0fa-1a2b-52b9-8dcf-eb2e8a46b422'; // finance and engineering
const CONTRACT = 'e8726125-3c80-591e-b7bd-37fbf4f46b9a'; // sales only
const RUNBOOK = '5e9397a8-2727-5b2e-b008-c5ae042bb988'; // engineering only
const UNKNOWN = '99999999-9999-4999-8999-999999999999';

test('m2_ac16_finance_demo_reads_seeded_documents_with_a_range_request_and_gets_a_neutral_404', async ({
  page,
}) => {
  const baseUrl = process.env['E2E_BASE_URL'];
  if (!baseUrl) throw new Error('E2E_BASE_URL is required. Not skipping.');

  await page.goto(`${baseUrl}/login`);
  await page.getByRole('button', { name: 'Try Demo' }).click();
  await page.getByRole('button', { name: /Finance/ }).click();
  await expect(page.getByTestId('active-department')).toContainText('Finance');

  // Library: the two Finance documents are listed, the other two are not.
  await page.goto(`${baseUrl}/documents`);
  await expect(page.getByTestId('library-page')).toBeVisible();
  await expect(page.getByText('Company Handbook (sample)')).toBeVisible();
  await expect(page.getByText('Budget Planning Guide (sample)')).toBeVisible();
  await expect(page.getByText('Contract Review Checklist (sample)')).toHaveCount(0);
  await expect(page.getByText('Incident Runbook (sample)')).toHaveCount(0);

  // Bytes through the proxy: full body, then a single range (real R2 behind the API).
  const api = `${baseUrl}/api/v1/documents`;
  const full = await page.request.get(`${api}/${HANDBOOK}/content`);
  expect(full.status()).toBe(200);
  expect(full.headers()['content-type']).toContain('application/pdf');
  expect(full.headers()['cache-control']).toContain('no-store');
  const bytes = await full.body();
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-');

  const part = await page.request.get(`${api}/${HANDBOOK}/content`, {
    headers: { Range: 'bytes=0-99' },
  });
  expect(part.status()).toBe(206);
  expect(part.headers()['content-range']).toMatch(/^bytes 0-99\/\d+$/);
  expect((await part.body()).length).toBe(100);

  const outOfRange = await page.request.get(`${api}/${HANDBOOK}/content`, {
    headers: { Range: `bytes=${bytes.length + 10}-` },
  });
  expect(outOfRange.status()).toBe(416);

  // No storage host in any header of the bytes response.
  const headerText = JSON.stringify(full.headers());
  expect(headerText).not.toMatch(/r2\.cloudflarestorage\.com|r2\.dev/);

  // The viewer renders the PDF for a document Finance may read.
  await page.goto(`${baseUrl}/documents/${BUDGET}`);
  await expect(page.getByTestId('viewer-filename')).toBeVisible();
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 20_000 });

  // Neutral 404: documents Finance cannot see answer exactly like an unknown id.
  const bodies: string[] = [];
  for (const id of [CONTRACT, RUNBOOK, UNKNOWN]) {
    for (const suffix of ['', '/content']) {
      const res = await page.request.get(`${api}/${id}${suffix}`);
      expect(res.status(), `${id}${suffix}`).toBe(404);
      const body = (await res.json()) as { error: { code: string; message: string } };
      expect(body.error.code).toBe('DOCUMENT_NOT_FOUND');
      bodies.push(`${body.error.code}|${body.error.message}`);
    }
  }
  expect(new Set(bodies).size).toBe(1);
});
