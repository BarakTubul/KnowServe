/** What the UI needs to know about the Firebase user. It never contains tokens. */
export interface FirebaseUserInfo {
  uid: string;
  email: string | null;
  emailVerified: boolean;
  isAnonymous: boolean;
  /** Provider ids linked to the user, for example `password` and `google.com`. */
  providerIds: string[];
  /** Time of the user's last sign-in, in epoch milliseconds. */
  lastSignInMs: number | null;
}

export type AuthFlowErrorKind =
  | 'invalid-credential'
  | 'email-in-use'
  | 'weak-password'
  | 'account-exists'
  | 'credential-in-use'
  | 'popup-cancelled'
  | 'popup-blocked'
  | 'expired-code'
  | 'invalid-code'
  | 'too-many-requests'
  | 'requires-recent-login'
  | 'network'
  | 'no-user'
  | 'unverified'
  | 'unknown';

/** A Firebase failure reduced to the cases the UI distinguishes (FE-AUTH-02, 03, 07, 12, 13). */
export class AuthFlowError extends Error {
  readonly kind: AuthFlowErrorKind;
  /** The email the failure refers to, when Firebase reports it (account linking). */
  readonly email: string | undefined;

  constructor(kind: AuthFlowErrorKind, email?: string) {
    super(kind);
    this.name = 'AuthFlowError';
    this.kind = kind;
    this.email = email;
  }
}

/** The seam between the UI and the Firebase SDK. Tests inject a fake (FE-AUTH test table). */
export interface AuthGateway {
  /** Resolves once the SDK has restored its own persisted user (tab-scoped). */
  ready(): Promise<void>;
  currentUser(): FirebaseUserInfo | null;
  signInWithPassword(email: string, password: string): Promise<FirebaseUserInfo>;
  /** Creates the account and sends the verification email. */
  signUpWithPassword(email: string, password: string): Promise<FirebaseUserInfo>;
  /** Google popup. Throws `account-exists` (with the email) when a password account owns it. */
  signInWithGoogle(): Promise<FirebaseUserInfo>;
  /** Signs in with the password, then links the Google credential held from `signInWithGoogle`. */
  linkPendingGoogle(email: string, password: string): Promise<FirebaseUserInfo>;
  cancelPendingLink(): void;
  signInAnonymously(): Promise<FirebaseUserInfo>;
  /** A fresh ID token for one API call. Callers must not keep it. */
  getIdToken(forceRefresh?: boolean): Promise<string>;
  reloadUser(): Promise<FirebaseUserInfo | null>;
  signOut(): Promise<void>;
  resendVerification(): Promise<void>;
  reauthenticateWithPassword(password: string): Promise<void>;
  reauthenticateWithGoogle(): Promise<void>;
  sendPasswordReset(email: string): Promise<void>;
  /** Returns the account email the code belongs to. */
  verifyResetCode(code: string): Promise<string>;
  confirmPasswordReset(code: string, newPassword: string): Promise<void>;
  applyVerificationCode(code: string): Promise<void>;
  /** Demo upgrade: links an email + password to the anonymous user and sends the verification email. */
  linkEmailPassword(email: string, password: string): Promise<FirebaseUserInfo>;
  /** Demo upgrade: links Google (popup) to the anonymous user. */
  linkGoogle(): Promise<FirebaseUserInfo>;
}
