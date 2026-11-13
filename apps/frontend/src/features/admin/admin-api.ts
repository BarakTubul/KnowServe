import {
  call,
  createApiClient,
  multipartBody,
  resolveBaseUrl,
  type ApiClient,
} from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

export type AdminDocument = components['schemas']['AdminDocumentOut'];
export type AdminDocumentPage = components['schemas']['AdminDocumentList'];
export type DocumentStatus = AdminDocument['status'];
export type ImportPreview = components['schemas']['ImportPreviewResponse'];
export type ImportEntryPreview = components['schemas']['ImportEntryPreview'];
export type ImportConfirmation = components['schemas']['ImportConfirmResponse'];
export type ImportEntryResult = components['schemas']['ImportEntryResult'];

export const ADMIN_PAGE_SIZE = 20;

export interface ListAdminDocumentsParams {
  q: string;
  status: DocumentStatus | '';
  cursor: string | null;
  limit?: number;
}

/** `GET /v1/admin/documents` (ADM-02): every non-deleted document with its latest revision. */
export function listAdminDocuments(
  params: ListAdminDocumentsParams,
  client: ApiClient = createApiClient(),
): Promise<AdminDocumentPage> {
  return call<AdminDocumentPage>(() =>
    client.GET('/v1/admin/documents', {
      params: {
        query: {
          q: params.q || null,
          status: params.status || null,
          cursor: params.cursor,
          limit: params.limit ?? ADMIN_PAGE_SIZE,
        },
      },
    }),
  );
}

/** `PATCH .../access` (ADM-07): replaces the allowed departments. No job, no reprocessing. */
export function updateAccess(
  documentId: string,
  allowedDepartmentIds: string[],
  client: ApiClient = createApiClient(),
): Promise<AdminDocument> {
  return call<AdminDocument>(() =>
    client.PATCH('/v1/admin/documents/{document_id}/access', {
      params: { path: { document_id: documentId } },
      body: { allowed_department_ids: allowedDepartmentIds },
    }),
  );
}

/** `DELETE /v1/admin/documents/{id}` (ADM-08): a soft delete. */
export function deleteAdminDocument(
  documentId: string,
  client: ApiClient = createApiClient(),
): Promise<void> {
  return call<void>(
    () =>
      client.DELETE('/v1/admin/documents/{document_id}', {
        params: { path: { document_id: documentId } },
      }),
    { empty: true },
  );
}

/** `POST .../retry` (ADM-16). No body and no idempotency key; the server re-checks the precondition. */
export function retryAdminDocument(
  documentId: string,
  client: ApiClient = createApiClient(),
): Promise<AdminDocument> {
  return call<AdminDocument>(() =>
    client.POST('/v1/admin/documents/{document_id}/retry', {
      params: { path: { document_id: documentId } },
    }),
  );
}

export interface UploadDocumentInput {
  file: File;
  title: string;
  ownerDepartmentId: string;
  allowedDepartmentIds: string[];
}

/** `POST /v1/admin/documents` (ADM-03): multipart with one `Idempotency-Key` per user action. */
export function uploadDocument(
  input: UploadDocumentInput,
  idempotencyKey: string,
  client: ApiClient = createApiClient(),
): Promise<AdminDocument> {
  const fields: [string, string | Blob][] = [
    ['file', input.file],
    ['title', input.title],
    ['owner_department_id', input.ownerDepartmentId],
    ...input.allowedDepartmentIds.map((id): [string, string] => ['allowed_department_ids', id]),
  ];
  return call<AdminDocument>(() =>
    client.POST('/v1/admin/documents', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      body: multipartBody(fields),
    }),
  );
}

/** `POST .../replace` (ADM-18): a new file for a failed document. Same idempotency rules as upload. */
export function replaceDocumentFile(
  documentId: string,
  file: File,
  idempotencyKey: string,
  client: ApiClient = createApiClient(),
): Promise<AdminDocument> {
  return call<AdminDocument>(() =>
    client.POST('/v1/admin/documents/{document_id}/replace', {
      params: { path: { document_id: documentId }, header: { 'Idempotency-Key': idempotencyKey } },
      body: multipartBody([['file', file]]),
    }),
  );
}

/** `POST /v1/admin/imports/preview` (ADM-12): validates the ZIP and creates nothing. */
export function previewImport(
  file: File,
  client: ApiClient = createApiClient(),
): Promise<ImportPreview> {
  return call<ImportPreview>(() =>
    client.POST('/v1/admin/imports/preview', { body: multipartBody([['file', file]]) }),
  );
}

/** `POST /v1/admin/imports/confirm` (ADM-13): the same ZIP again, with the key of this confirmation. */
export function confirmImport(
  file: File,
  idempotencyKey: string,
  client: ApiClient = createApiClient(),
): Promise<ImportConfirmation> {
  return call<ImportConfirmation>(() =>
    client.POST('/v1/admin/imports/confirm', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      body: multipartBody([['file', file]]),
    }),
  );
}

/** URL of the status stream of one document (ING-07). Same origin as the API client, so cookies apply. */
export function documentEventsUrl(documentId: string): string {
  return `${resolveBaseUrl()}/v1/admin/documents/${encodeURIComponent(documentId)}/events`;
}
