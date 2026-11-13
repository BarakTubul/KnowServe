import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import { replaceDocumentFile, type AdminDocument } from '../admin-api';
import { patchAdminDocument, refreshAdminDocuments } from '../admin-cache';
import { adminErrorMessage, describeAdminError } from '../admin-error-messages';
import { ModalDialog } from '../modal-dialog';
import { fileFingerprint, useActionKey } from '../use-action-key';
import { PDF_MAX_BYTES, uploadText } from './upload-text';

function checkFile(file: File | null): string | null {
  if (!file) return adminErrorMessage('FILE_REQUIRED');
  if (file.size === 0) return adminErrorMessage('FILE_EMPTY');
  if (file.size > PDF_MAX_BYTES) return adminErrorMessage('FILE_TOO_LARGE');
  if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
    return adminErrorMessage('NOT_A_PDF');
  }
  return null;
}

/**
 * Replace the file of a failed document (FE-ADM-13, ADM-18). Opened only where the server says
 * `can_replace`. A 409 or 422 shows the catalog message and the row keeps its state; success moves the
 * row to `queued`, and its status stream takes over.
 */
export function ReplaceDialog({
  document,
  onClose,
}: {
  document: AdminDocument;
  onClose: () => void;
}) {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const queryClient = useQueryClient();
  const { keyFor, reset } = useActionKey();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const replace = useMutation({
    mutationFn: (chosen: File) =>
      replaceDocumentFile(document.document_id, chosen, keyFor(fileFingerprint(chosen))),
    onSuccess: async (updated) => {
      reset();
      patchAdminDocument(queryClient, identity, updated);
      await refreshAdminDocuments(queryClient, identity);
      onClose();
    },
    onError: (error) => {
      // A conflict means the document changed under us: show the truth in the list behind the dialog.
      if (error instanceof Error) void refreshAdminDocuments(queryClient, identity);
    },
  });

  function submit() {
    const problem = checkFile(file);
    setFileError(problem);
    if (!problem && file) replace.mutate(file);
  }

  return (
    <ModalDialog
      title={uploadText.replace.title}
      onClose={onClose}
      busy={replace.isPending}
      testId="replace-dialog"
    >
      <p className="text-sm" dir="auto">
        {document.title}
      </p>
      <p className="text-sm" data-testid="replace-notice">
        {uploadText.replace.notice}
      </p>
      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor="replace-file">{uploadText.replace.fileLabel}</label>
        <Input
          id="replace-file"
          type="file"
          accept="application/pdf,.pdf"
          disabled={replace.isPending}
          aria-invalid={fileError ? true : undefined}
          aria-describedby="replace-file-error"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setFileError(null);
          }}
        />
        <p id="replace-file-hint" className="text-muted-foreground">
          {uploadText.fileHint}
        </p>
        <p
          id="replace-file-error"
          role={fileError ? 'alert' : undefined}
          className="text-destructive"
        >
          {fileError}
        </p>
      </div>
      {replace.isError && (
        <Alert variant="error" data-testid="replace-error">
          {describeAdminError(replace.error, language)}
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose} disabled={replace.isPending}>
          {uploadText.replace.cancel}
        </Button>
        <Button onClick={submit} disabled={replace.isPending}>
          {replace.isPending ? uploadText.replace.submitting : uploadText.replace.submit}
        </Button>
      </div>
    </ModalDialog>
  );
}
