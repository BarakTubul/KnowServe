# ADR 0004: Firebase as identity provider, KnowServe sessions, freshness and the verifier

Status: accepted (OPEN-24, OPEN-25, OPEN-26). Date: 2026-11-06.

## Decision
- Firebase Authentication (standard, no Identity Platform) proves identity: Email/Password, Google, Anonymous. KnowServe keeps its own opaque PostgreSQL sessions and all authorization.
- A Firebase ID token is verified once, at a session-creating endpoint, and discarded. Sessions last an absolute 24 h and are never extended.
- **Freshness:** session creation requires `auth_time` within 5 minutes (`KS_AUTH_MAX_AGE_SECONDS`). Without it, Firebase's persistent browser login would let the app silently mint a new 24 h session after expiry, which is an extension. A stale but valid token gets 401 `REAUTH_REQUIRED` and the client asks for the credential again (this also covers verifying an email later than 5 minutes). Conversion is authenticated by the Demo session plus a token whose `iat` is within the window, because linking a credential does not refresh `auth_time`.
- **Verifier:** Firebase Admin SDK behind the `TokenVerifier` interface. With the emulator host configured it accepts unsigned emulator tokens, so backend tests use the real verification path without the network. The emulator host is refused when `KS_ENV=production` (settings validator).
- **CSRF token delivery:** the per-session secret is returned by `/v1/auth/me` and by every session-creating response, and sent as `X-CSRF-Token`. The session-creating endpoints use the Origin check and the fresh token instead.
- Demo users are Firebase anonymous accounts with a KnowServe `demo` identity; conversion links a credential in Firebase, then the API changes `users.kind` in one transaction and replaces the session.

## Consequences
- No per-request Firebase call. A password reset or a Firebase-side disable does not end existing sessions in M1 (O2); KnowServe-side disable and "sign out everywhere" do.
- Anonymous Firebase accounts are never deleted by KnowServe (N2).
- Firebase behavior used here (anonymous linking, claims after linking, enumeration protection, password policy) is verified by emulator tests and the pre-release real-Firebase smoke.

## Observed on the Firebase Auth Emulator (firebase-tools 15.35.0, 2026-11-06)
The Admin SDK verifies emulator tokens in emulator mode. Linking an email/password credential to an anonymous account keeps the same `uid`; the next token has `sign_in_provider = password`, `email_verified = false` until the email is verified, and an unchanged old `auth_time` with a fresh `iat`, which confirms the conversion rule above. A second account cannot take an email that is already registered (`EMAIL_EXISTS`). A password sign-in produces a fresh `auth_time`. These are emulator results; the real service is checked by the pre-release smoke.
