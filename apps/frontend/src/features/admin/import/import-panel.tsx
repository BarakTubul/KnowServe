import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import {
  confirmImport,
  previewImport,
  type ImportConfirmation,
  type ImportEntryPreview,
  type ImportEntryResult,
  type ImportPreview,
} from '../admin-api';
import { refreshAdminDocuments } from '../admin-cache';
import { adminErrorMessage, describeAdminError } from '../admin-error-messages';
import { fileFingerprint, useActionKey } from '../use-action-key';
import { ZIP_MAX_BYTES, uploadText } from '../upload/upload-text';

const t = uploadText.importer;

function entryProblem(
  entry: { error_code?: string | null; detail?: string | null },
  language: 'en' | 'he',
) {
  const text = adminErrorMessage(entry.error_code ?? 'generic', language);
  return entry.detail ? `${text} (${entry.detail})` : text;
}

function PreviewEntry({ entry }: { entry: ImportEntryPreview }) {
  const { language } = useLanguage();
  return (
    <li
      data-testid={entry.valid ? 'import-entry-valid' : 'import-entry-invalid'}
      className="flex flex-col gap-1 rounded-md border border-border p-2 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <bdi className="font-medium">{entry.file}</bdi>
        <span className={entry.valid ? 'text-success' : 'text-destructive'}>
          {entry.valid ? t.valid : t.invalid}
        </span>
      </div>
      {entry.valid ? (
        <>
          {entry.title && <span dir="auto">{entry.title}</span>}
          <span className="text-muted-foreground">
            {t.owner}: {entry.owner_department?.name ?? '-'}
          </span>
          <span className="text-muted-foreground" data-testid="import-entry-allowed">
            {t.allowed}: {entry.allowed_departments.map((d) => d.name).join(', ')}
          </span>
        </>
      ) : (
        <span role="status" className="text-destructive" data-testid="import-entry-problem">
          {entryProblem(entry, language)}
        </span>
      )}
    </li>
  );
}

function ResultEntry({ entry }: { entry: ImportEntryResult }) {
  const { language } = useLanguage();
  const created = entry.status === 'created';
  return (
    <li
      data-testid={created ? 'import-result-created' : 'import-result-rejected'}
      className="flex flex-col gap-1 rounded-md border border-border p-2 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <bdi className="font-medium">{entry.file}</bdi>
        <span className={created ? 'text-success' : 'text-destructive'}>
          {created ? t.created : t.rejected}
        </span>
      </div>
      {!created && <span className="text-destructive">{entryProblem(entry, language)}</span>}
    </li>
  );
}

/**
 * ZIP import (FE-ADM-11, ADM-11 to ADM-14). Step 1 sends the ZIP for a read-only preview that creates
 * nothing. Step 2 is an explicit Confirm that sends the ZIP again with this action's Idempotency-Key
 * (double click safe: the button is disabled and a repeat reuses the key). Invalid entries are shown
 * with the server's reason and are never imported; there is no default access.
 */
export function ImportPanel({ onClose }: { onClose?: () => void }) {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const queryClient = useQueryClient();
  const confirmKey = useActionKey();
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const [fileError, setFileError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportConfirmation | null>(null);

  const previewMutation = useMutation({
    mutationFn: (zip: File) => previewImport(zip),
    onSuccess: (data) => {
      setPreview(data);
      setResult(null);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (zip: File) =>
      confirmImport(zip, confirmKey.keyFor(`confirm:${fileFingerprint(zip)}`)),
    onSuccess: async (data) => {
      confirmKey.reset();
      setResult(data);
      setPreview(null);
      await refreshAdminDocuments(queryClient, identity);
    },
  });

  function choose(next: File | null) {
    setFile(next);
    setPreview(null);
    setResult(null);
    previewMutation.reset();
    confirmMutation.reset();
    confirmKey.reset();
    if (!next) {
      setFileError(null);
      setInputKey((n) => n + 1); // clears the file input
    } else if (next.size === 0) setFileError(adminErrorMessage('FILE_EMPTY', language));
    else if (next.size > ZIP_MAX_BYTES) setFileError(adminErrorMessage('ZIP_TOO_LARGE', language));
    else if (!/\.zip$/i.test(next.name)) setFileError(adminErrorMessage('ZIP_INVALID', language));
    else setFileError(null);
  }

  function runPreview() {
    if (!file) return setFileError(adminErrorMessage('FILE_REQUIRED', language));
    if (!fileError) previewMutation.mutate(file);
  }

  const busy = previewMutation.isPending || confirmMutation.isPending;
  const validCount = preview?.valid_count ?? 0;
  const rejected = result?.results.filter((entry) => entry.status === 'rejected') ?? [];
  const error = confirmMutation.error ?? previewMutation.error;

  return (
    <section
      aria-labelledby="import-title"
      data-testid="import-panel"
      className="flex flex-col gap-4 rounded-md border border-border p-4"
    >
      <h2 id="import-title" className="text-lg font-semibold">
        {t.title}
      </h2>
      <p className="text-sm text-muted-foreground">{t.hint}</p>
      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor="import-file">{t.fileLabel}</label>
        <Input
          key={inputKey}
          id="import-file"
          type="file"
          accept=".zip,application/zip"
          disabled={busy}
          aria-invalid={fileError ? true : undefined}
          aria-describedby="import-file-error"
          onChange={(event) => choose(event.target.files?.[0] ?? null)}
        />
        <p
          id="import-file-error"
          role={fileError ? 'alert' : undefined}
          className="text-destructive"
        >
          {fileError}
        </p>
      </div>
      {!preview && !result && (
        <Button className="self-start" onClick={runPreview} disabled={busy}>
          {previewMutation.isPending ? t.previewing : t.preview}
        </Button>
      )}

      {error && <Alert variant="error">{describeAdminError(error, language)}</Alert>}

      {preview && (
        <div className="flex flex-col gap-3" data-testid="import-preview">
          <p role="status" className="text-sm">
            {t.summary(preview.valid_count, preview.invalid_count)}
          </p>
          <p className="text-sm text-muted-foreground">{t.noDefault}</p>
          <ul className="flex flex-col gap-2">
            {preview.entries.map((entry) => (
              <PreviewEntry key={`${entry.index}-${entry.file}`} entry={entry} />
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy || validCount === 0 || !file}
              onClick={() => file && confirmMutation.mutate(file)}
            >
              {confirmMutation.isPending ? t.confirming : t.confirm(validCount)}
            </Button>
            <Button variant="outline" disabled={busy} onClick={() => choose(null)}>
              {t.cancel}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-3" data-testid="import-results">
          <h3 className="font-medium">{t.resultsTitle}</h3>
          <p role="status" className="text-sm">
            {t.resultSummary(result.created_count, result.rejected_count)}
          </p>
          <ul className="flex flex-col gap-2">
            {result.results.map((entry) => (
              <ResultEntry key={`${entry.index}-${entry.file}`} entry={entry} />
            ))}
          </ul>
          {rejected.length > 0 && (
            <div className="flex flex-col gap-1">
              <Button
                variant="outline"
                className="self-start"
                disabled={busy}
                onClick={() => file && confirmMutation.mutate(file)}
              >
                {confirmMutation.isPending ? t.confirming : t.retryFailed}
              </Button>
              <p className="text-sm text-muted-foreground">{t.retryNote}</p>
            </div>
          )}
          <Button variant="outline" className="self-start" onClick={() => choose(null)}>
            {t.cancel}
          </Button>
        </div>
      )}
      {onClose && (
        <Button variant="outline" size="sm" className="self-start" onClick={onClose}>
          {uploadText.close}
        </Button>
      )}
    </section>
  );
}
