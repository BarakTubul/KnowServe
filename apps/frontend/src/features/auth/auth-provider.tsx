import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  convertDemo,
  createSession,
  getMe,
  logout as apiLogout,
  setActiveDepartment,
  startDemo as apiStartDemo,
  type Identity,
} from '@/lib/api/client';
import { setCsrfToken } from '@/lib/api/csrf';
import { ApiError } from '@/lib/api/errors';
import { subscribeApiErrors } from '@/lib/api/events';
import {
  AuthContext,
  type ApiNotice,
  type AuthContextValue,
  type AuthStatus,
} from './auth-context';
import { createFirebaseGateway } from './firebase-gateway';
import type { AuthGateway } from './gateway-types';
import { describeApiError } from './messages';

interface AuthProviderProps {
  children: ReactNode;
  /** Tests inject a fake; the app uses the Firebase SDK. */
  gateway?: AuthGateway;
}

const SESSION_ENDED = 'Your session ended. Sign in again to continue.';
const DEMO_ENDED = 'Your Demo session ended. Start a new Demo or sign in.';

export function AuthProvider({ children, gateway: injected }: AuthProviderProps) {
  const queryClient = useQueryClient();
  const [gateway] = useState<AuthGateway>(() => injected ?? createFirebaseGateway());
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const [notice, setNotice] = useState<ApiNotice | null>(null);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [signedOutByUser, setSignedOutByUser] = useState(false);
  const identityRef = useRef<Identity | null>(null);

  const applyIdentity = useCallback(
    (next: Identity) => {
      // A different user must never see the previous user's cached data.
      if (identityRef.current && identityRef.current.user_id !== next.user_id) queryClient.clear();
      identityRef.current = next;
      setCsrfToken(next.csrf_token); // memory only (FE-AUTH-06)
      setIdentity(next);
      setStatus('authenticated');
      setSessionNotice(null);
      setSignedOutByUser(false);
    },
    [queryClient],
  );

  /** Drop everything identity-scoped without calling the API (a 401 already says the session is gone). */
  const clearIdentity = useCallback(
    (message: string | null, byUser = false) => {
      identityRef.current = null;
      setCsrfToken(null);
      queryClient.clear();
      setIdentity(null);
      setStatus('anonymous');
      setSelectorOpen(false);
      setSessionNotice(message);
      setSignedOutByUser(byUser);
    },
    [queryClient],
  );

  // FE-AUTH-01: hydrate from the current-identity endpoint; guards show a loader until it settles.
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) applyIdentity(me);
      })
      .catch(() => {
        if (!cancelled) setStatus('anonymous');
      });
    return () => {
      cancelled = true;
    };
  }, [applyIdentity]);

  // FE-AUTH-05 / FE-ARCH-03: global handling of errors from authenticated calls.
  useEffect(
    () =>
      subscribeApiErrors((error) => {
        if (error.status === 401 && error.code !== 'REAUTH_REQUIRED') {
          clearIdentity(error.code === 'DEMO_EXPIRED' ? DEMO_ENDED : SESSION_ENDED);
        } else if (error.status === 409 && error.code === 'ACTIVE_DEPARTMENT_REQUIRED') {
          setSelectorOpen(true);
        } else if (
          error.status === 429 &&
          (error.code === 'RATE_LIMITED' || error.code === 'QUOTA_EXCEEDED')
        ) {
          setNotice({
            kind: error.code === 'QUOTA_EXCEEDED' ? 'quota' : 'rate-limited',
            message: describeApiError(error),
          });
        } else if (error.status === 503 && error.code === 'AI_UNAVAILABLE') {
          setNotice({ kind: 'ai-unavailable', message: describeApiError(error) });
        }
      }),
    [clearIdentity],
  );

  const establishSession = useCallback<AuthContextValue['establishSession']>(
    async (kind, options) => {
      // The ID token exists only inside this call; it is never put into state or storage.
      const token = await gateway.getIdToken(options?.forceRefresh ?? false);
      const next = kind === 'convert' ? await convertDemo(token) : await createSession(token);
      applyIdentity(next);
      return next;
    },
    [gateway, applyIdentity],
  );

  const startDemo = useCallback<AuthContextValue['startDemo']>(async () => {
    const attempt = async () => {
      await gateway.signInAnonymously();
      return apiStartDemo(await gateway.getIdToken());
    };
    let next: Identity;
    try {
      next = await attempt();
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'DEMO_EXPIRED') throw error;
      // The old anonymous identity is past its 24 hours: leave it and start a new Demo (FE-AUTH-08).
      await gateway.signOut();
      next = await attempt();
    }
    applyIdentity(next);
    return next;
  }, [gateway, applyIdentity]);

  const logout = useCallback<AuthContextValue['logout']>(
    async (options) => {
      try {
        await apiLogout();
      } catch {
        // The local state is cleared either way; the server session ends at its 24 hours at the latest.
      }
      try {
        await gateway.signOut();
      } catch {
        // Same: nothing the user can do about it here.
      }
      clearIdentity(null, !options?.toLogin);
    },
    [gateway, clearIdentity],
  );

  const selectDepartment = useCallback<AuthContextValue['selectDepartment']>(
    async (departmentId) => {
      const next = await setActiveDepartment(departmentId);
      // SEC-10: nothing of the previous department may stay in the cache.
      queryClient.removeQueries({ queryKey: ['dept'] });
      applyIdentity(next);
      setSelectorOpen(false);
    },
    [queryClient, applyIdentity],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      identity,
      gateway,
      sessionNotice,
      signedOutByUser,
      clearSessionNotice: () => setSessionNotice(null),
      notice,
      dismissNotice: () => setNotice(null),
      applyIdentity,
      establishSession,
      startDemo,
      logout,
      selectDepartment,
      departmentSelectorOpen: selectorOpen,
      openDepartmentSelector: () => setSelectorOpen(true),
      closeDepartmentSelector: () => setSelectorOpen(false),
    }),
    [
      status,
      identity,
      gateway,
      sessionNotice,
      signedOutByUser,
      notice,
      applyIdentity,
      establishSession,
      startDemo,
      logout,
      selectDepartment,
      selectorOpen,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
