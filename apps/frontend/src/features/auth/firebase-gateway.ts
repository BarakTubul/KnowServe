import {
  EmailAuthProvider,
  GoogleAuthProvider,
  applyActionCode,
  confirmPasswordReset,
  createUserWithEmailAndPassword,
  linkWithCredential,
  linkWithPopup,
  reauthenticateWithCredential,
  reauthenticateWithPopup,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInAnonymously,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  verifyPasswordResetCode,
  type AuthCredential,
  type User,
} from 'firebase/auth';
import { getFirebaseAuth } from '@/lib/firebase';
import { AuthFlowError, type AuthGateway, type FirebaseUserInfo } from './gateway-types';

export { AuthFlowError } from './gateway-types';
export type { AuthFlowErrorKind, AuthGateway, FirebaseUserInfo } from './gateway-types';

function info(user: User): FirebaseUserInfo {
  const last = user.metadata.lastSignInTime ? Date.parse(user.metadata.lastSignInTime) : NaN;
  return {
    uid: user.uid,
    email: user.email,
    emailVerified: user.emailVerified,
    isAnonymous: user.isAnonymous,
    providerIds: user.providerData.map((p) => p.providerId),
    lastSignInMs: Number.isNaN(last) ? null : last,
  };
}

function codeOf(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code = (error as { code: unknown }).code;
    if (typeof code === 'string') return code;
  }
  return '';
}

function emailOf(error: unknown): string | undefined {
  if (typeof error === 'object' && error !== null && 'customData' in error) {
    const data = (error as { customData?: { email?: unknown } }).customData;
    if (data && typeof data.email === 'string') return data.email;
  }
  return undefined;
}

/** Map a Firebase error onto the cases the UI handles; anything else is `unknown`. */
export function toAuthFlowError(error: unknown): AuthFlowError {
  if (error instanceof AuthFlowError) return error;
  switch (codeOf(error)) {
    case 'auth/invalid-credential':
    case 'auth/invalid-login-credentials':
    case 'auth/wrong-password':
    case 'auth/user-not-found':
    case 'auth/invalid-email':
    case 'auth/user-disabled':
      return new AuthFlowError('invalid-credential');
    case 'auth/email-already-in-use':
      return new AuthFlowError('email-in-use');
    case 'auth/weak-password':
      return new AuthFlowError('weak-password');
    case 'auth/account-exists-with-different-credential':
      return new AuthFlowError('account-exists', emailOf(error));
    case 'auth/credential-already-in-use':
    case 'auth/provider-already-linked':
      return new AuthFlowError('credential-in-use');
    case 'auth/popup-closed-by-user':
    case 'auth/cancelled-popup-request':
      return new AuthFlowError('popup-cancelled');
    case 'auth/popup-blocked':
      return new AuthFlowError('popup-blocked');
    case 'auth/expired-action-code':
      return new AuthFlowError('expired-code');
    case 'auth/invalid-action-code':
      return new AuthFlowError('invalid-code');
    case 'auth/too-many-requests':
      return new AuthFlowError('too-many-requests');
    case 'auth/requires-recent-login':
      return new AuthFlowError('requires-recent-login');
    case 'auth/network-request-failed':
      return new AuthFlowError('network');
    default:
      return new AuthFlowError('unknown');
  }
}

async function guard<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (error) {
    throw toAuthFlowError(error);
  }
}

function requireUser(): User {
  const user = getFirebaseAuth().currentUser;
  if (!user) throw new AuthFlowError('no-user');
  return user;
}

/** Real gateway on the Firebase Web SDK. The SDK is initialised lazily on first use. */
export function createFirebaseGateway(): AuthGateway {
  // A Google credential waits here (memory only) while the user proves the existing password (FE-AUTH-12).
  let pendingGoogle: AuthCredential | null = null;

  return {
    ready: async () => {
      await getFirebaseAuth().authStateReady();
    },
    currentUser: () => {
      const user = getFirebaseAuth().currentUser;
      return user ? info(user) : null;
    },
    signInWithPassword: (email, password) =>
      guard(async () => {
        const { user } = await signInWithEmailAndPassword(getFirebaseAuth(), email, password);
        return info(user);
      }),
    signUpWithPassword: (email, password) =>
      guard(async () => {
        const { user } = await createUserWithEmailAndPassword(getFirebaseAuth(), email, password);
        await sendEmailVerification(user);
        return info(user);
      }),
    signInWithGoogle: () =>
      guard(async () => {
        pendingGoogle = null;
        try {
          const { user } = await signInWithPopup(getFirebaseAuth(), new GoogleAuthProvider());
          return info(user);
        } catch (error) {
          if (codeOf(error) === 'auth/account-exists-with-different-credential') {
            pendingGoogle = GoogleAuthProvider.credentialFromError(
              error as Parameters<typeof GoogleAuthProvider.credentialFromError>[0],
            );
          }
          throw error;
        }
      }),
    linkPendingGoogle: (email, password) =>
      guard(async () => {
        const credential = pendingGoogle;
        if (!credential) throw new AuthFlowError('no-user');
        const { user } = await signInWithEmailAndPassword(getFirebaseAuth(), email, password);
        if (!user.emailVerified) {
          // Never link, and never trust, an unverified password account (AUTH-32).
          await signOut(getFirebaseAuth());
          pendingGoogle = null;
          throw new AuthFlowError('unverified');
        }
        const linked = await linkWithCredential(user, credential);
        pendingGoogle = null;
        return info(linked.user);
      }),
    cancelPendingLink: () => {
      pendingGoogle = null;
    },
    signInAnonymously: () =>
      guard(async () => info((await signInAnonymously(getFirebaseAuth())).user)),
    getIdToken: (forceRefresh = false) => guard(() => requireUser().getIdToken(forceRefresh)),
    reloadUser: async () => {
      const user = getFirebaseAuth().currentUser;
      if (!user) return null;
      await guard(() => user.reload());
      return info(user);
    },
    signOut: () => guard(() => signOut(getFirebaseAuth())),
    resendVerification: () => guard(() => sendEmailVerification(requireUser())),
    reauthenticateWithPassword: (password) =>
      guard(async () => {
        const user = requireUser();
        if (!user.email) throw new AuthFlowError('no-user');
        await reauthenticateWithCredential(
          user,
          EmailAuthProvider.credential(user.email, password),
        );
      }),
    reauthenticateWithGoogle: () =>
      guard(async () => {
        await reauthenticateWithPopup(requireUser(), new GoogleAuthProvider());
      }),
    sendPasswordReset: (email) => guard(() => sendPasswordResetEmail(getFirebaseAuth(), email)),
    verifyResetCode: (code) => guard(() => verifyPasswordResetCode(getFirebaseAuth(), code)),
    confirmPasswordReset: (code, newPassword) =>
      guard(() => confirmPasswordReset(getFirebaseAuth(), code, newPassword)),
    applyVerificationCode: (code) => guard(() => applyActionCode(getFirebaseAuth(), code)),
    linkEmailPassword: (email, password) =>
      guard(async () => {
        const user = requireUser();
        const linked = await linkWithCredential(
          user,
          EmailAuthProvider.credential(email, password),
        );
        await sendEmailVerification(linked.user);
        return info(linked.user);
      }),
    linkGoogle: () =>
      guard(async () => info((await linkWithPopup(requireUser(), new GoogleAuthProvider())).user)),
  };
}
