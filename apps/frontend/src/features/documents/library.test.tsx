import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  DEPARTMENTS,
  DEPARTMENTS_LIST,
  ME,
  SET_DEPARTMENT,
  departmentsOk,
  errorResponse,
  jsonResponse,
  makeIdentity,
  mockApi,
} from '@/test/fake-api';
import { renderApp } from '@/test/render';
import { CATALOGS, libraryCatalog, libraryErrorMessage } from './library-messages';
import { ApiError } from '@/lib/api/errors';

const [A, B] = DEPARTMENTS;
if (!A || !B) throw new Error('fixture needs departments');

const DOCS = 'GET /v1/documents';

function doc(n: number, owner: { id: string; name: string } | undefined = DEPARTMENTS[0]) {
  return {
    id: `00000000-0000-4000-8000-00000000000${n}`,
    title: `Handbook ${n}`,
    filename: `handbook-${n}.pdf`,
    page_count: n + 1,
    owner_department: { id: owner?.id ?? '', name: owner?.name ?? '' },
  };
}

function page(items: ReturnType<typeof doc>[], next: string | null = null) {
  return jsonResponse(200, { items, has_more: next !== null, next_cursor: next });
}

const base = {
  [ME]: () => jsonResponse(200, makeIdentity({ active_department: A })),
  [DEPARTMENTS_LIST]: departmentsOk,
};

function lastQuery(api: ReturnType<typeof mockApi>) {
  const request = api.last(DOCS);
  return request ? new URL(request.url).searchParams : new URLSearchParams();
}

describe('FE-DOC-01/02/04/05 library states and items', () => {
  it('fe_doc_04_05_items_show_filename_and_owner_department_and_link_to_the_viewer', async () => {
    mockApi({ ...base, [DOCS]: () => page([doc(1, B)]) });
    const { user } = renderApp('/documents');
    const link = await screen.findByRole('link', { name: /Handbook 1/ });
    expect(link).toHaveTextContent('handbook-1.pdf');
    expect(link).toHaveTextContent(`Owner department: ${B.name}`);
    expect(link).not.toHaveTextContent(/access/i);
    expect(link).toHaveAttribute('href', `/documents/${doc(1).id}`);
    await user.click(link);
    expect(await screen.findByTestId('location')).toHaveTextContent(`/documents/${doc(1).id}`);
  });

  it('fe_doc_02_shows_loading_then_the_empty_message', async () => {
    mockApi({ ...base, [DOCS]: () => page([]) });
    renderApp('/documents');
    expect(await screen.findByText('Loading documents...')).toBeInTheDocument();
    expect(await screen.findByTestId('library-empty')).toHaveTextContent(
      'No documents are available in this department.',
    );
  });

  it('fe_doc_02_prod_13_errors_render_a_friendly_message_never_the_api_text', async () => {
    mockApi({
      ...base,
      [DOCS]: () => errorResponse(503, 'SERVICE_UNAVAILABLE', 'psycopg2 OperationalError at db-7'),
    });
    renderApp('/documents');
    const alert = await screen.findByTestId('library-error');
    expect(alert).toHaveTextContent('temporarily unavailable');
    expect(alert).not.toHaveTextContent(/psycopg2|OperationalError|db-7|SERVICE_UNAVAILABLE/);
  });

  it('fe_arch_14_error_code_maps_to_a_catalog_message_with_a_generic_fallback', () => {
    const text = libraryCatalog();
    const make = (code: string, status = 400) => new ApiError({ code, message: 'raw', status });
    expect(libraryErrorMessage(make('NETWORK_ERROR', 0))).toBe(text.errors.NETWORK_ERROR);
    expect(libraryErrorMessage(make('X', 429))).toBe(text.errors.RATE_LIMITED);
    expect(libraryErrorMessage(make('X', 422))).toBe(text.errors.VALIDATION_ERROR);
    expect(libraryErrorMessage(make('ACTIVE_DEPARTMENT_REQUIRED', 409))).toBe(
      text.errors.ACTIVE_DEPARTMENT_REQUIRED,
    );
    expect(libraryErrorMessage(make('SOMETHING_NEW'))).toBe(text.errors.generic);
    expect(libraryErrorMessage(new Error('boom'))).toBe(text.errors.generic);
    expect(libraryErrorMessage(make('SOMETHING_NEW'))).not.toContain('raw');
  });

  it('fe_arch_14_an_unknown_selected_language_falls_back_to_english', () => {
    expect(libraryCatalog('xx')).toBe(CATALOGS.en);
  });
});

describe('FE-DOC-03/06 search and owner filter', () => {
  it('fe_doc_03_search_and_owner_filter_are_sent_together_and_options_come_from_the_api', async () => {
    const api = mockApi({ ...base, [DOCS]: () => page([doc(1)]) });
    const { user } = renderApp('/documents');
    await screen.findByRole('link', { name: /Handbook 1/ });
    const select = screen.getByLabelText('Owner department');
    for (const department of DEPARTMENTS) {
      expect(
        await within(select).findByRole('option', { name: department.name }),
      ).toBeInTheDocument();
    }
    await user.selectOptions(select, B.id);
    await user.type(screen.getByLabelText('Search documents'), 'policy');
    await waitFor(() => {
      expect(lastQuery(api).get('q')).toBe('policy');
      expect(lastQuery(api).get('owner_department_id')).toBe(B.id);
    });
  });

  it('fe_doc_06_a_filter_with_no_hits_shows_the_no_match_message', async () => {
    mockApi({
      ...base,
      [DOCS]: (request) => (new URL(request.url).searchParams.get('q') ? page([]) : page([doc(1)])),
    });
    const { user } = renderApp('/documents');
    await screen.findByRole('link', { name: /Handbook 1/ });
    await user.type(screen.getByLabelText('Search documents'), 'zzz');
    expect(await screen.findByTestId('library-no-match')).toHaveTextContent(
      'No documents match your search.',
    );
    expect(screen.queryByTestId('library-empty')).not.toBeInTheDocument();
  });
});

describe('FE-DOC-10 cursor paging', () => {
  function pagedApi() {
    return mockApi({
      ...base,
      [DOCS]: (request) => {
        const params = new URL(request.url).searchParams;
        if (params.get('owner_department_id')) return page([doc(9, B)]);
        return params.get('cursor') === 'c2' ? page([doc(3)]) : page([doc(1), doc(2)], 'c2');
      },
    });
  }

  it('fe_doc_10_load_more_appends_the_next_page_and_the_button_disappears_at_the_end', async () => {
    const api = pagedApi();
    const { user } = renderApp('/documents');
    await screen.findByRole('link', { name: /Handbook 2/ });
    expect(lastQuery(api).get('cursor')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByRole('link', { name: /Handbook 3/ });
    expect(lastQuery(api).get('cursor')).toBe('c2');
    expect(screen.getAllByRole('link', { name: /Handbook/ })).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('fe_doc_10_a_filter_change_restarts_from_the_first_page_without_a_cursor', async () => {
    const api = pagedApi();
    const { user } = renderApp('/documents');
    await screen.findByRole('link', { name: /Handbook 2/ });
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByRole('link', { name: /Handbook 3/ });
    await user.selectOptions(screen.getByLabelText('Owner department'), B.id);
    await screen.findByRole('link', { name: /Handbook 9/ });
    expect(lastQuery(api).get('cursor')).toBeNull();
    expect(screen.queryByRole('link', { name: /Handbook 3/ })).not.toBeInTheDocument();
  });
});

describe('FE-DOC-01 department-keyed cache', () => {
  it('fe_doc_01_the_query_key_carries_identity_and_department_and_a_switch_never_shows_the_old_list', async () => {
    let current = A;
    const api = mockApi({
      ...base,
      [SET_DEPARTMENT]: () => {
        current = B;
        return jsonResponse(200, makeIdentity({ active_department: B }));
      },
      [DOCS]: () => page([current === A ? doc(1) : doc(2, B)]),
    });
    const { user, client } = renderApp('/documents');
    await screen.findByRole('link', { name: /Handbook 1/ });
    const userId = makeIdentity().user_id;
    expect(
      client.getQueryCache().findAll({ queryKey: ['dept', userId, A.id, 'documents'] }).length,
    ).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Change department' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', { name: B.name }));
    await screen.findByRole('link', { name: /Handbook 2/ });
    expect(screen.queryByRole('link', { name: /Handbook 1/ })).not.toBeInTheDocument();
    expect(client.getQueryCache().findAll({ queryKey: ['dept', userId, A.id] })).toHaveLength(0);
    expect(
      client.getQueryCache().findAll({ queryKey: ['dept', userId, B.id, 'documents'] }).length,
    ).toBeGreaterThan(0);
    expect(api.count(DOCS)).toBe(2);
  });
});

describe('dashboard entry', () => {
  it('fe_doc_05_the_dashboard_links_to_the_library', async () => {
    mockApi({ ...base, [DOCS]: () => page([]) });
    const { user } = renderApp('/dashboard');
    await user.click(await screen.findByTestId('library-link'));
    expect(await screen.findByTestId('library-page')).toBeInTheDocument();
  });
});
