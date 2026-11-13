import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import { identityKey } from '@/features/auth/auth-context';
import type { Identity } from '@/lib/api/client';
import type { AdminDocument, AdminDocumentPage } from './admin-api';

type Pages = InfiniteData<AdminDocumentPage, string | null>;

/** Admin queries are scoped to the signed-in identity, so a logout clears them (FE-ARCH-04). */
export function adminDocumentsKey(
  identity: Identity | null,
  filters?: { q: string; status: string },
) {
  return filters
    ? identityKey(identity, 'admin-documents', filters)
    : identityKey(identity, 'admin-documents');
}

/** Merge new data for one document into every cached list page that shows it. */
export function patchAdminDocument(
  client: QueryClient,
  identity: Identity | null,
  patch: Partial<AdminDocument> & Pick<AdminDocument, 'document_id'>,
): void {
  client.setQueriesData<Pages>({ queryKey: adminDocumentsKey(identity) }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((item) =>
          item.document_id === patch.document_id ? { ...item, ...patch } : item,
        ),
      })),
    };
  });
}

/** Refetch every admin list: the database is the truth (FE-ADM-06). */
export function refreshAdminDocuments(
  client: QueryClient,
  identity: Identity | null,
): Promise<void> {
  return client.invalidateQueries({ queryKey: adminDocumentsKey(identity) });
}
