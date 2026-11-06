import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './auth-context';

export function AuthLoader() {
  return (
    <main
      data-testid="auth-loading"
      aria-busy="true"
      className="flex min-h-screen items-center justify-center p-6"
    >
      <p role="status" className="text-muted-foreground">
        Loading...
      </p>
    </main>
  );
}

/** Protected routes: a loader while the identity resolves (FE-AUTH-01), then login without a session. */
export function RequireAuth() {
  const { status, signedOutByUser } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <AuthLoader />;
  if (status === 'anonymous' && signedOutByUser) return <Navigate to="/" replace />;
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

/** The login screen is for visitors; a signed-in user goes on to the dashboard. */
export function GuestOnly() {
  const { status } = useAuth();
  if (status === 'loading') return <AuthLoader />;
  if (status === 'authenticated') return <Navigate to="/dashboard" replace />;
  return <Outlet />;
}
