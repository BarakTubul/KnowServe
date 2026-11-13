import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  ADMIN_CONFIRM,
  ADMIN_CREATE,
  ADMIN_LIST,
  ADMIN_PREVIEW,
  DEPARTMENTS,
  DEPARTMENTS_LIST,
  ME,
  adminDocKey,
  adminPage,
  departmentsOk,
  errorResponse,
  jsonResponse,
  makeAdminDocument,
  makeAdminIdentity,
  mockApi,
} from '@/test/fake-api';
import { FakeEventSource, stubEventSource } from '@/test/fake-event-source';
import { renderApp } from '@/test/render';
import { ADMIN_ERROR_CATALOGS } from '../admin-error-messages';

const [A, B, C] = DEPARTMENTS;
if (!A || !B || !C) throw new Error('fixture needs departments');

const base = {
  [ME]: () => jsonResponse(200, makeAdminIdentity({ active_department: A })),
  [DEPARTMENTS_LIST]: departmentsOk,
};

function pdf(name = 'leave.pdf', size = 64) {
  return new File([new Uint8Array(size).fill(65)], name, {
    type: name.endsWith('.pdf') ? 'application/pdf' : 'text/plain',
  });
}

function choose(label: string, file: File) {
  // fireEvent skips the `accept` filter of user.upload, so a wrong type reaches our own check.
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
}

beforeEach(() => {
  stubEventSource();
});

async function openUpload(routes: Parameters<typeof mockApi>[0]) {
  const api = mockApi({ ...base, [ADMIN_LIST]: () => adminPage([]), ...routes });
  const view = renderApp('/admin/documents');
  await view.user.click(await screen.findByRole('button', { name: 'Upload a document' }));
  const form = await screen.findByTestId('upload-form');
  await within(form).findByLabelText('Owner department');
  return { api, form: within(form), ...view };
}

describe('FE-ADM-03 single upload validation', () => {
  it('fe_adm_03_no_file_no_departments_and_a_non_pdf_show_inline_errors_and_make_no_request', async () => {
    const { api, form, user } = await openUpload({});
    await user.click(form.getByLabelText(A.name)); // deselect the preselected owner
    await user.click(form.getByRole('button', { name: 'Upload' }));
    expect(await form.findByText(ADMIN_ERROR_CATALOGS.en.FILE_REQUIRED)).toBeInTheDocument();
    expect(form.getByText(ADMIN_ERROR_CATALOGS.en.TITLE_INVALID)).toBeInTheDocument();
    expect(form.getByText(ADMIN_ERROR_CATALOGS.en.ALLOWED_DEPARTMENTS_EMPTY)).toBeInTheDocument();

    choose('PDF file', pdf('notes.txt'));
    await user.type(form.getByLabelText('Title'), 'Notes');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    expect(await form.findByText(ADMIN_ERROR_CATALOGS.en.NOT_A_PDF)).toBeInTheDocument();
    expect(api.count(ADMIN_CREATE)).toBe(0);
  });

  it('fe_adm_03_a_file_over_the_d1_limit_is_refused_before_sending', async () => {
    const { api, form, user } = await openUpload({});
    choose('PDF file', pdf('big.pdf', 20 * 1024 * 1024 + 1));
    await user.type(form.getByLabelText('Title'), 'Big');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    expect(await form.findByText(ADMIN_ERROR_CATALOGS.en.FILE_TOO_LARGE)).toBeInTheDocument();
    expect(api.count(ADMIN_CREATE)).toBe(0);
    expect(form.getByText(/up to 20 MiB/)).toBeInTheDocument();
  });

  it('fe_adm_03_the_form_states_that_ownership_alone_grants_no_access', async () => {
    const { form } = await openUpload({});
    expect(form.getByText(/Ownership alone does not give a department access/)).toBeInTheDocument();
  });

  it('fe_adm_03_owner_starts_as_the_active_department_and_preselects_it_as_allowed', async () => {
    const { form } = await openUpload({});
    expect(form.getByLabelText('Owner department')).toHaveValue(A.id);
    expect(form.getByLabelText(A.name)).toBeChecked();
    expect(form.getByLabelText(B.name)).not.toBeChecked();
  });

  it('fe_adm_03_picking_owner_b_after_deselecting_a_sends_allowed_b_only_and_never_infers', async () => {
    const created = makeAdminDocument({ status: 'queued', title: 'Policy' });
    const { api, form, user } = await openUpload({
      [ADMIN_CREATE]: () => jsonResponse(202, created),
    });
    await user.click(form.getByLabelText(A.name)); // deselect A
    await user.selectOptions(form.getByLabelText('Owner department'), B.id);
    expect(form.getByLabelText(B.name)).toBeChecked(); // preselected by choosing the owner
    expect(form.getByLabelText(A.name)).not.toBeChecked();

    choose('PDF file', pdf());
    await user.type(form.getByLabelText('Title'), 'Policy');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    await waitFor(() => expect(api.count(ADMIN_CREATE)).toBe(1));
    const body = await api.last(ADMIN_CREATE)!.formData();
    expect(body.get('owner_department_id')).toBe(B.id);
    expect(body.getAll('allowed_department_ids')).toEqual([B.id]);
    expect(body.get('title')).toBe('Policy');
  });

  it('fe_adm_03_without_an_active_department_nothing_is_preselected', async () => {
    mockApi({
      ...base,
      [ME]: () => jsonResponse(200, makeAdminIdentity({ active_department: null })),
      [ADMIN_LIST]: () => adminPage([]),
    });
    const { user } = renderApp('/admin/documents');
    await user.click(await screen.findByRole('button', { name: 'Upload a document' }));
    const form = within(await screen.findByTestId('upload-form'));
    await form.findByLabelText(A.name);
    expect(form.getByLabelText('Owner department')).toHaveValue('');
    expect(form.getByLabelText(A.name)).not.toBeChecked();
  });
});

describe('FE-ADM-04/05/09 submit, success and failure', () => {
  it('fe_adm_04_05_sends_multipart_disables_the_button_resets_and_shows_a_queued_row_with_a_stream', async () => {
    const created = makeAdminDocument({
      status: 'queued',
      title: 'Leave',
      delivery_state: 'queued',
    });
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let uploaded = false;
    const { api, form, user } = await openUpload({
      [ADMIN_LIST]: () => adminPage(uploaded ? [created] : []),
      [ADMIN_CREATE]: async () => {
        await gate;
        uploaded = true;
        return jsonResponse(202, created);
      },
    });
    choose('PDF file', pdf());
    await user.type(form.getByLabelText('Title'), 'Leave');
    await user.click(form.getByRole('button', { name: 'Upload' }));

    const submitting = await form.findByRole('button', { name: 'Uploading...' });
    expect(submitting).toBeDisabled();
    await user.click(submitting); // a second click while in flight does nothing
    release();

    expect(await form.findByTestId('upload-success')).toHaveTextContent(
      'was uploaded and is queued',
    );
    expect(api.count(ADMIN_CREATE)).toBe(1);
    const request = api.last(ADMIN_CREATE)!;
    expect(request.headers.get('Idempotency-Key')).toMatch(/^[A-Za-z0-9_-]{8,128}$/);
    expect(request.headers.get('Content-Type')).toMatch(/^multipart\/form-data/);
    // The form was reset and the document is in the list as queued, following its stream.
    expect(form.getByLabelText('Title')).toHaveValue('');
    expect(await screen.findByTestId('status-badge-queued')).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.open).toHaveLength(1));
    expect(FakeEventSource.open[0]!.url).toContain(`${created.document_id}/events`);
  });

  it('fe_adm_09_a_422_shows_the_catalog_message_and_keeps_every_input', async () => {
    const { form, user } = await openUpload({
      [ADMIN_CREATE]: () => errorResponse(422, 'NOT_A_PDF', 'magic bytes mismatch at offset 0'),
    });
    choose('PDF file', pdf());
    await user.type(form.getByLabelText('Title'), 'Keep me');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    const alert = await form.findByTestId('upload-error');
    expect(alert).toHaveTextContent(ADMIN_ERROR_CATALOGS.en.NOT_A_PDF);
    expect(alert).not.toHaveTextContent('magic bytes');
    expect(form.getByLabelText('Title')).toHaveValue('Keep me');
    expect(form.getByLabelText('Owner department')).toHaveValue(A.id);
    expect(form.getByLabelText(A.name)).toBeChecked();
    expect(form.getByRole('button', { name: 'Upload' })).toBeEnabled();
  });

  it('fe_adm_09_uploads_disabled_503_shows_the_paused_message', async () => {
    const { form, user } = await openUpload({
      [ADMIN_CREATE]: () => errorResponse(503, 'UPLOADS_DISABLED', 'flag off'),
    });
    choose('PDF file', pdf());
    await user.type(form.getByLabelText('Title'), 'T');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    expect(await form.findByTestId('upload-error')).toHaveTextContent(/paused/i);
  });

  it('fe_adm_04_a_retry_of_the_same_upload_reuses_the_key_and_a_new_upload_gets_a_new_one', async () => {
    let calls = 0;
    const created = makeAdminDocument({ status: 'queued' });
    const { api, form, user } = await openUpload({
      [ADMIN_CREATE]: () =>
        ++calls === 1
          ? errorResponse(503, 'DEPENDENCY_UNAVAILABLE', 'x')
          : jsonResponse(202, created),
    });
    choose('PDF file', pdf());
    await user.type(form.getByLabelText('Title'), 'Same');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    await form.findByTestId('upload-error');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    await form.findByTestId('upload-success');
    const keys = api.calls
      .filter((c) => c.key === ADMIN_CREATE)
      .map((c) => c.request.headers.get('Idempotency-Key'));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);

    choose('PDF file', pdf('second.pdf'));
    await user.type(form.getByLabelText('Title'), 'Other');
    await user.click(form.getByRole('button', { name: 'Upload' }));
    await waitFor(() => expect(api.count(ADMIN_CREATE)).toBe(3));
    const third = api.last(ADMIN_CREATE)!.headers.get('Idempotency-Key');
    expect(third).not.toBe(keys[0]);
  });
});

describe('FE-ADM-13 replace file of a failed document', () => {
  const failed = makeAdminDocument({
    document_id: '22222222-0000-4000-8000-000000000001',
    title: 'Failed doc',
    status: 'failed',
    failure_code: 'NO_EXTRACTABLE_TEXT',
    delivery_state: 'failed',
    can_retry: true,
    can_replace: true,
  });
  const ready = makeAdminDocument({
    document_id: '22222222-0000-4000-8000-000000000002',
    title: 'Ready doc',
  });
  const processing = makeAdminDocument({
    document_id: '22222222-0000-4000-8000-000000000003',
    title: 'Processing doc',
    status: 'processing',
    phase: 'extracting',
  });
  const replaceKey = adminDocKey('POST', failed.document_id, '/replace');

  function rowOf(title: string) {
    const row = screen
      .getAllByTestId('admin-document')
      .find((element) => within(element).queryByText(title) !== null);
    if (!row) throw new Error(`no row for ${title}`);
    return within(row);
  }

  it('fe_adm_13_the_action_exists_only_on_the_row_the_server_marks_replaceable_and_comes_before_retry', async () => {
    mockApi({ ...base, [ADMIN_LIST]: () => adminPage([ready, failed, processing]) });
    renderApp('/admin/documents');
    await screen.findByText('Failed doc');
    expect(
      rowOf('Ready doc').queryByRole('button', { name: 'Replace file' }),
    ).not.toBeInTheDocument();
    expect(
      rowOf('Processing doc').queryByRole('button', { name: 'Replace file' }),
    ).not.toBeInTheDocument();
    const buttons = rowOf('Failed doc')
      .getAllByRole('button')
      .map((b) => b.textContent);
    expect(buttons.indexOf('Replace file')).toBeLessThan(buttons.indexOf('Retry'));
  });

  it('fe_adm_13_shows_the_notice_sends_the_file_and_moves_the_row_to_queued', async () => {
    const queued = {
      ...failed,
      status: 'queued',
      failure_code: null,
      can_retry: false,
      can_replace: false,
    };
    let replaced = false;
    const api = mockApi({
      ...base,
      [ADMIN_LIST]: () => adminPage([replaced ? (queued as typeof failed) : failed]),
      [replaceKey]: () => {
        replaced = true;
        return jsonResponse(202, queued);
      },
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Failed doc');
    await user.click(rowOf('Failed doc').getByRole('button', { name: 'Replace file' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Replace file' }));
    expect(dialog.getByTestId('replace-notice')).toHaveTextContent(
      'document ID, owner and access stay the same',
    );
    expect(dialog.getByTestId('replace-notice')).toHaveTextContent('unavailable to users');

    await user.click(dialog.getByRole('button', { name: 'Replace file' })); // no file yet
    expect(await dialog.findByRole('alert')).toHaveTextContent(
      ADMIN_ERROR_CATALOGS.en.FILE_REQUIRED,
    );
    expect(api.count(replaceKey)).toBe(0);

    fireEvent.change(dialog.getByLabelText('New PDF file'), {
      target: { files: [pdf('fixed.pdf')] },
    });
    await user.click(dialog.getByRole('button', { name: 'Replace file' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(api.last(replaceKey)!.headers.get('Idempotency-Key')).toMatch(/^[A-Za-z0-9_-]{8,128}$/);
    expect(await rowOf('Failed doc').findByTestId('status-badge-queued')).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.open).toHaveLength(1));
  });

  it.each([
    [409, 'DOCUMENT_NOT_REPLACEABLE'],
    [422, 'NOT_A_PDF'],
  ] as const)(
    'fe_adm_13_a_%i_shows_the_catalog_message_and_the_row_stays_failed',
    async (status, code) => {
      mockApi({
        ...base,
        [ADMIN_LIST]: () => adminPage([failed]),
        [replaceKey]: () => errorResponse(status, code, 'raw server text'),
      });
      const { user } = renderApp('/admin/documents');
      await screen.findByText('Failed doc');
      await user.click(rowOf('Failed doc').getByRole('button', { name: 'Replace file' }));
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.change(dialog.getByLabelText('New PDF file'), { target: { files: [pdf()] } });
      await user.click(dialog.getByRole('button', { name: 'Replace file' }));
      const alert = await dialog.findByTestId('replace-error');
      expect(alert).toHaveTextContent(ADMIN_ERROR_CATALOGS.en[code]);
      expect(alert).not.toHaveTextContent('raw server text');
      expect(rowOf('Failed doc').getByTestId('status-badge-failed')).toBeInTheDocument();
    },
  );
});

describe('FE-ADM-11 ZIP import preview and confirm', () => {
  const zip = () =>
    new File([new Uint8Array(32).fill(80)], 'batch.zip', { type: 'application/zip' });
  const preview = {
    valid_count: 1,
    invalid_count: 2,
    entries: [
      {
        index: 0,
        file: 'ok.pdf',
        valid: true,
        title: 'Good one',
        owner_department: A,
        allowed_departments: [A, B],
      },
      {
        index: 1,
        file: 'missing.pdf',
        valid: false,
        title: 'No access list',
        owner_department: A,
        allowed_departments: [],
        error_code: 'ALLOWED_DEPARTMENTS_MISSING',
        error_message: 'server english',
      },
      {
        index: 2,
        file: 'empty.pdf',
        valid: false,
        title: 'Empty access list',
        owner_department: A,
        allowed_departments: [],
        error_code: 'ALLOWED_DEPARTMENTS_EMPTY',
      },
    ],
  };

  async function openImport(routes: Parameters<typeof mockApi>[0]) {
    const api = mockApi({
      ...base,
      [ADMIN_LIST]: () => adminPage([]),
      [ADMIN_PREVIEW]: () => jsonResponse(200, preview),
      ...routes,
    });
    const view = renderApp('/admin/documents');
    await view.user.click(await screen.findByRole('button', { name: 'Import a ZIP' }));
    const panel = within(await screen.findByTestId('import-panel'));
    return { api, panel, ...view };
  }

  async function previewIt(
    panel: ReturnType<typeof within>,
    user: ReturnType<typeof renderApp>['user'],
  ) {
    fireEvent.change(panel.getByLabelText('ZIP file'), { target: { files: [zip()] } });
    await user.click(panel.getByRole('button', { name: 'Preview' }));
    return panel.findByTestId('import-preview');
  }

  it('fe_adm_11_the_preview_lists_valid_and_invalid_entries_with_no_default_access_and_creates_nothing', async () => {
    const { api, panel, user } = await openImport({});
    const box = within(await previewIt(panel, user));
    expect(box.getAllByTestId('import-entry-valid')).toHaveLength(1);
    expect(box.getAllByTestId('import-entry-invalid')).toHaveLength(2);
    expect(box.getByTestId('import-entry-allowed')).toHaveTextContent(`${A.name}, ${B.name}`);
    const problems = box.getAllByTestId('import-entry-problem').map((p) => p.textContent);
    expect(problems).toEqual([
      ADMIN_ERROR_CATALOGS.en.ALLOWED_DEPARTMENTS_MISSING,
      ADMIN_ERROR_CATALOGS.en.ALLOWED_DEPARTMENTS_EMPTY,
    ]);
    expect(box.queryByText(/server english/)).not.toBeInTheDocument();
    expect(box.getByText(/no default access for imports/i)).toBeInTheDocument();
    expect(box.getByText('1 valid, 2 invalid. Nothing has been created yet.')).toBeInTheDocument();
    expect(api.count(ADMIN_PREVIEW)).toBe(1);
    expect(api.count(ADMIN_CONFIRM)).toBe(0);
    expect(api.count(ADMIN_CREATE)).toBe(0);
  });

  it('fe_adm_11_confirm_resends_the_zip_with_a_key_is_double_click_safe_and_shows_per_file_results', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const { api, panel, user } = await openImport({
      [ADMIN_CONFIRM]: async () => {
        await gate;
        return jsonResponse(200, {
          created_count: 1,
          rejected_count: 0,
          results: [{ index: 0, file: 'ok.pdf', status: 'created', document_id: 'd1' }],
        });
      },
    });
    const box = within(await previewIt(panel, user));
    await user.click(box.getByRole('button', { name: 'Import 1 valid document' }));
    const busy = await box.findByRole('button', { name: 'Importing...' });
    expect(busy).toBeDisabled();
    await user.click(busy);
    release();

    const results = within(await panel.findByTestId('import-results'));
    expect(results.getByText('1 created, 0 not imported.')).toBeInTheDocument();
    expect(api.count(ADMIN_CONFIRM)).toBe(1);
    const request = api.last(ADMIN_CONFIRM)!;
    expect(request.headers.get('Idempotency-Key')).toMatch(/^[A-Za-z0-9_-]{8,128}$/);
    expect(request.headers.get('Content-Type')).toMatch(/^multipart\/form-data/);
    expect((await request.formData()).get('file')).not.toBeNull();
    expect(results.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument();
  });

  it('fe_adm_11_retry_of_the_failed_file_sends_the_zip_again_with_a_new_key_and_creates_it', async () => {
    let calls = 0;
    const { api, panel, user } = await openImport({
      [ADMIN_CONFIRM]: () =>
        jsonResponse(
          200,
          ++calls === 1
            ? {
                created_count: 1,
                rejected_count: 1,
                results: [
                  { index: 0, file: 'ok.pdf', status: 'created', document_id: 'd1' },
                  {
                    index: 1,
                    file: 'later.pdf',
                    status: 'rejected',
                    error_code: 'UPLOAD_BACKLOG_FULL',
                  },
                ],
              }
            : {
                created_count: 1,
                rejected_count: 0,
                results: [{ index: 1, file: 'later.pdf', status: 'created', document_id: 'd2' }],
              },
        ),
    });
    const box = within(await previewIt(panel, user));
    await user.click(box.getByRole('button', { name: /^Import 1 valid/ }));
    const results = within(await panel.findByTestId('import-results'));
    expect(results.getByTestId('import-result-rejected')).toHaveTextContent(
      ADMIN_ERROR_CATALOGS.en.UPLOAD_BACKLOG_FULL,
    );
    await user.click(
      results.getByRole('button', { name: 'Retry the files that were not imported' }),
    );
    await waitFor(() => expect(api.count(ADMIN_CONFIRM)).toBe(2));
    const keys = api.calls
      .filter((c) => c.key === ADMIN_CONFIRM)
      .map((c) => c.request.headers.get('Idempotency-Key'));
    expect(keys[0]).not.toBe(keys[1]);
    expect(await panel.findByText('1 created, 0 not imported.')).toBeInTheDocument();
  });

  it('fe_adm_11_a_zip_error_from_the_server_shows_the_catalog_message_and_nothing_is_confirmed', async () => {
    const { api, panel, user } = await openImport({
      [ADMIN_PREVIEW]: () => errorResponse(422, 'ZIP_ENCRYPTED', 'entry 3 flag bit 0'),
    });
    fireEvent.change(panel.getByLabelText('ZIP file'), { target: { files: [zip()] } });
    await user.click(panel.getByRole('button', { name: 'Preview' }));
    expect(await panel.findByRole('alert')).toHaveTextContent(
      ADMIN_ERROR_CATALOGS.en.ZIP_ENCRYPTED,
    );
    expect(api.count(ADMIN_CONFIRM)).toBe(0);
  });

  it('fe_adm_11_without_valid_entries_confirm_is_disabled_and_a_wrong_file_type_is_refused_locally', async () => {
    const { api, panel, user } = await openImport({
      [ADMIN_PREVIEW]: () =>
        jsonResponse(200, { valid_count: 0, invalid_count: 1, entries: [preview.entries[1]] }),
    });
    fireEvent.change(panel.getByLabelText('ZIP file'), {
      target: { files: [new File(['x'], 'a.pdf')] },
    });
    expect(await panel.findByRole('alert')).toHaveTextContent(ADMIN_ERROR_CATALOGS.en.ZIP_INVALID);
    await user.click(panel.getByRole('button', { name: 'Preview' }));
    expect(api.count(ADMIN_PREVIEW)).toBe(0);

    const box = within(await previewIt(panel, user));
    expect(box.getByRole('button', { name: 'Import 0 valid documents' })).toBeDisabled();
  });
});
