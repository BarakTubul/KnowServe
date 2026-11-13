import { useInfiniteQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import { AccessEditor } from './access-editor';
import { listAdminDocuments, type AdminDocument, type DocumentStatus } from './admin-api';
import { adminDocumentsKey } from './admin-cache';
import { describeAdminError } from './admin-error-messages';
import { STATUS_LABEL, adminText } from './admin-text';
import { DeleteDialog } from './delete-dialog';
import { DocumentRow } from './document-row';
import { ImportPanel } from './import/import-panel';
import { ReplaceDialog } from './upload/replace-dialog';
import { UploadForm } from './upload/upload-form';
import { uploadText } from './upload/upload-text';

const SEARCH_DEBOUNCE_MS = 250;
const STATUSES: DocumentStatus[] = ['queued', 'processing', 'ready', 'failed'];

function useDebounced(value: string, delayMs: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/** Admin document list (FE-ADM-02): every document, newest first, with status, owner and access. */
export function AdminDocumentsPage() {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<DocumentStatus | ''>('');
  const [editing, setEditing] = useState<AdminDocument | null>(null);
  const [deleting, setDeleting] = useState<AdminDocument | null>(null);
  const [replacing, setReplacing] = useState<AdminDocument | null>(null);
  const [panel, setPanel] = useState<'upload' | 'import' | null>(null);
  const q = useDebounced(search.trim(), SEARCH_DEBOUNCE_MS);

  const documents = useInfiniteQuery({
    queryKey: adminDocumentsKey(identity, { q, status }),
    queryFn: ({ pageParam }) => listAdminDocuments({ q, status, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.has_more && last.next_cursor ? last.next_cursor : undefined),
    enabled: identity !== null,
  });

  const items = documents.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = q !== '' || status !== '';

  return (
    <main data-testid="admin-documents-page" className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{adminText.title}</h1>
        <Link to="/dashboard" className="text-sm underline">
          {adminText.backToDashboard}
        </Link>
      </header>

      <div className="flex flex-wrap gap-2">
        <Button
          variant={panel === 'upload' ? 'default' : 'outline'}
          aria-expanded={panel === 'upload'}
          onClick={() => setPanel(panel === 'upload' ? null : 'upload')}
        >
          {uploadText.open}
        </Button>
        <Button
          variant={panel === 'import' ? 'default' : 'outline'}
          aria-expanded={panel === 'import'}
          onClick={() => setPanel(panel === 'import' ? null : 'import')}
        >
          {uploadText.importer.open}
        </Button>
      </div>
      {panel === 'upload' && <UploadForm />}
      {panel === 'import' && <ImportPanel onClose={() => setPanel(null)} />}

      <div className="flex flex-wrap gap-3">
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          {adminText.searchLabel}
          <Input
            type="search"
            value={search}
            placeholder={adminText.searchPlaceholder}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {adminText.statusFilterLabel}
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as DocumentStatus | '')}
            className="h-9 rounded-md border border-border bg-background px-2 text-sm"
          >
            <option value="">{adminText.allStatuses}</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {STATUS_LABEL[value]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {documents.isPending && <p role="status">{adminText.loading}</p>}
      {documents.isError && (
        <Alert variant="error" data-testid="admin-list-error">
          {describeAdminError(documents.error, language)}{' '}
          <button type="button" className="underline" onClick={() => void documents.refetch()}>
            {adminText.retryLoad}
          </button>
        </Alert>
      )}
      {documents.isSuccess && items.length === 0 && (
        <p data-testid={filtered ? 'admin-no-match' : 'admin-empty'}>
          {filtered ? adminText.noMatch : adminText.empty}
        </p>
      )}
      {items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <DocumentRow
              key={item.document_id}
              document={item}
              onEditAccess={setEditing}
              onDelete={setDeleting}
              onReplace={setReplacing}
            />
          ))}
        </ul>
      )}
      {documents.hasNextPage && (
        <Button
          variant="outline"
          className="self-start"
          disabled={documents.isFetchingNextPage}
          onClick={() => void documents.fetchNextPage()}
        >
          {documents.isFetchingNextPage ? adminText.loadingMore : adminText.loadMore}
        </Button>
      )}

      {editing && <AccessEditor document={editing} onClose={() => setEditing(null)} />}
      {replacing && <ReplaceDialog document={replacing} onClose={() => setReplacing(null)} />}
      {deleting && <DeleteDialog document={deleting} onClose={() => setDeleting(null)} />}
    </main>
  );
}
