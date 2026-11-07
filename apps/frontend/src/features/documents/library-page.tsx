import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { departmentKey, identityKey, useAuth } from '@/features/auth/auth-context';
import { DepartmentSelectorDialog } from '@/features/departments/department-selector';
import { RequireDepartment } from '@/features/departments/require-department';
import { listDepartments } from '@/lib/api/client';
import { useLanguage } from '@/lib/i18n/language-context';
import { LanguageSelector } from '@/lib/i18n/language-selector';
import { listDocuments } from './library-api';
import { libraryCatalog, libraryErrorMessage } from './library-messages';

const SEARCH_DEBOUNCE_MS = 250;

function useDebounced(value: string, delayMs: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/** Document library (FE-DOC-01..06, FE-DOC-10): permissioned list, search, owner filter, cursor paging. */
export function LibraryPage() {
  const { identity, openDepartmentSelector } = useAuth();
  const { language } = useLanguage();
  const text = libraryCatalog(language);
  const [search, setSearch] = useState('');
  const [owner, setOwner] = useState('');
  const q = useDebounced(search.trim(), SEARCH_DEBOUNCE_MS);

  const departments = useQuery({
    queryKey: identityKey(identity, 'departments'),
    queryFn: () => listDepartments(),
    enabled: identity !== null,
  });

  // The key carries identity and active department, so a switch or a new filter starts at the first
  // page with its own cache entry; the previous department's data is removed by the auth provider.
  const documents = useInfiniteQuery({
    queryKey: departmentKey(identity, 'documents', { q, owner }),
    queryFn: ({ pageParam }) => listDocuments({ q, ownerDepartmentId: owner, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.has_more && last.next_cursor ? last.next_cursor : undefined),
    enabled: identity?.active_department != null,
  });

  const items = documents.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = q !== '' || owner !== '';

  return (
    <main data-testid="library-page" className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{text.title}</h1>
        <div className="flex flex-wrap items-center gap-3">
          <LanguageSelector />
          <Link to="/dashboard" className="text-sm underline">
            {text.backToDashboard}
          </Link>
          {identity?.active_department && (
            <Button variant="outline" size="sm" onClick={openDepartmentSelector}>
              {text.changeDepartment}
            </Button>
          )}
        </div>
      </header>
      <RequireDepartment>
        <div className="flex flex-wrap gap-3">
          <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
            {text.searchLabel}
            <Input
              type="search"
              value={search}
              placeholder={text.searchPlaceholder}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {text.ownerFilterLabel}
            <select
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              className="h-9 rounded-md border border-border bg-background px-2 text-sm"
            >
              <option value="">{text.allDepartments}</option>
              {(departments.data ?? []).map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        {documents.isPending && <p role="status">{text.loading}</p>}
        {documents.isError && (
          <Alert variant="error" data-testid="library-error">
            {libraryErrorMessage(documents.error, text)}{' '}
            <button type="button" className="underline" onClick={() => void documents.refetch()}>
              {text.retry}
            </button>
          </Alert>
        )}
        {documents.isSuccess && items.length === 0 && (
          <p data-testid={filtered ? 'library-no-match' : 'library-empty'}>
            {filtered ? text.noMatch : text.empty}
          </p>
        )}
        {items.length > 0 && (
          <ul className="flex flex-col gap-2">
            {items.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/documents/${item.id}`}
                  className="flex flex-col items-start gap-1 rounded-md border border-border p-3 hover:bg-muted"
                >
                  <span className="font-medium" dir="auto">
                    {item.title}
                  </span>
                  <bdi className="text-sm text-muted-foreground">{item.filename}</bdi>
                  <span className="text-sm text-muted-foreground">
                    {text.ownerDepartment(item.owner_department.name)} ·{' '}
                    {text.pages(item.page_count)}
                  </span>
                </Link>
              </li>
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
            {documents.isFetchingNextPage ? text.loadingMore : text.loadMore}
          </Button>
        )}
      </RequireDepartment>
      <DepartmentSelectorDialog />
    </main>
  );
}
