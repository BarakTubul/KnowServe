import { createApiClient } from '@/lib/api/client';
import { ApiError, parseApiError } from '@/lib/api/errors';
import { emitApiError } from '@/lib/api/events';
import type { components } from '@/lib/api/schema';

export type DocumentListItem = components['schemas']['DocumentListItem'];
export type DocumentPage = components['schemas']['DocumentListResponse'];

export const PAGE_SIZE = 20;

export interface ListDocumentsParams {
  q: string;
  ownerDepartmentId: string;
  cursor: string | null;
  limit?: number;
}

/**
 * `GET /v1/documents` over the generated client. Failures become ApiError and go to the global
 * handler (401/409/429/503), as the shared client does; kept here because that helper is not exported.
 */
export async function listDocuments(params: ListDocumentsParams): Promise<DocumentPage> {
  const client = createApiClient();
  let result;
  try {
    result = await client.GET('/v1/documents', {
      params: {
        query: {
          q: params.q || null,
          owner_department_id: params.ownerDepartmentId || null,
          cursor: params.cursor,
          limit: params.limit ?? PAGE_SIZE,
        },
      },
    });
  } catch {
    const error = new ApiError({ code: 'NETWORK_ERROR', message: 'network', status: 0 });
    emitApiError(error);
    throw error;
  }
  if (result.response.ok && result.data) return result.data;
  const error = parseApiError(
    result.response.status,
    result.error,
    result.response.headers.get('X-Request-ID'),
    result.response.headers.get('Retry-After'),
  );
  emitApiError(error);
  throw error;
}
