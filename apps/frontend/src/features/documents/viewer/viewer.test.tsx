import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ME,
  errorResponse,
  jsonResponse,
  makeIdentity,
  mockApi,
  DEPARTMENTS,
} from '@/test/fake-api';
import { renderApp } from '@/test/render';
import { viewerCatalog, viewerMessage } from './messages';

const EN = viewerCatalog('en');
const NOT_AVAILABLE_TITLE = EN.notAvailableTitle;
const GENERIC_MESSAGE = EN.errors.generic;

const ID = '44444444-4444-4444-8444-444444444444';
const META = 'GET /v1/documents/' + ID;
const META_BODY = {
  id: ID,
  title: 'Travel policy',
  filename: 'travel-policy.pdf',
  page_count: 5,
  owner_department: { id: DEPARTMENTS[0]?.id, name: DEPARTMENTS[0]?.name },
};

// react-pdf is replaced by a fake that records the `file` it was given (pdf.js itself needs a real
// worker and canvas, which jsdom lacks). The fake can fail the way pdf.js does: with an HTTP status.
const pdf = vi.hoisted(() => ({
  files: [] as unknown[],
  failWith: null as unknown,
}));

vi.mock('react-pdf', async () => {
  const React = await import('react');
  return {
    pdfjs: { GlobalWorkerOptions: {} },
    Document: (props: {
      file: unknown;
      options?: unknown;
      onLoadSuccess?: (p: { numPages: number }) => void;
      onLoadError?: (e: unknown) => void;
      children?: React.ReactNode;
    }) => {
      pdf.files.push({ ...(props.file as object), ...(props.options as object) });
      React.useEffect(() => {
        if (pdf.failWith) props.onLoadError?.(pdf.failWith);
        else props.onLoadSuccess?.({ numPages: 5 });
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, []);
      return pdf.failWith ? null : React.createElement('div', null, props.children);
    },
    Page: (props: { pageNumber: number }) =>
      React.createElement(
        'div',
        { 'data-testid': 'pdf-page' },
        `rendered page ${props.pageNumber}`,
      ),
  };
});

beforeEach(() => {
  pdf.files = [];
  pdf.failWith = null;
});

function api(meta: () => Response = () => jsonResponse(200, META_BODY)) {
  return mockApi({ [ME]: () => jsonResponse(200, makeIdentity()), [META]: meta });
}

describe('FE-DOC-07 viewer loads bytes only from the API', () => {
  it('fe_doc_07_requests_only_the_api_bytes_url_with_credentials', async () => {
    const calls = api();
    renderApp(`/documents/${ID}`);
    expect(await screen.findByTestId('pdf-page')).toBeInTheDocument();
    expect(pdf.files).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ url: `/api/v1/documents/${ID}/content`, withCredentials: true }),
      ]),
    );
    for (const file of pdf.files) {
      expect((file as { url: string }).url).toMatch(/^\/api\/v1\/documents\/[0-9a-f-]+\/content$/);
    }
    // Every request the page made went to the API (no storage or public URL).
    for (const call of calls.calls) expect(new URL(call.request.url).pathname).toMatch(/^\/api\//);
  });
});

describe('FE-DOC-08 page navigation and ?page= sync', () => {
  it('fe_doc_08_opens_page_3_and_next_moves_to_page_4_in_the_url', async () => {
    api();
    const { user } = renderApp(`/documents/${ID}?page=3`);
    expect(await screen.findByText('rendered page 3')).toBeInTheDocument();
    expect(screen.getByTestId('viewer-filename')).toHaveTextContent('travel-policy.pdf');
    expect(screen.getByTestId('viewer-header-page')).toHaveTextContent('Page 3 of 5');
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByText('rendered page 4')).toBeInTheDocument();
    expect(screen.getByTestId('viewer-header-page')).toHaveTextContent('Page 4 of 5');
  });

  it('fe_doc_08_zoom_changes_the_shown_percentage', async () => {
    api();
    const { user } = renderApp(`/documents/${ID}`);
    await screen.findByTestId('pdf-page');
    expect(screen.getByTestId('viewer-zoom')).toHaveTextContent('100%');
    await user.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByTestId('viewer-zoom')).toHaveTextContent('125%');
  });

  it('fe_doc_08_an_out_of_range_page_shows_an_inline_notice_and_the_nearest_page', async () => {
    api();
    renderApp(`/documents/${ID}?page=99`);
    expect(await screen.findByTestId('viewer-page-notice')).toHaveTextContent('Showing page 5');
    expect(await screen.findByText('rendered page 5')).toBeInTheDocument();
  });

  it('fe_doc_08_a_non_numeric_page_falls_back_to_page_1_with_the_notice', async () => {
    api();
    renderApp(`/documents/${ID}?page=abc`);
    expect(await screen.findByTestId('viewer-page-notice')).toBeInTheDocument();
    expect(await screen.findByText('rendered page 1')).toBeInTheDocument();
  });
});

describe('FE-DOC-09 neutral not-available view', () => {
  it('fe_doc_09_metadata_404_shows_the_neutral_view', async () => {
    api(() => errorResponse(404, 'DOCUMENT_NOT_FOUND', 'Document not found'));
    renderApp(`/documents/${ID}`);
    expect(await screen.findByText(NOT_AVAILABLE_TITLE)).toBeInTheDocument();
    expect(screen.queryByTestId('pdf-page')).not.toBeInTheDocument();
  });

  it('fe_doc_09_bytes_404_shows_the_same_neutral_view', async () => {
    api();
    pdf.failWith = { status: 404, name: 'ResponseException' };
    renderApp(`/documents/${ID}`);
    const bytes = await screen.findByTestId('viewer-not-available');
    expect(bytes).toHaveTextContent(NOT_AVAILABLE_TITLE);
  });

  it('fe_doc_09_the_404_view_is_identical_for_every_cause', async () => {
    api(() => errorResponse(404, 'DOCUMENT_NOT_FOUND', 'x'));
    const first = renderApp(`/documents/${ID}`);
    const a = (await screen.findByTestId('viewer-not-available')).innerHTML;
    first.unmount();
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity()),
      [META]: () => errorResponse(404, 'SOMETHING_ELSE', 'other message'),
    });
    renderApp(`/documents/${ID}`);
    expect((await screen.findByTestId('viewer-not-available')).innerHTML).toBe(a);
  });
});

describe('FE-ARCH-14 / PROD-13 friendly error mapping', () => {
  it('fe_arch_14_503_shows_the_catalog_message_never_the_raw_error', async () => {
    api(() => errorResponse(503, 'SERVICE_UNAVAILABLE', 'psycopg stack trace boom'));
    renderApp(`/documents/${ID}`);
    const view = await screen.findByTestId('viewer-error');
    expect(view).toHaveTextContent(viewerMessage('SERVICE_UNAVAILABLE'));
    expect(view).not.toHaveTextContent('psycopg');
  });

  it('fe_arch_14_an_unknown_code_shows_the_generic_message', async () => {
    api(() => errorResponse(500, 'WEIRD_NEW_CODE', 'internal detail'));
    renderApp(`/documents/${ID}`);
    const view = await screen.findByTestId('viewer-error');
    expect(view).toHaveTextContent(GENERIC_MESSAGE);
    expect(view).not.toHaveTextContent('internal detail');
  });

  it('fe_arch_14_a_network_failure_shows_the_connection_message', async () => {
    api();
    pdf.failWith = new Error('Failed to fetch');
    renderApp(`/documents/${ID}`);
    expect(await screen.findByTestId('viewer-error')).toHaveTextContent(
      viewerMessage('NETWORK_ERROR'),
    );
  });

  it('fe_arch_14_an_unreadable_pdf_shows_a_friendly_message', async () => {
    api();
    pdf.failWith = { name: 'InvalidPDFException', message: 'Invalid PDF structure.' };
    renderApp(`/documents/${ID}`);
    const view = await screen.findByTestId('viewer-error');
    expect(view).toHaveTextContent(viewerMessage('PDF_UNREADABLE'));
    expect(view).not.toHaveTextContent('Invalid PDF structure');
  });
});
