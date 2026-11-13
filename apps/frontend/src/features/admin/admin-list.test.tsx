import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  ADMIN_LIST,
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
  makeIdentity,
  mockApi,
} from '@/test/fake-api';
import { FakeEventSource, stubEventSource } from '@/test/fake-event-source';
import { renderApp } from '@/test/render';
import { ADMIN_ERROR_CATALOGS, FAILURE_CATALOGS } from './admin-error-messages';

const [A, B, C] = DEPARTMENTS;
if (!A || !B || !C) throw new Error('fixture needs departments');

const queued = makeAdminDocument({
  document_id: '11111111-0000-4000-8000-000000000001',
  title: 'Queued doc',
  status: 'queued',
  delivery_state: 'queued',
});
const processing = makeAdminDocument({
  document_id: '11111111-0000-4000-8000-000000000002',
  title: 'Processing doc',
  status: 'processing',
  phase: 'embedding',
  delivery_state: 'processing',
});
const ready = makeAdminDocument({
  document_id: '11111111-0000-4000-8000-000000000003',
  title: 'Ready doc',
  allowed_departments: [A, C],
});
const failed = makeAdminDocument({
  document_id: '11111111-0000-4000-8000-000000000004',
  title: 'Failed doc',
  status: 'failed',
  failure_code: 'NO_EXTRACTABLE_TEXT',
  failure_message: 'English fallback from the server that must never be shown',
  delivery_state: 'failed',
  can_retry: true,
  can_replace: true,
});

const adminBase = {
  [ME]: () => jsonResponse(200, makeAdminIdentity({ active_department: null })),
  [DEPARTMENTS_LIST]: departmentsOk,
};

function row(title: string) {
  const element = screen.getByText(title).closest('[data-testid="admin-document"]');
  if (!(element instanceof HTMLElement)) throw new Error(`no row for ${title}`);
  return within(element);
}

beforeEach(() => {
  stubEventSource();
});

describe('FE-ADM-01 Admin only', () => {
  it('fe_adm_01_a_registered_user_sees_the_not_available_view_and_no_admin_call_is_made', async () => {
    const api = mockApi({
      [ME]: () => jsonResponse(200, makeIdentity()),
      [DEPARTMENTS_LIST]: departmentsOk,
    });
    renderApp('/admin/documents');
    expect(await screen.findByTestId('admin-not-available')).toHaveTextContent('not available');
    expect(api.count(ADMIN_LIST)).toBe(0);
    expect(screen.queryByTestId('admin-documents-page')).not.toBeInTheDocument();
  });

  it('fe_arch_07_the_dashboard_links_to_admin_only_for_the_admin', async () => {
    mockApi({
      ...adminBase,
      [ME]: () => jsonResponse(200, makeAdminIdentity({ active_department: A })),
    });
    const { unmount } = renderApp('/dashboard');
    expect(await screen.findByTestId('admin-link')).toHaveAttribute('href', '/admin/documents');
    unmount();

    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: A })),
      [DEPARTMENTS_LIST]: departmentsOk,
    });
    renderApp('/dashboard');
    await screen.findByTestId('library-link');
    expect(screen.queryByTestId('admin-link')).not.toBeInTheDocument();
  });

  it('fe_adm_01_the_admin_needs_no_active_department', async () => {
    mockApi({ ...adminBase, [ADMIN_LIST]: () => adminPage([ready]) });
    renderApp('/admin/documents');
    expect(await screen.findByText('Ready doc')).toBeInTheDocument();
    expect(screen.queryByTestId('department-required')).not.toBeInTheDocument();
  });
});

describe('FE-ADM-02 and FE-ADM-10 list and badges', () => {
  it('fe_adm_02_10_renders_every_status_with_a_distinct_badge_owner_and_allowed_departments', async () => {
    mockApi({ ...adminBase, [ADMIN_LIST]: () => adminPage([queued, processing, ready, failed]) });
    renderApp('/admin/documents');
    expect(await screen.findAllByTestId('admin-document')).toHaveLength(4);
    expect(row('Queued doc').getByTestId('status-badge-queued')).toHaveTextContent('Queued');
    expect(row('Processing doc').getByTestId('status-badge-processing')).toHaveTextContent(
      'Processing: Preparing for search',
    );
    expect(row('Ready doc').getByTestId('status-badge-ready')).toHaveTextContent('Ready');
    expect(row('Failed doc').getByTestId('status-badge-failed')).toHaveTextContent('Failed');
    expect(row('Ready doc').getByTestId('allowed-departments')).toHaveTextContent(
      `${A.name}, ${C.name}`,
    );
    expect(row('Ready doc').getByText(/Owner: Aurora Finance/)).toBeInTheDocument();
  });

  it('fe_adm_06_a_failed_document_shows_the_catalog_reason_never_the_server_text', async () => {
    mockApi({ ...adminBase, [ADMIN_LIST]: () => adminPage([failed]) });
    renderApp('/admin/documents');
    const reason = await screen.findByTestId('failure-reason');
    expect(reason).toHaveTextContent(FAILURE_CATALOGS.en.NO_EXTRACTABLE_TEXT);
    expect(reason).not.toHaveTextContent('English fallback');
  });

  it('fe_adm_02_search_and_status_filter_are_sent_to_the_api', async () => {
    const api = mockApi({
      ...adminBase,
      [ADMIN_LIST]: (request) => {
        const q = new URL(request.url).searchParams.get('q');
        return adminPage(q ? [] : [ready]);
      },
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');
    await user.type(screen.getByLabelText('Search by title'), 'leave');
    expect(await screen.findByTestId('admin-no-match')).toBeInTheDocument();
    expect(new URL(api.last(ADMIN_LIST)!.url).searchParams.get('q')).toBe('leave');

    await user.selectOptions(screen.getByLabelText('Status'), 'failed');
    await waitFor(() =>
      expect(new URL(api.last(ADMIN_LIST)!.url).searchParams.get('status')).toBe('failed'),
    );
  });

  it('fe_adm_02_shows_an_empty_state_and_pages_with_load_more', async () => {
    const api = mockApi({
      ...adminBase,
      [ADMIN_LIST]: (request) =>
        new URL(request.url).searchParams.get('cursor')
          ? adminPage([ready])
          : adminPage([failed], 'cursor-2'),
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Failed doc');
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    expect(await screen.findByText('Ready doc')).toBeInTheDocument();
    expect(new URL(api.last(ADMIN_LIST)!.url).searchParams.get('cursor')).toBe('cursor-2');
  });

  it('fe_adm_09_a_list_error_shows_the_catalog_message_and_can_be_retried', async () => {
    let calls = 0;
    mockApi({
      ...adminBase,
      [ADMIN_LIST]: () =>
        ++calls === 1
          ? errorResponse(503, 'DEPENDENCY_UNAVAILABLE', 'psycopg2 failed at db-7')
          : adminPage([ready]),
    });
    const { user } = renderApp('/admin/documents');
    const alert = await screen.findByTestId('admin-list-error');
    expect(alert).toHaveTextContent(ADMIN_ERROR_CATALOGS.en.DEPENDENCY_UNAVAILABLE);
    expect(alert).not.toHaveTextContent(/psycopg2|db-7/);
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Ready doc')).toBeInTheDocument();
  });
});

describe('ADM-16 retry uses the server flags', () => {
  it('fe_adm_06_retry_is_offered_only_where_can_retry_is_true_and_requeues_the_document', async () => {
    const retried = {
      ...failed,
      status: 'queued',
      failure_code: null,
      can_retry: false,
      can_replace: false,
    };
    const api = mockApi({
      ...adminBase,
      [ADMIN_LIST]: () => adminPage([ready, failed]),
      [adminDocKey('POST', failed.document_id, '/retry')]: () => jsonResponse(202, retried),
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Failed doc');
    expect(row('Ready doc').queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await user.click(row('Failed doc').getByRole('button', { name: 'Retry' }));

    expect(await row('Failed doc').findByTestId('status-badge-queued')).toBeInTheDocument();
    expect(api.count(adminDocKey('POST', failed.document_id, '/retry'))).toBe(1);
    const request = api.last(adminDocKey('POST', failed.document_id, '/retry'))!;
    expect(request.headers.get('Idempotency-Key')).toBeNull(); // only create, replace and confirm use one
    // The requeued document follows its stream.
    await waitFor(() => expect(FakeEventSource.open).toHaveLength(1));
    expect(FakeEventSource.open[0]!.url).toContain(`${failed.document_id}/events`);
  });

  it('fe_adm_09_a_409_not_retryable_shows_the_catalog_message_and_refreshes_the_list', async () => {
    const api = mockApi({
      ...adminBase,
      [ADMIN_LIST]: () => adminPage([failed]),
      [adminDocKey('POST', failed.document_id, '/retry')]: () =>
        errorResponse(409, 'DOCUMENT_NOT_RETRYABLE', 'job 7 is leased'),
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Failed doc');
    await user.click(row('Failed doc').getByRole('button', { name: 'Retry' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(ADMIN_ERROR_CATALOGS.en.DOCUMENT_NOT_RETRYABLE);
    expect(alert).not.toHaveTextContent('leased');
    await waitFor(() => expect(api.count(ADMIN_LIST)).toBeGreaterThan(1));
  });
});

describe('FE-ADM-05/06 live status in the list', () => {
  it('fe_adm_06_status_events_update_the_stage_and_the_failure_reason_with_retry', async () => {
    mockApi({ ...adminBase, [ADMIN_LIST]: () => adminPage([queued]) });
    renderApp('/admin/documents');
    await screen.findByText('Queued doc');
    await waitFor(() => expect(FakeEventSource.open).toHaveLength(1));
    const source = FakeEventSource.open[0]!;
    const base = { document_id: queued.document_id, revision_id: queued.revision_id };

    source.emit('status', {
      ...base,
      status: 'processing',
      phase: 'extracting',
      can_retry: false,
      can_replace: false,
    });
    expect(await row('Queued doc').findByTestId('status-badge-processing')).toHaveTextContent(
      'Extracting text',
    );
    source.emit('status', {
      ...base,
      status: 'processing',
      phase: 'embedding',
      can_retry: false,
      can_replace: false,
    });
    await waitFor(() =>
      expect(row('Queued doc').getByTestId('status-badge-processing')).toHaveTextContent(
        'Preparing for search',
      ),
    );

    source.emit('status', {
      ...base,
      status: 'failed',
      phase: null,
      failure_code: 'NO_EXTRACTABLE_TEXT',
      failure_message: 'server text',
      delivery_state: 'failed',
      can_retry: true,
      can_replace: true,
    });
    expect(await row('Queued doc').findByTestId('failure-reason')).toHaveTextContent(
      'selectable text',
    );
    expect(row('Queued doc').getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    source.emit('end', { reason: 'terminal' });
    expect(source.closed).toBe(true);
  });

  it('fe_adm_06_a_terminal_end_refetches_the_list_from_the_database', async () => {
    let calls = 0;
    mockApi({
      ...adminBase,
      [ADMIN_LIST]: () =>
        adminPage(
          ++calls === 1
            ? [queued]
            : [{ ...queued, status: 'ready', page_count: 7, delivery_state: 'done' }],
        ),
    });
    renderApp('/admin/documents');
    await screen.findByText('Queued doc');
    await waitFor(() => expect(FakeEventSource.open).toHaveLength(1));
    FakeEventSource.open[0]!.emit('end', { reason: 'terminal' });
    expect(await row('Queued doc').findByTestId('status-badge-ready')).toBeInTheDocument();
    expect(row('Queued doc').getByText(/7 pages/)).toBeInTheDocument();
    expect(FakeEventSource.open).toHaveLength(0); // a ready document has no stream
  });
});

describe('FE-ADM-07 edit access', () => {
  it('fe_adm_07_is_prefilled_requires_a_department_and_patches_the_chosen_ids_then_refetches', async () => {
    const doc = { ...ready, allowed_departments: [A, C] };
    const api = mockApi({
      ...adminBase,
      [ADMIN_LIST]: () => adminPage([doc]),
      [adminDocKey('PATCH', doc.document_id, '/access')]: () =>
        jsonResponse(200, { ...doc, allowed_departments: [A, B] }),
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');
    await user.click(row('Ready doc').getByRole('button', { name: 'Edit access' }));

    const dialog = await screen.findByRole('dialog', { name: 'Edit access' });
    expect(within(dialog).getByText(/does not reprocess/i)).toBeInTheDocument();
    const boxA = await within(dialog).findByLabelText(A.name);
    expect(boxA).toBeChecked();
    expect(within(dialog).getByLabelText(B.name)).not.toBeChecked();
    expect(within(dialog).getByLabelText(C.name)).toBeChecked();

    await user.click(within(dialog).getByLabelText(C.name));
    await user.click(within(dialog).getByLabelText(B.name));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const request = api.last(adminDocKey('PATCH', doc.document_id, '/access'))!;
    expect(await request.json()).toEqual({ allowed_department_ids: [A.id, B.id] });
    expect(api.count(ADMIN_LIST)).toBeGreaterThan(1);
  });

  it('fe_adm_07_saving_with_no_department_is_blocked_with_an_inline_message_and_no_request', async () => {
    const doc = { ...ready, allowed_departments: [A] };
    const api = mockApi({ ...adminBase, [ADMIN_LIST]: () => adminPage([doc]) });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');
    await user.click(row('Ready doc').getByRole('button', { name: 'Edit access' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByLabelText(A.name));
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Choose at least one department',
    );
    expect(api.count(adminDocKey('PATCH', doc.document_id, '/access'))).toBe(0);
  });

  it('fe_adm_09_a_422_keeps_the_dialog_open_with_the_catalog_message', async () => {
    const doc = { ...ready, allowed_departments: [A] };
    mockApi({
      ...adminBase,
      [ADMIN_LIST]: () => adminPage([doc]),
      [adminDocKey('PATCH', doc.document_id, '/access')]: () =>
        errorResponse(422, 'UNKNOWN_DEPARTMENT', 'department 9 does not exist'),
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');
    await user.click(row('Ready doc').getByRole('button', { name: 'Edit access' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByLabelText(A.name);
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(
      await within(dialog).findByText(ADMIN_ERROR_CATALOGS.en.UNKNOWN_DEPARTMENT),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/department 9/)).not.toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('closes_on_escape_and_gives_focus_back_to_the_opening_button', async () => {
    mockApi({ ...adminBase, [ADMIN_LIST]: () => adminPage([ready]) });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');
    const opener = row('Ready doc').getByRole('button', { name: 'Edit access' });
    await user.click(opener);
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });
});

describe('FE-ADM-08 delete', () => {
  it('fe_adm_08_cancel_does_nothing_and_confirm_deletes_then_refreshes_the_list', async () => {
    let deleted = false;
    const api = mockApi({
      ...adminBase,
      [ADMIN_LIST]: () => adminPage(deleted ? [] : [ready]),
      [adminDocKey('DELETE', ready.document_id)]: () => {
        deleted = true;
        return new Response(null, { status: 204 });
      },
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');

    await user.click(row('Ready doc').getByRole('button', { name: 'Delete' }));
    let dialog = await screen.findByRole('dialog', { name: 'Delete document' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.count(adminDocKey('DELETE', ready.document_id))).toBe(0);

    await user.click(row('Ready doc').getByRole('button', { name: 'Delete' }));
    dialog = await screen.findByRole('dialog', { name: 'Delete document' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(await screen.findByTestId('admin-empty')).toBeInTheDocument();
    expect(api.count(adminDocKey('DELETE', ready.document_id))).toBe(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('fe_adm_08_a_404_shows_the_catalog_message_in_the_dialog', async () => {
    mockApi({
      ...adminBase,
      [ADMIN_LIST]: () => adminPage([ready]),
      [adminDocKey('DELETE', ready.document_id)]: () =>
        errorResponse(404, 'DOCUMENT_NOT_FOUND', 'x'),
    });
    const { user } = renderApp('/admin/documents');
    await screen.findByText('Ready doc');
    await user.click(row('Ready doc').getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      ADMIN_ERROR_CATALOGS.en.DOCUMENT_NOT_FOUND,
    );
  });
});
