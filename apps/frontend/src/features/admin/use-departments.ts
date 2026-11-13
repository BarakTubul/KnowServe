import { useQuery } from '@tanstack/react-query';
import { identityKey, useAuth } from '@/features/auth/auth-context';
import { listDepartments } from '@/lib/api/client';

/** Departments always come from the API (FE-ARCH-13, FE-ADM-03). Shared with the department selector's key. */
export function useDepartments() {
  const { identity } = useAuth();
  return useQuery({
    queryKey: identityKey(identity, 'departments'),
    queryFn: () => listDepartments(),
    enabled: identity !== null,
  });
}
