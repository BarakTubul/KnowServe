import { Link, Outlet } from 'react-router-dom';
import { useAuth } from '@/features/auth/auth-context';
import { adminText } from './admin-text';

/** What a non-Admin sees on an Admin route (FE-ADM-01). The API answers 403 for the same calls (SEC-15). */
export function NotAvailableView() {
  return (
    <main data-testid="admin-not-available" className="mx-auto flex max-w-md flex-col gap-3 p-6">
      <h1 className="text-xl font-semibold">{adminText.notAvailableTitle}</h1>
      <p>{adminText.notAvailableBody}</p>
      <Link to="/dashboard" className="underline">
        {adminText.backToDashboard}
      </Link>
    </main>
  );
}

/**
 * Admin routes (FE-ADM-01, FE-ARCH-07). Used inside `RequireAuth`, which has already resolved the
 * session. This is UX only: the Admin role comes from the server's identity and every call is checked
 * there again. Admin routes need no active department.
 */
export function RequireAdmin() {
  const { identity } = useAuth();
  if (identity?.kind !== 'admin') return <NotAvailableView />;
  return <Outlet />;
}
