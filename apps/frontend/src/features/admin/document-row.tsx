import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import { retryAdminDocument, type AdminDocument } from './admin-api';
import { patchAdminDocument, refreshAdminDocuments } from './admin-cache';
import { describeAdminError, failureMessage } from './admin-error-messages';
import { DELIVERY_HINT, adminText } from './admin-text';
import { TERMINAL_FAILURES } from './upload/upload-text';
import { StatusBadge } from './status-badge';
import { useDocumentEvents } from './use-document-events';

interface DocumentRowProps {
  document: AdminDocument;
  onEditAccess: (document: AdminDocument) => void;
  onDelete: (document: AdminDocument) => void;
  onReplace: (document: AdminDocument) => void;
}

/**
 * One document of the Admin list (FE-ADM-02, FE-ADM-06, FE-ADM-10). A document that can still change
 * follows its status stream. The actions come from the server's `can_retry` and `can_replace` flags;
 * the client keeps no action rules of its own (ADM-16, ADM-18).
 */
export function DocumentRow({ document, onEditAccess, onDelete, onReplace }: DocumentRowProps) {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const queryClient = useQueryClient();

  const live = document.status === 'queued' || document.status === 'processing';
  const stream = useDocumentEvents({
    documentId: document.document_id,
    enabled: live,
    onStatus: (status) => patchAdminDocument(queryClient, identity, status),
    onTerminal: () => void refreshAdminDocuments(queryClient, identity),
    onPoll: () => void refreshAdminDocuments(queryClient, identity),
  });

  const retry = useMutation({
    mutationFn: () => retryAdminDocument(document.document_id),
    onSuccess: (updated) => patchAdminDocument(queryClient, identity, updated),
    onError: () => void refreshAdminDocuments(queryClient, identity),
  });

  const hint = document.delivery_state ? DELIVERY_HINT[document.delivery_state] : undefined;
  const failed = document.status === 'failed';

  const replaceButton = document.can_replace ? (
    <Button size="sm" variant="outline" onClick={() => onReplace(document)}>
      {adminText.actions.replaceFile}
    </Button>
  ) : null;
  const retryButton = document.can_retry ? (
    <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}>
      {retry.isPending ? adminText.actions.retrying : adminText.actions.retry}
    </Button>
  ) : null;
  // Retry cannot help a terminal failure, so Replace file comes first there (plan F13); otherwise Retry does.
  const terminal = document.failure_code != null && TERMINAL_FAILURES.has(document.failure_code);

  return (
    <li
      data-testid="admin-document"
      data-document-id={document.document_id}
      className="flex flex-col gap-2 rounded-md border border-border p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="font-medium" dir="auto">
            {document.title}
          </span>
          <bdi className="text-sm text-muted-foreground">{document.filename}</bdi>
        </div>
        <StatusBadge document={document} />
      </div>
      <p className="text-sm text-muted-foreground">
        {adminText.owner}: {document.owner_department.name}
        {document.page_count != null && <> · {adminText.pages(document.page_count)}</>} ·{' '}
        {adminText.size(document.size_bytes)}
      </p>
      <p className="text-sm text-muted-foreground" data-testid="allowed-departments">
        {adminText.allowed}:{' '}
        {document.allowed_departments.length > 0
          ? document.allowed_departments.map((department) => department.name).join(', ')
          : adminText.noAllowed}
      </p>
      {failed && (
        <p role="status" data-testid="failure-reason" className="text-sm text-destructive">
          {failureMessage(document.failure_code ?? 'generic', language)}
        </p>
      )}
      {hint && (
        <p data-testid="delivery-hint" className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      {stream === 'degraded' && (
        <p data-testid="stream-degraded" className="text-sm text-muted-foreground">
          {adminText.streamDegraded}
        </p>
      )}
      {retry.isError && <Alert variant="error">{describeAdminError(retry.error, language)}</Alert>}
      <div className="flex flex-wrap gap-2">
        {terminal ? replaceButton : retryButton}
        {terminal ? retryButton : replaceButton}
        <Button size="sm" variant="outline" onClick={() => onEditAccess(document)}>
          {adminText.actions.editAccess}
        </Button>
        <Button size="sm" variant="outline" onClick={() => onDelete(document)}>
          {adminText.actions.delete}
        </Button>
      </div>
    </li>
  );
}
