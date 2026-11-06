import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { identityKey, useAuth } from '@/features/auth/auth-context';
import { describeApiError } from '@/features/auth/messages';
import { listDepartments } from '@/lib/api/client';

interface DepartmentSelectorProps {
  /** Required on first login: no way to dismiss it (FE-AUTH-09). */
  required?: boolean;
}

/** Lists the departments from the API (FE-ARCH-13). Nothing is hard-coded. */
export function DepartmentSelector({ required = false }: DepartmentSelectorProps) {
  const { identity, selectDepartment, closeDepartmentSelector } = useAuth();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: identityKey(identity, 'departments'),
    queryFn: () => listDepartments(),
    enabled: identity !== null,
  });

  async function choose(id: string) {
    setPending(id);
    setError(null);
    try {
      await selectDepartment(id);
    } catch (e) {
      setError(describeApiError(e));
    } finally {
      setPending(null);
    }
  }

  const activeId = identity?.active_department?.id;

  return (
    <section
      data-testid="department-selector"
      aria-labelledby="department-selector-title"
      className="flex flex-col gap-4"
    >
      <div className="flex flex-col gap-1">
        <h2 id="department-selector-title" className="text-lg font-semibold">
          {required ? 'Choose a department to continue' : 'Switch department'}
        </h2>
        <p className="text-sm text-muted-foreground">
          Demo Mode: you pick the department yourself, for demonstration. This changes what you view
          and never gives you extra access.
        </p>
      </div>
      {query.isPending && <p role="status">Loading departments...</p>}
      {query.isError && (
        <Alert variant="error">
          Could not load the departments.{' '}
          <button type="button" className="underline" onClick={() => void query.refetch()}>
            Retry
          </button>
        </Alert>
      )}
      {query.isSuccess && (
        <ul className="flex flex-col gap-2">
          {query.data.map((department) => (
            <li key={department.id}>
              <Button
                variant={department.id === activeId ? 'default' : 'outline'}
                className="w-full justify-start"
                aria-pressed={department.id === activeId}
                disabled={pending !== null}
                onClick={() => void choose(department.id)}
              >
                {department.name}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {error && <Alert variant="error">{error}</Alert>}
      {!required && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={closeDepartmentSelector}
        >
          Close
        </Button>
      )}
    </section>
  );
}

/** Modal presentation, opened by the header action or by a 409 `ACTIVE_DEPARTMENT_REQUIRED`. */
export function DepartmentSelectorDialog() {
  const { departmentSelectorOpen, identity } = useAuth();
  // Without a department the screen itself shows the required selector.
  if (!departmentSelectorOpen || !identity?.active_department) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-foreground/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="department-selector-title"
        className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-lg"
      >
        <DepartmentSelector />
      </div>
    </div>
  );
}
