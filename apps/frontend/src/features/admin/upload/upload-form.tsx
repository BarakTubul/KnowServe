import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuth } from '@/features/auth/auth-context';
import { useLanguage } from '@/lib/i18n/language-context';
import { uploadDocument } from '../admin-api';
import { refreshAdminDocuments } from '../admin-cache';
import { adminErrorMessage, describeAdminError } from '../admin-error-messages';
import { DepartmentChecklist } from '../department-checklist';
import { fileFingerprint, useActionKey } from '../use-action-key';
import { useDepartments } from '../use-departments';
import { PDF_MAX_BYTES, TITLE_MAX_LENGTH, uploadText } from './upload-text';

const e = (code: Parameters<typeof adminErrorMessage>[0]) => adminErrorMessage(code);

/** Client checks mirror the contract; the server validates independently (FE-ARCH-09). */
export const uploadSchema = z.object({
  file: z
    .instanceof(File, { message: e('FILE_REQUIRED') })
    .refine((f) => f.size > 0, e('FILE_EMPTY'))
    .refine((f) => f.size <= PDF_MAX_BYTES, e('FILE_TOO_LARGE'))
    .refine((f) => /\.pdf$/i.test(f.name) || f.type === 'application/pdf', e('NOT_A_PDF')),
  title: z.string().trim().min(1, e('TITLE_INVALID')).max(TITLE_MAX_LENGTH, e('TITLE_INVALID')),
  ownerDepartmentId: z.string().min(1, e('OWNER_REQUIRED')),
  allowedDepartmentIds: z.array(z.string()).min(1, e('ALLOWED_DEPARTMENTS_EMPTY')),
});
export type UploadValues = z.input<typeof uploadSchema>;

const EMPTY: UploadValues = {
  file: undefined as unknown as File,
  title: '',
  ownerDepartmentId: '',
  allowedDepartmentIds: [],
};

/**
 * Single upload (FE-ADM-03/04/05/09). The owner defaults to the active department, and choosing an
 * owner pre-selects it as an allowed department; the Admin may change both. Nothing else is inferred
 * (OPEN-16). The button is disabled while the request runs, and a retry of the same upload reuses its
 * Idempotency-Key.
 */
export function UploadForm({ onUploaded }: { onUploaded?: (title: string) => void }) {
  const { identity } = useAuth();
  const { language } = useLanguage();
  const queryClient = useQueryClient();
  const departments = useDepartments();
  const { keyFor, reset: resetKey } = useActionKey();
  const [inputKey, setInputKey] = useState(0);
  const [done, setDone] = useState<string | null>(null);

  const form = useForm<UploadValues>({
    resolver: zodResolver(uploadSchema),
    defaultValues: EMPTY,
    mode: 'onSubmit',
  });
  const { control, register, handleSubmit, setValue, getValues, formState } = form;
  const { errors } = formState;
  const owner = useWatch({ control, name: 'ownerDepartmentId' });
  const allowed = useWatch({ control, name: 'allowedDepartmentIds' });

  // The active department is the starting owner, once the department list is known (single upload only).
  const activeId = identity?.active_department?.id;
  const departmentList = departments.data;
  useEffect(() => {
    if (!departmentList || !activeId || getValues('ownerDepartmentId')) return;
    if (departmentList.some((d) => d.id === activeId)) {
      setValue('ownerDepartmentId', activeId);
      setValue('allowedDepartmentIds', [activeId]);
    }
  }, [departmentList, activeId, getValues, setValue]);

  function chooseOwner(id: string) {
    setValue('ownerDepartmentId', id, { shouldValidate: formState.isSubmitted });
    if (id && !getValues('allowedDepartmentIds').includes(id)) {
      setValue('allowedDepartmentIds', [...getValues('allowedDepartmentIds'), id]);
    }
  }

  const upload = useMutation({
    mutationFn: (values: z.output<typeof uploadSchema>) => {
      const fingerprint = [
        fileFingerprint(values.file),
        values.title,
        values.ownerDepartmentId,
        [...values.allowedDepartmentIds].sort().join(','),
      ].join('|');
      return uploadDocument(
        {
          file: values.file,
          title: values.title,
          ownerDepartmentId: values.ownerDepartmentId,
          allowedDepartmentIds: values.allowedDepartmentIds,
        },
        keyFor(fingerprint),
      );
    },
    onSuccess: async (created) => {
      resetKey();
      // Back to the starting point: the active department is the owner and allowed again.
      const start = departmentList?.some((d) => d.id === activeId) ? activeId : undefined;
      form.reset({
        ...EMPTY,
        ownerDepartmentId: start ?? '',
        allowedDepartmentIds: start ? [start] : [],
      });
      setInputKey((n) => n + 1); // clears the file input
      setDone(uploadText.uploaded(created.title));
      await refreshAdminDocuments(queryClient, identity);
      onUploaded?.(created.title);
    },
  });

  const submit = handleSubmit((values) => {
    setDone(null);
    upload.mutate(values as z.output<typeof uploadSchema>);
  });

  const fileError = errors.file?.message;
  const allowedError = errors.allowedDepartmentIds?.message;
  return (
    <form
      onSubmit={(event) => void submit(event)}
      noValidate
      aria-labelledby="upload-form-title"
      data-testid="upload-form"
      className="flex flex-col gap-4 rounded-md border border-border p-4"
    >
      <h2 id="upload-form-title" className="text-lg font-semibold">
        {uploadText.formTitle}
      </h2>

      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor="upload-file">{uploadText.fileLabel}</label>
        <Controller
          control={control}
          name="file"
          render={({ field }) => (
            <Input
              id="upload-file"
              key={inputKey}
              type="file"
              accept="application/pdf,.pdf"
              disabled={upload.isPending}
              aria-invalid={fileError ? true : undefined}
              aria-describedby="upload-file-hint upload-file-error"
              onChange={(event) =>
                field.onChange(event.target.files?.[0] ?? (undefined as unknown as File))
              }
            />
          )}
        />
        <p id="upload-file-hint" className="text-muted-foreground">
          {uploadText.fileHint}
        </p>
        <p
          id="upload-file-error"
          role={fileError ? 'alert' : undefined}
          className="text-destructive"
        >
          {fileError}
        </p>
      </div>

      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor="upload-title">{uploadText.titleLabel}</label>
        <Input
          id="upload-title"
          disabled={upload.isPending}
          aria-invalid={errors.title ? true : undefined}
          aria-describedby="upload-title-error"
          dir="auto"
          {...register('title')}
        />
        <p
          id="upload-title-error"
          role={errors.title ? 'alert' : undefined}
          className="text-destructive"
        >
          {errors.title?.message}
        </p>
      </div>

      {departments.isPending && <p role="status">{uploadText.loadingDepartments}</p>}
      {departments.isError && (
        <Alert variant="error">{describeAdminError(departments.error, language)}</Alert>
      )}
      {departments.isSuccess && (
        <>
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="upload-owner">{uploadText.ownerLabel}</label>
            <select
              id="upload-owner"
              value={owner}
              disabled={upload.isPending}
              aria-invalid={errors.ownerDepartmentId ? true : undefined}
              aria-describedby="upload-owner-note upload-owner-error"
              onChange={(event) => chooseOwner(event.target.value)}
              className="h-9 rounded-md border border-border bg-background px-2 text-sm"
            >
              <option value="">{uploadText.ownerPlaceholder}</option>
              {departments.data.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
            <p id="upload-owner-note" className="text-muted-foreground">
              {uploadText.ownerNote}
            </p>
            <p
              id="upload-owner-error"
              role={errors.ownerDepartmentId ? 'alert' : undefined}
              className="text-destructive"
            >
              {errors.ownerDepartmentId?.message}
            </p>
          </div>
          <div className="flex flex-col gap-1">
            <DepartmentChecklist
              legend={uploadText.allowedLegend}
              departments={departments.data}
              selected={allowed}
              disabled={upload.isPending}
              describedBy="upload-allowed-note upload-allowed-error"
              onChange={(ids) =>
                setValue('allowedDepartmentIds', ids, { shouldValidate: formState.isSubmitted })
              }
            />
            <p id="upload-allowed-note" className="text-sm text-muted-foreground">
              {uploadText.allowedNote}
            </p>
            <p
              id="upload-allowed-error"
              role={allowedError ? 'alert' : undefined}
              className="text-sm text-destructive"
            >
              {allowedError}
            </p>
          </div>
        </>
      )}

      {upload.isError && (
        <Alert variant="error" data-testid="upload-error">
          {describeAdminError(upload.error, language)}
        </Alert>
      )}
      {done && !upload.isPending && (
        <Alert variant="success" data-testid="upload-success">
          {done}
        </Alert>
      )}
      <Button
        type="submit"
        className="self-start"
        disabled={upload.isPending || !departments.isSuccess}
      >
        {upload.isPending ? uploadText.submitting : uploadText.submit}
      </Button>
    </form>
  );
}
