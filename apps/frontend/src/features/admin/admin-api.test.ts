import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { setCsrfToken } from '@/lib/api/csrf';
import { ApiError } from '@/lib/api/errors';
import { errorResponse, jsonResponse, makeAdminDocument, mockApi } from '@/test/fake-api';
import { confirmImport, replaceDocumentFile, uploadDocument } from './admin-api';
import { ADMIN_ERROR_CATALOGS, describeAdminError } from './admin-error-messages';
import { fileFingerprint, useActionKey } from './use-action-key';

const DOC = makeAdminDocument({ status: 'queued' });
const KEY = /^[A-Za-z0-9_-]{8,128}$/;

function pdf(name = 'a.pdf', content = '%PDF-1.4 test') {
  return new File([content], name, { type: 'application/pdf' });
}

describe('FE-ADM-04 multipart helper and Idempotency-Key', () => {
  it('fe_adm_04_upload_sends_multipart_with_the_key_the_csrf_token_and_repeated_department_ids', async () => {
    setCsrfToken('csrf-1');
    const api = mockApi({ 'POST /v1/admin/documents': () => jsonResponse(202, DOC) });
    const result = await uploadDocument(
      {
        file: pdf('leave.pdf'),
        title: 'Leave policy',
        ownerDepartmentId: 'owner-id',
        allowedDepartmentIds: ['dept-1', 'dept-2'],
      },
      'key-12345678',
    );
    expect(result.document_id).toBe(DOC.document_id);

    const request = api.last('POST /v1/admin/documents')!;
    expect(request.headers.get('Idempotency-Key')).toBe('key-12345678');
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf-1');
    // The browser sets the boundary; the client must not set a JSON content type.
    expect(request.headers.get('Content-Type')).toMatch(/^multipart\/form-data; boundary=/);
    const form = await request.formData();
    expect(form.get('title')).toBe('Leave policy');
    expect(form.get('owner_department_id')).toBe('owner-id');
    expect(form.getAll('allowed_department_ids')).toEqual(['dept-1', 'dept-2']);
    const file = form.get('file');
    // (jsdom's FormData loses the file name when undici re-reads it; a browser keeps it.)
    expect(await (file as File).text()).toBe('%PDF-1.4 test');
  });

  it('fe_adm_13_replace_and_import_confirm_carry_their_own_key', async () => {
    const api = mockApi({
      [`POST /v1/admin/documents/${DOC.document_id}/replace`]: () => jsonResponse(202, DOC),
      'POST /v1/admin/imports/confirm': () =>
        jsonResponse(200, { created_count: 0, rejected_count: 0, results: [] }),
    });
    await replaceDocumentFile(DOC.document_id, pdf(), 'replace-key-1');
    await confirmImport(pdf('batch.zip', 'PK'), 'confirm-key-1');
    expect(
      api
        .last(`POST /v1/admin/documents/${DOC.document_id}/replace`)!
        .headers.get('Idempotency-Key'),
    ).toBe('replace-key-1');
    expect(api.last('POST /v1/admin/imports/confirm')!.headers.get('Idempotency-Key')).toBe(
      'confirm-key-1',
    );
  });
});

describe('one Idempotency-Key per user action', () => {
  it('reuses_the_key_for_a_retry_of_the_same_request_and_changes_it_for_a_different_one', () => {
    const { result } = renderHook(() => useActionKey());
    const first = result.current.keyFor('file-a');
    expect(first).toMatch(KEY);
    expect(result.current.keyFor('file-a')).toBe(first); // a retry after a timeout
    const second = result.current.keyFor('file-b'); // different content: a new action
    expect(second).not.toBe(first);
    expect(result.current.keyFor('file-b')).toBe(second);
  });

  it('starts_a_new_action_after_reset_even_for_identical_content', () => {
    const { result } = renderHook(() => useActionKey());
    const first = result.current.keyFor('same');
    result.current.reset();
    expect(result.current.keyFor('same')).not.toBe(first);
  });

  it('fingerprints_a_file_by_name_size_and_modified_time', () => {
    const a = new File(['abc'], 'a.pdf', { lastModified: 1 });
    expect(fileFingerprint(a)).toBe(
      fileFingerprint(new File(['abc'], 'a.pdf', { lastModified: 1 })),
    );
    expect(fileFingerprint(a)).not.toBe(
      fileFingerprint(new File(['abcd'], 'a.pdf', { lastModified: 1 })),
    );
  });
});

describe('FE-ADM-09 error mapping (PROD-13)', () => {
  const he = (code: string) =>
    describeAdminError(new ApiError({ code, message: 'raw', status: 422 }), 'he');

  it('maps_every_known_code_to_its_catalog_text_in_both_languages', () => {
    for (const code of Object.keys(ADMIN_ERROR_CATALOGS.en).filter((c) => c !== 'generic')) {
      const error = new ApiError({ code, message: 'raw server text', status: 422 });
      expect(describeAdminError(error, 'en')).toBe(ADMIN_ERROR_CATALOGS.en[code as 'FILE_EMPTY']);
      expect(describeAdminError(error, 'he')).toBe(ADMIN_ERROR_CATALOGS.he[code as 'FILE_EMPTY']);
    }
  });

  it('uses_the_generic_text_for_unknown_codes_and_non_api_errors_and_never_the_raw_message', () => {
    const unknown = new ApiError({
      code: 'SOMETHING_NEW',
      message: 'Traceback at db-7',
      status: 500,
    });
    expect(describeAdminError(unknown)).toBe(ADMIN_ERROR_CATALOGS.en.generic);
    expect(describeAdminError(new TypeError('boom'))).toBe(ADMIN_ERROR_CATALOGS.en.generic);
    expect(he('SOMETHING_NEW')).toBe(ADMIN_ERROR_CATALOGS.he.generic);
  });

  it('reads_a_413_from_the_proxy_without_our_envelope_as_file_too_large', async () => {
    mockApi({
      'POST /v1/admin/documents': () => new Response('Request Entity Too Large', { status: 413 }),
    });
    const error = await uploadDocument(
      { file: pdf(), title: 't', ownerDepartmentId: 'o', allowedDepartmentIds: ['d'] },
      'key-12345678',
    ).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(describeAdminError(error)).toBe(ADMIN_ERROR_CATALOGS.en.FILE_TOO_LARGE);
  });

  it('maps_a_network_failure_and_an_uploads_disabled_503', async () => {
    mockApi({ 'POST /v1/admin/documents': () => errorResponse(503, 'UPLOADS_DISABLED', 'off') });
    const error = await uploadDocument(
      { file: pdf(), title: 't', ownerDepartmentId: 'o', allowedDepartmentIds: ['d'] },
      'key-12345678',
    ).catch((e: unknown) => e);
    expect(describeAdminError(error)).toBe(ADMIN_ERROR_CATALOGS.en.UPLOADS_DISABLED);
    expect(
      describeAdminError(new ApiError({ code: 'NETWORK_ERROR', message: 'x', status: 0 })),
    ).toBe(ADMIN_ERROR_CATALOGS.en.NETWORK_ERROR);
  });
});
