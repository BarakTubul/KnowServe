import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import { deleteAdminDocument, type AdminDocument } from './admin-api';
import { refreshAdminDocuments } from './admin-cache';
import { describeAdminError } from './admin-error-messages';
import { adminText } from './admin-text';
import { ModalDialog } from './modal-dialog';

/** Soft-delete confirmation (FE-ADM-08): an accessible dialog; cancel does nothing. */
export function DeleteDialog({
  document,
  onClose,
}: {
  document: AdminDocument;
  onClose: () => void;
}) {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteAdminDocument(document.document_id),
    onSuccess: async () => {
      await refreshAdminDocuments(queryClient, identity);
      onClose();
    },
  });
  return (
    <ModalDialog
      title={adminText.remove.title}
      onClose={onClose}
      busy={remove.isPending}
      testId="delete-dialog"
    >
      <p className="text-sm" dir="auto">
        {adminText.remove.body(document.title)}
      </p>
      {remove.isError && (
        <Alert variant="error">{describeAdminError(remove.error, language)}</Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose} disabled={remove.isPending}>
          {adminText.remove.cancel}
        </Button>
        <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
          {remove.isPending ? adminText.remove.deleting : adminText.remove.confirm}
        </Button>
      </div>
    </ModalDialog>
  );
}
