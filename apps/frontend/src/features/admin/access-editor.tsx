import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import { updateAccess, type AdminDocument } from './admin-api';
import { patchAdminDocument, refreshAdminDocuments } from './admin-cache';
import { adminErrorMessage, describeAdminError } from './admin-error-messages';
import { adminText } from './admin-text';
import { DepartmentChecklist } from './department-checklist';
import { ModalDialog } from './modal-dialog';
import { useDepartments } from './use-departments';

/** Edit access (FE-ADM-07): a department checklist pre-filled from the document, at least one required. */
export function AccessEditor({
  document,
  onClose,
}: {
  document: AdminDocument;
  onClose: () => void;
}) {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const queryClient = useQueryClient();
  const departments = useDepartments();
  const [selected, setSelected] = useState<string[]>(() =>
    document.allowed_departments.map((department) => department.id),
  );
  const [showRequired, setShowRequired] = useState(false);

  const save = useMutation({
    mutationFn: () => updateAccess(document.document_id, selected),
    onSuccess: async (updated) => {
      patchAdminDocument(queryClient, identity, updated);
      await refreshAdminDocuments(queryClient, identity);
      onClose();
    },
  });

  function submit() {
    if (selected.length === 0) {
      setShowRequired(true);
      return;
    }
    save.mutate();
  }

  const required = showRequired && selected.length === 0;
  return (
    <ModalDialog
      title={adminText.access.title}
      onClose={onClose}
      busy={save.isPending}
      testId="access-editor"
    >
      <p className="text-sm text-muted-foreground" dir="auto">
        {document.title}
      </p>
      <p className="text-sm">{adminText.access.description}</p>
      {departments.isPending && <p role="status">{adminText.access.loadingDepartments}</p>}
      {departments.isError && (
        <Alert variant="error">{describeAdminError(departments.error, language)}</Alert>
      )}
      {departments.isSuccess && (
        <DepartmentChecklist
          legend={adminText.access.title}
          departments={departments.data}
          selected={selected}
          onChange={(ids) => setSelected(ids)}
          disabled={save.isPending}
          describedBy={required ? 'access-required' : undefined}
        />
      )}
      {required && (
        <p id="access-required" role="alert" className="text-sm text-destructive">
          {adminErrorMessage('ALLOWED_DEPARTMENTS_EMPTY')}
        </p>
      )}
      <p className="text-sm text-muted-foreground">{adminText.access.noReprocessing}</p>
      {save.isError && <Alert variant="error">{describeAdminError(save.error, language)}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose} disabled={save.isPending}>
          {adminText.access.cancel}
        </Button>
        <Button onClick={submit} disabled={save.isPending || !departments.isSuccess}>
          {save.isPending ? adminText.access.saving : adminText.access.save}
        </Button>
      </div>
    </ModalDialog>
  );
}
