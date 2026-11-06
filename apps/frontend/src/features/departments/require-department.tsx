import type { ReactNode } from 'react';
import { useAuth } from '@/features/auth/auth-context';
import { DepartmentSelector } from './department-selector';

/** Department-scoped screens wait for a chosen department; the first login has none (FE-AUTH-09). */
export function RequireDepartment({ children }: { children: ReactNode }) {
  const { identity } = useAuth();
  if (!identity?.active_department) {
    return (
      <div data-testid="department-required" className="max-w-md">
        <DepartmentSelector required />
      </div>
    );
  }
  return <>{children}</>;
}
