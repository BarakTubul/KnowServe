import { useQuery } from '@tanstack/react-query';
import { Suspense, lazy, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { departmentKey, useAuth } from '@/features/auth/auth-context';
import { ApiError } from '@/lib/api/errors';
import { useLanguage } from '@/lib/i18n/language-context';
import { LanguageSelector } from '@/lib/i18n/language-selector';
import { getDocumentMetadata, pdfLoadError, reportApiError } from './viewer/api';
import { viewerCatalog, viewerMessage } from './viewer/messages';

// pdf.js is loaded only when a document is opened, so the rest of the app stays small.
const PdfSurface = lazy(() => import('./viewer/pdf-surface'));

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const DEFAULT_ZOOM = 2;

function parsePage(raw: string | null): number | null {
  if (raw === null || !/^-?\d+$/.test(raw)) return null;
  return Number.parseInt(raw, 10);
}

function BackLink() {
  const text = viewerCatalog(useLanguage().language);
  return (
    <Button asChild variant="outline" size="sm" className="mt-4">
      <Link to="/documents">{text.backToDocuments}</Link>
    </Button>
  );
}

function NotAvailable() {
  const text = viewerCatalog(useLanguage().language);
  return (
    <main className="mx-auto max-w-3xl p-6" data-testid="viewer-not-available">
      <h1 className="text-xl font-semibold">{text.notAvailableTitle}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{text.notAvailableBody}</p>
      <BackLink />
    </main>
  );
}

/** Protected PDF viewer at /documents/:id (FE-DOC-07..09). */
export function ViewerPage() {
  const { id = '' } = useParams();
  const { identity } = useAuth();
  const text = viewerCatalog(useLanguage().language);
  const [searchParams, setSearchParams] = useSearchParams();
  const [zoomIndex, setZoomIndex] = useState(DEFAULT_ZOOM);
  const [loadedPages, setLoadedPages] = useState<number | null>(null);
  const [pdfError, setPdfError] = useState<ApiError | null>(null);

  const metadata = useQuery({
    queryKey: departmentKey(identity, 'document', id),
    queryFn: () => getDocumentMetadata(id),
    retry: false,
  });

  if (metadata.isPending) {
    return (
      <main className="mx-auto max-w-3xl p-6" data-testid="viewer-loading">
        <p className="text-sm text-muted-foreground">{text.loadingDocument}</p>
      </main>
    );
  }
  const failure = metadata.error ?? pdfError;
  if (failure) {
    const apiError = failure instanceof ApiError ? failure : pdfLoadError(failure);
    // One identical view for every 404 cause (SEC-02).
    if (apiError.status === 404) return <NotAvailable />;
    return (
      <main className="mx-auto max-w-3xl p-6" data-testid="viewer-error">
        <Alert variant="error">{viewerMessage(apiError.code, text)}</Alert>
        <BackLink />
      </main>
    );
  }

  const doc = metadata.data;
  if (!doc) return null;
  const total = Math.max(loadedPages ?? doc.page_count, 1);
  const requested = parsePage(searchParams.get('page'));
  const outOfRange =
    searchParams.has('page') && (requested === null || requested < 1 || requested > total);
  const page = requested === null ? 1 : Math.min(Math.max(requested, 1), total);
  const scale = ZOOM_STEPS[zoomIndex] ?? 1;

  function goTo(next: number) {
    setSearchParams({ page: String(Math.min(Math.max(next, 1), total)) });
  }

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-4 p-6" data-testid="viewer-page">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link to="/documents" className="text-sm text-muted-foreground underline">
            {text.documentsLink}
          </Link>
          <h1 className="truncate text-start text-xl font-semibold" data-testid="viewer-filename">
            <bdi>{doc.filename}</bdi>
          </h1>
          <p className="text-sm text-muted-foreground" data-testid="viewer-header-page">
            {text.pageOf(page, total)}
          </p>
        </div>
        <div
          className="flex flex-wrap items-center gap-2"
          role="toolbar"
          aria-label={text.toolbarLabel}
        >
          <LanguageSelector />
          <Button
            variant="outline"
            size="sm"
            onClick={() => goTo(page - 1)}
            disabled={page <= 1}
            aria-label={text.previousLabel}
          >
            {text.previous}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => goTo(page + 1)}
            disabled={page >= total}
            aria-label={text.nextLabel}
          >
            {text.next}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setZoomIndex((i) => Math.max(i - 1, 0))}
            disabled={zoomIndex <= 0}
            aria-label={text.zoomOutLabel}
          >
            −
          </Button>
          <span className="w-12 text-center text-sm" dir="ltr" data-testid="viewer-zoom">
            {Math.round(scale * 100)}%
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setZoomIndex((i) => Math.min(i + 1, ZOOM_STEPS.length - 1))}
            disabled={zoomIndex >= ZOOM_STEPS.length - 1}
            aria-label={text.zoomInLabel}
          >
            +
          </Button>
        </div>
      </header>
      {outOfRange && (
        <Alert variant="info" data-testid="viewer-page-notice">
          {text.pageMissing(page)}
        </Alert>
      )}
      {/* The PDF canvas stays left-to-right whatever the interface language. */}
      <div dir="ltr" className="overflow-auto rounded-md border bg-muted p-2">
        <Suspense
          fallback={<p className="p-6 text-sm text-muted-foreground">{text.loadingViewer}</p>}
        >
          <PdfSurface
            documentId={id}
            page={page}
            scale={scale}
            onLoaded={setLoadedPages}
            onError={(e) => setPdfError(reportApiError(pdfLoadError(e)))}
          />
        </Suspense>
      </div>
    </main>
  );
}
