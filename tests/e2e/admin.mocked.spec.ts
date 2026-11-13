// M3 Admin flows in a real browser against a MOCKED API (M3-AC for FE-ADM-05/06/11/13).
// The API is a stateful page.route fake (support/admin-fake-api.ts) that follows
// docs/contracts/admin-api.md. It is NOT backend evidence and does not exercise Firebase sign-in; the
// real-API wiring is checked once in the lead's local trial at CP6.
import { expect, test, type Page } from '@playwright/test';
import { installAdminApi } from './support/admin-fake-api';

const PDF = (name: string) => ({
  name,
  mimeType: 'application/pdf',
  buffer: Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'),
});

async function uploadPdf(page: Page, title: string) {
  await page.getByRole('button', { name: 'Upload a document' }).click();
  const form = page.getByTestId('upload-form');
  await form.getByLabel('PDF file').setInputFiles(PDF('policy.pdf'));
  await form.getByLabel('Title').fill(title);
  await form.getByRole('button', { name: 'Upload' }).click();
  await expect(form.getByTestId('upload-success')).toBeVisible();
}

test('m3_upload_goes_from_queued_to_ready_through_the_status_stream', async ({ page }) => {
  const api = await installAdminApi(page);
  await page.goto('/admin/documents');
  await expect(page.getByTestId('admin-empty')).toBeVisible();

  await uploadPdf(page, 'Leave policy');
  const row = page.getByTestId('admin-document').filter({ hasText: 'Leave policy' });
  await expect(row.getByTestId('status-badge-ready')).toBeVisible();
  expect(api.createKeys).toHaveLength(1);
  expect(api.createKeys[0]).toMatch(/^[A-Za-z0-9_-]{8,128}$/);
});

test('m3_failed_document_is_replaced_and_becomes_ready', async ({ page }) => {
  await installAdminApi(page);
  await page.goto('/admin/documents');
  await uploadPdf(page, 'Scanned handbook');

  const row = page.getByTestId('admin-document').filter({ hasText: 'Scanned handbook' });
  await expect(row.getByTestId('status-badge-failed')).toBeVisible();
  await expect(row.getByTestId('failure-reason')).toContainText('selectable text');

  await row.getByRole('button', { name: 'Replace file' }).click();
  const dialog = page.getByRole('dialog', { name: 'Replace file' });
  await expect(dialog.getByTestId('replace-notice')).toContainText('unavailable to users');
  await dialog.getByLabel('New PDF file').setInputFiles(PDF('fixed.pdf'));
  await dialog.getByRole('button', { name: 'Replace file' }).click();

  await expect(dialog).toBeHidden();
  await expect(row.getByTestId('status-badge-ready')).toBeVisible();
});

test('m3_zip_preview_shows_the_bad_entry_confirm_imports_the_rest_and_retry_creates_the_other', async ({
  page,
}) => {
  const api = await installAdminApi(page);
  await page.goto('/admin/documents');
  await page.getByRole('button', { name: 'Import a ZIP' }).click();
  const panel = page.getByTestId('import-panel');
  await panel.getByLabel('ZIP file').setInputFiles({
    name: 'batch.zip',
    mimeType: 'application/zip',
    buffer: Buffer.from('PK\u0003\u0004 fake'),
  });
  await panel.getByRole('button', { name: 'Preview' }).click();

  const preview = panel.getByTestId('import-preview');
  await expect(preview.getByTestId('import-entry-valid')).toHaveCount(2);
  await expect(preview.getByTestId('import-entry-invalid')).toHaveCount(1);
  await expect(preview.getByTestId('import-entry-problem')).toContainText('which departments');
  // Nothing exists before the explicit confirm.
  await expect(page.getByTestId('admin-document')).toHaveCount(0);

  await preview.getByRole('button', { name: 'Import 2 valid documents' }).click();
  const results = panel.getByTestId('import-results');
  await expect(results.getByText('1 created, 1 not imported.')).toBeVisible();
  await expect(page.getByTestId('admin-document')).toHaveCount(1);

  await results.getByRole('button', { name: 'Retry the files that were not imported' }).click();
  await expect(results.getByText('1 created, 0 not imported.')).toBeVisible();
  await expect(page.getByTestId('admin-document')).toHaveCount(2);
  expect(api.confirmKeys).toHaveLength(2);
  expect(api.confirmKeys[0]).not.toBe(api.confirmKeys[1]);
});

test('m3_a_registered_user_cannot_open_the_admin_page', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: '44444444-4444-4444-8444-444444444444',
        kind: 'registered',
        sign_in_provider: 'password',
        email: 'user@example.test',
        display_name: null,
        active_department: null,
        csrf_token: 'x',
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      }),
    }),
  );
  await page.goto('/admin/documents');
  await expect(page.getByTestId('admin-not-available')).toBeVisible();
});
