import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getStatus } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';

function errorCode(e: unknown): string {
  return e instanceof ApiError ? e.code : 'UNKNOWN';
}

function requestId(e: unknown): string {
  return (e instanceof ApiError && e.requestId) || 'n/a';
}

export function StatusPage() {
  const query = useQuery({ queryKey: ['status'], queryFn: () => getStatus(), retry: false });

  return (
    <main data-testid="status-page" className="mx-auto flex max-w-xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">KnowServe</h1>
        <span
          data-testid="demo-mode-badge"
          className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground"
        >
          Demo Mode
        </span>
      </header>
      <Card>
        <CardHeader>
          <CardTitle>API status</CardTitle>
        </CardHeader>
        <CardContent>
          {query.isPending && <p data-testid="api-loading">Checking API status...</p>}
          {query.isSuccess && (
            <dl data-testid="api-status" className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">Service</dt>
              <dd data-testid="api-service">{query.data.service}</dd>
              <dt className="text-muted-foreground">Version</dt>
              <dd data-testid="api-version">{query.data.version}</dd>
              <dt className="text-muted-foreground">Environment</dt>
              <dd data-testid="api-environment">{query.data.environment}</dd>
              <dt className="text-muted-foreground">Database</dt>
              <dd data-testid="api-database">{query.data.database}</dd>
            </dl>
          )}
          {query.isError && (
            <div
              data-testid="api-error"
              role="alert"
              className="flex flex-col gap-2 text-destructive"
            >
              <p>The API is not available right now.</p>
              <p>
                Error code: <span data-testid="api-error-code">{errorCode(query.error)}</span>
              </p>
              <p>
                Request id: <span data-testid="api-error-request-id">{requestId(query.error)}</span>
              </p>
              <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
                Retry
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
