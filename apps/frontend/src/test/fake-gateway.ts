import { vi } from 'vitest';
import type { AuthGateway, FirebaseUserInfo } from '@/features/auth/gateway-types';

export function firebaseUser(overrides: Partial<FirebaseUserInfo> = {}): FirebaseUserInfo {
  return {
    uid: 'uid-1',
    email: 'ada@example.com',
    emailVerified: true,
    isAnonymous: false,
    providerIds: ['password'],
    lastSignInMs: Date.now(),
    ...overrides,
  };
}

/**
 * A scripted Firebase gateway for component tests (no SDK, no network). Every method is a spy; the
 * `user` field is the signed-in Firebase user the gateway reports.
 */
export function createFakeGateway(initial: FirebaseUserInfo | null = null) {
  const state: { user: FirebaseUserInfo | null; token: string } = {
    user: initial,
    token: 'fake-id-token',
  };
  const gateway = {
    state,
    ready: vi.fn(() => Promise.resolve()),
    currentUser: vi.fn(() => state.user),
    signInWithPassword: vi.fn((email: string, password: string) => {
      void password;
      state.user = firebaseUser({ email });
      return Promise.resolve(state.user);
    }),
    signUpWithPassword: vi.fn((email: string, password: string) => {
      void password;
      state.user = firebaseUser({ email, emailVerified: false });
      return Promise.resolve(state.user);
    }),
    signInWithGoogle: vi.fn(() => {
      state.user = firebaseUser({ email: 'ada@gmail.example', providerIds: ['google.com'] });
      return Promise.resolve(state.user);
    }),
    linkPendingGoogle: vi.fn((email: string, password: string) => {
      void password;
      state.user = firebaseUser({ email, providerIds: ['password', 'google.com'] });
      return Promise.resolve(state.user);
    }),
    cancelPendingLink: vi.fn(),
    signInAnonymously: vi.fn(() => {
      state.user = firebaseUser({
        uid: 'anon-1',
        email: null,
        emailVerified: false,
        isAnonymous: true,
        providerIds: [],
      });
      return Promise.resolve(state.user);
    }),
    getIdToken: vi.fn((forceRefresh?: boolean) => {
      void forceRefresh;
      return Promise.resolve(state.token);
    }),
    reloadUser: vi.fn(() => Promise.resolve(state.user)),
    signOut: vi.fn(() => {
      state.user = null;
      return Promise.resolve();
    }),
    resendVerification: vi.fn(() => Promise.resolve()),
    reauthenticateWithPassword: vi.fn((password: string) => {
      void password;
      return Promise.resolve();
    }),
    reauthenticateWithGoogle: vi.fn(() => Promise.resolve()),
    sendPasswordReset: vi.fn((email: string) => {
      void email;
      return Promise.resolve();
    }),
    verifyResetCode: vi.fn((code: string) => {
      void code;
      return Promise.resolve('ada@example.com');
    }),
    confirmPasswordReset: vi.fn((code: string, newPassword: string) => {
      void code;
      void newPassword;
      return Promise.resolve();
    }),
    applyVerificationCode: vi.fn((code: string) => {
      void code;
      return Promise.resolve();
    }),
    linkEmailPassword: vi.fn((email: string, password: string) => {
      void password;
      state.user = firebaseUser({ email, emailVerified: false });
      return Promise.resolve(state.user);
    }),
    linkGoogle: vi.fn(() => {
      state.user = firebaseUser({ email: 'ada@gmail.example', providerIds: ['google.com'] });
      return Promise.resolve(state.user);
    }),
  } satisfies AuthGateway & { state: typeof state };
  return gateway;
}

export type FakeGateway = ReturnType<typeof createFakeGateway>;
