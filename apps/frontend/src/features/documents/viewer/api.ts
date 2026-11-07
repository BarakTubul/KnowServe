import { createApiClient, resolveBaseUrl } from '@/lib/api/client';
import { ApiError, parseApiError } from '@/lib/api/errors';
import { emitApiError } from '@/lib/api/events';
import type { components } from '@/lib/api/schema';

export type DocumentMetadata = components['schemas']['DocumentMetadata'];

/** The only URL the viewer loads PDF bytes from (FE-DOC-07, DOC-04): the API, never storage. */
export function documentContentUrl(id: string): string {
  return `${resolveBaseUrl()}/v1/documents/${encodeURIComponent(id)}/content`;
}

const GLOBAL_STATUSES = new Set([401, 409, 429, 503]);

/** 401/409/429/503 also go to the global handler (FE-AUTH-05). */
export function reportApiError(error: ApiError): ApiError {
  if (GLOBAL_STATUSES.has(error.status)) emitApiError(error);
  return error;
}

export async function getDocumentMetadata(id: string): Promise<DocumentMetadata> {
  const client = createApiClient();
  let result;
  try {
    result = await client.GET('/v1/documents/{document_id}', {
      params: { path: { document_id: id } },
    });
  } catch {
    throw new ApiError({ code: 'NETWORK_ERROR', message: 'network', status: 0 });
  }
  if (result.response.ok && result.data) return result.data;
  throw reportApiError(
    parseApiError(
      result.response.status,
      result.error,
      result.response.headers.get('X-Request-ID'),
      result.response.headers.get('Retry-After'),
    ),
  );
}

/** Maps a pdf.js load failure to an ApiError; pdf.js exposes the HTTP status but not our envelope. */
export function pdfLoadError(error: unknown): ApiError {
  const status =
    typeof error === 'object' && error !== null && 'status' in error
      ? Number((error as { status: unknown }).status)
      : undefined;
  const make = (code: string, s: number) => new ApiError({ code, message: code, status: s });
  if (status === 404) return make('DOCUMENT_NOT_FOUND', 404);
  if (status === 401) return make('UNAUTHENTICATED', 401);
  if (status === 409) return make('ACTIVE_DEPARTMENT_REQUIRED', 409);
  if (status === 429) return make('RATE_LIMITED', 429);
  if (status === 503) return make('SERVICE_UNAVAILABLE', 503);
  if (status === 0 || (error instanceof Error && /network|fetch/i.test(error.message)))
    return make('NETWORK_ERROR', 0);
  if (status === undefined) return make('PDF_UNREADABLE', 0);
  return make('UNEXPECTED_RESPONSE', status);
}
