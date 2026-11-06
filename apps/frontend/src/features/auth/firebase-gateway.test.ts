import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  sendEmailVerification: vi.fn(async () => undefined),
  sendPasswordResetEmail: vi.fn(async () => undefined),
  createUserWithEmailAndPassword: vi.fn(async () => ({
    user: {
      uid: 'u1',
      email: 'a@example.test',
      emailVerified: false,
      isAnonymous: false,
      providerData: [],
      metadata: {},
    },
  })),
  linkWithCredential: vi.fn(async () => ({
    user: {
      uid: 'u1',
      email: 'a@example.test',
      emailVerified: false,
      isAnonymous: false,
      providerData: [],
      metadata: {},
    },
  })),
  currentUser: {
    uid: 'u1',
    email: 'a@example.test',
    emailVerified: false,
    isAnonymous: false,
    providerData: [],
    metadata: {},
  },
}));

vi.mock('firebase/auth', () => ({
  EmailAuthProvider: { credential: vi.fn(() => ({})) },
  GoogleAuthProvider: class {},
  applyActionCode: vi.fn(),
  confirmPasswordReset: vi.fn(),
  createUserWithEmailAndPassword: mocks.createUserWithEmailAndPassword,
  linkWithCredential: mocks.linkWithCredential,
  linkWithPopup: vi.fn(),
  reauthenticateWithCredential: vi.fn(),
  reauthenticateWithPopup: vi.fn(),
  sendEmailVerification: mocks.sendEmailVerification,
  sendPasswordResetEmail: mocks.sendPasswordResetEmail,
  signInAnonymously: vi.fn(),
  signInWithEmailAndPassword: vi.fn(),
  signInWithPopup: vi.fn(),
  signOut: vi.fn(),
  verifyPasswordResetCode: vi.fn(),
}));

vi.mock('@/lib/firebase', () => ({
  getFirebaseAuth: () => ({ currentUser: mocks.currentUser }),
}));

import { actionCodeSettings, createFirebaseGateway } from './firebase-gateway';

// FE-AUTH-07: Firebase's default action handler is used; each email only carries a continue URL
// that returns the user to this app's /login page.
describe('FE-AUTH-07 email action continue URL', () => {
  beforeEach(() => vi.clearAllMocks());

  it('is built from the running origin, not a hardcoded host', () => {
    expect(actionCodeSettings()).toEqual({ url: `${window.location.origin}/login` });
    expect(actionCodeSettings()).not.toHaveProperty('handleCodeInApp');
  });

  it('is passed to the signup verification, resend, link verification and reset emails', async () => {
    const expected = { url: `${window.location.origin}/login` };
    const gateway = createFirebaseGateway();

    await gateway.signUpWithPassword('a@example.test', 'correct horse 1');
    await gateway.resendVerification();
    await gateway.linkEmailPassword('a@example.test', 'correct horse 1');
    await gateway.sendPasswordReset('a@example.test');

    const verification = mocks.sendEmailVerification.mock.calls as unknown[][];
    expect(verification).toHaveLength(3);
    for (const call of verification) expect(call[1]).toEqual(expected);
    const reset = mocks.sendPasswordResetEmail.mock.calls as unknown[][];
    expect(reset[0]?.[2]).toEqual(expected);
  });
});
