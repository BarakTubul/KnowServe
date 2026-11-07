import { Document, Page, pdfjs } from 'react-pdf';
import { useLanguage } from '@/lib/i18n/language-context';
import { documentContentUrl } from './api';
import { viewerCatalog } from './messages';

// Vite emits the worker as a hashed static asset next to the bundle (same origin, no CDN).
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

// isEvalSupported: false keeps pdf.js working under a CSP without unsafe-eval.
// Stable reference: react-pdf reloads the document when `options` changes identity.
const DOCUMENT_OPTIONS = { withCredentials: true, isEvalSupported: false };

interface Props {
  documentId: string;
  page: number;
  scale: number;
  onLoaded(numPages: number): void;
  onError(error: unknown): void;
}

/** React-PDF with bytes from the API endpoint only, sending the session cookie (FE-DOC-07). */
export default function PdfSurface({ documentId, page, scale, onLoaded, onError }: Props) {
  const text = viewerCatalog(useLanguage().language);
  return (
    <Document
      file={{ url: documentContentUrl(documentId) }}
      options={DOCUMENT_OPTIONS}
      onLoadSuccess={(pdf) => onLoaded(pdf.numPages)}
      onLoadError={onError}
      onSourceError={onError}
      loading={<p className="p-6 text-sm text-muted-foreground">{text.loadingDocument}</p>}
      error={null}
      noData={null}
    >
      <Page
        pageNumber={page}
        scale={scale}
        renderAnnotationLayer={false}
        renderTextLayer={false}
        onRenderError={onError}
      />
    </Document>
  );
}
