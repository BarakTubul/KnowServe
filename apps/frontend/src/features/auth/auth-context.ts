import { createContext, useContext } from 'react';
import type { Identity } from '@/lib/api/client';
import type { AuthGateway } from './gateway-types';

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

/** A global, non-blocking message from the API error handler (FE-AUTH-05). */
export interface ApiNotice {
  kind: 'rate-limited' | 'quota' | 'ai-unavailable';
  message: string;
}

export interface AuthContextValue {
  status: AuthStatus;
  identity: Identity | null;
  gateway: AuthGateway;
  /** Why the user was sent back to login (expired session or Demo), shown once. */
  sessionNotice: string | null;
  /** True after an explicit logout: guards then return to the public entry, not to login. */
  signedOutByUser: boolean;
  clearSessionNotice(): void;
  notice: ApiNotice | null;
  dismissNotice(): void;
  /** Store a new identity returned by the API (also keeps the CSRF token in memory). */
  applyIdentity(identity: Identity): void;
  /** Exchange the current Firebase user for a KnowServe session (`session`) or a Demo conversion. */
  establishSession(
    kind: 'session' | 'convert',
    options?: { forceRefresh?: boolean },
  ): Promise<Identity>;
  /** Anonymous sign-in plus Demo start; a stale Demo identity gets a new one (FE-AUTH-08). */
  startDemo(): Promise<Identity>;
  /** Ends the session; by default the guards then return to the public entry, `toLogin` goes to login. */
  logout(options?: { toLogin?: boolean }): Promise<void>;
  selectDepartment(departmentId: string): Promise<void>;
  departmentSelectorOpen: boolean;
  openDepartmentSelector(): void;
  closeDepartmentSelector(): void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}

/** Identity-scoped query key (FE-ARCH-04): cleared on logout. */
export function identityKey(identity: Identity | null, ...parts: unknown[]): unknown[] {
  return ['identity', identity?.user_id ?? 'none', ...parts];
}

/** Department-scoped query key (FE-ARCH-04, SEC-10): cleared on logout and on a department switch. */
export function departmentKey(identity: Identity | null, ...parts: unknown[]): unknown[] {
  return ['dept', identity?.user_id ?? 'none', identity?.active_department?.id ?? 'none', ...parts];
}
