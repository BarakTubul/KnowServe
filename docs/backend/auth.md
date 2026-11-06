# Backend auth, sessions and identities

**Status:** Target spec (M1), revised 2026-11-06 for **Firebase Authentication** (OPEN-24). Not implemented: the legacy code uses JWT, self-registered roles and no email verification (see "Current implementation").

## Purpose
This is the focused FastAPI auth module. Credentials are handled by **Firebase Authentication** (Email/Password and Google Sign-In). The API verifies a Firebase ID token once at login and then issues its **own opaque, DB-backed session**. CSRF, Try Demo visitors, the single private Admin and the active department stay in KnowServe. The API never receives or stores a password. Access-control rules are in `../cross-cutting/security-and-permissions.md`. Approved decisions: OPEN-04, OPEN-12, OPEN-14, OPEN-24 (`../open-decisions.md`). OPEN-15 and the registration part of OPEN-14 are amended by OPEN-24 (see AUTH-02, AUTH-03).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| AUTH-01 | Users sign up with **email and password through Firebase Authentication** (client SDK). The email address is the login identifier; there are no usernames. KnowServe stores **no password and no password hash** (no custom password storage). A `users` row is created on the first successful session exchange (AUTH-30), keyed by the Firebase `uid`, with the email normalized (trimmed, lower-case). | M1 |
| AUTH-02 | Sign-in failures and password-reset requests do not reveal whether an email is registered: Firebase **email enumeration protection stays enabled**. **Known deviation from OPEN-14 (OPEN-24, to be confirmed as D8):** the Firebase client signup returns "email already in use", so signup reveals an existing email. A server-side signup that hides it would need custom mail and password handling, which is out of scope. | M1 |
| AUTH-03 | Password policy (demo; amends OPEN-15): the minimum is **8 characters** with **no composition rules**, long passphrases and Unicode accepted, **enforced by Firebase's password policy** (mechanism and any Identity Platform upgrade: D8). Because KnowServe never sees a password, the common-password blocklist and breach check of OPEN-15 are **not enforceable server-side and are dropped**; the frontend may warn, but that is UX only. The 8-character minimum is a demo choice and is not described as meeting the stricter NIST single-factor recommendation. | M1 |
| AUTH-04 | There is exactly one private **Admin** identity: a Firebase **email/password** account created out of band (Firebase console or Admin SDK) and marked Admin in the `users` table by a seed command keyed by its Firebase `uid` (configuration, not a secret). The role is never derived from the email, a client-supplied value or a token claim a user can influence. A session for the Admin is created **only** when the token's sign-in provider is `password`; a Google sign-in for the Admin email is refused with the generic failure. No public API or UI path can create or elevate to Admin. | M1 |
| AUTH-06 | A successful session exchange (AUTH-30) for a verified user creates a new **opaque random session token**. Only a **hash** of the token is stored in PostgreSQL. The token is set in a `Secure`, `HttpOnly`, `SameSite=Lax`, **host-only** cookie on the API host (OPEN-04). Any pre-existing session id is not reused, which rotates the session against fixation. The Firebase ID token is verified, then discarded; it is never stored or logged. | M1 |
| AUTH-07 | An invalid, expired, forged, wrong-audience or disallowed-provider ID token returns the same `401` with the same generic message (unverified email: AUTH-13). A wrong email or password is reported by Firebase with its generic invalid-credential error. | M1 |
| AUTH-08 | Logout revokes the server-side session (the row is invalidated) and clears the cookie; the frontend also signs out of Firebase. | M1 |
| AUTH-09 | A "current identity" endpoint returns the identity type (registered/visitor/admin), its display data, the sign-in method and the active department for a valid session, and `401` otherwise. It also returns the session's CSRF token (AUTH-14). | M1 |
| AUTH-10 | Each request is validated by hashing the cookie token and looking up an unexpired, unrevoked session. Expired or revoked sessions get `401`. Sessions have an expiration (value OPEN-05). | M1 |
| AUTH-11 | Admin-only routes return `403` to registered users and visitors (SEC-03). | M1 |
| AUTH-13 | **Email verification is mandatory for password signups.** Firebase sends the verification email. The session exchange rejects any token with `email_verified = false` with `403 EMAIL_NOT_VERIFIED` and creates no session. An unverified account cannot access protected resources. Google accounts arrive with a verified email, and the claim is still checked. | M1 |
| AUTH-14 | Every cookie-authenticated state-changing request requires **both** a valid CSRF token bound to the session **and** an `Origin` matching an allowed frontend origin; otherwise it is rejected (OPEN-04). CORS is not treated as a CSRF defense. The token is returned by AUTH-09 and by the session exchange and is sent as `X-CSRF-Token`. The session exchange itself has no session yet, so it requires the Origin check and a rate limit instead of a CSRF token. | M1 |
| AUTH-15 | Brute-force protection: Firebase throttles its own sign-in, signup and reset endpoints (not tunable by us). KnowServe additionally rate-limits the session exchange (per IP and per `uid`) and Try Demo creation (values OPEN-05). | M1 |
| AUTH-16 | **Try Demo** creates a distinct, temporary anonymous visitor identity and session without signup. It is **KnowServe's own** visitor session (it does not use Firebase Anonymous Auth), separate from registered accounts, isolated per visitor and department (SEC-16), and expires and is purged (lifetime OPEN-05). | M1 |
| AUTH-17 | The active department is stored server-side on the session. Every registered user and Try Demo visitor (and the Admin) may select and switch among **all** seeded departments (OPEN-12, Demo Mode). An operation that needs an active department when none is set returns **409 `ACTIVE_DEPARTMENT_REQUIRED`** (OPEN-14). A switch never carries over data or context from the previous department (SEC-10). | M1 |
| AUTH-18 | JWT is **not** used as the primary session scheme (the Firebase ID token is used only for the one-time exchange), and Starlette's signed-cookie `SessionMiddleware` is **not** used as the session store. | M1 |
| AUTH-19 | **Same-origin API route** (mechanism of OPEN-04 superseded by OPEN-21, approved provisionally pending spike validation): the browser calls one origin; a Cloudflare Pages Function forwards `/api/v1/*` to the Cloud Run API (`../contracts/proxy.md`). Cookies stay host-only on that origin, so production needs no cross-site cookie and no CORS. The API accepts requests only with the proxy secret (403 `DIRECT_ACCESS_DENIED` otherwise) and trusts the forwarded client IP only after that check. `KS_API_ALLOWED_ORIGINS` is the single app origin used by the Origin check. Cloud Run Domain Mapping and `SameSite=None` workarounds are not used. | M0 spike / M1 |
| AUTH-20 | A departments endpoint returns the seeded departments. There is no department or user CRUD in the MVP (PROD-03). | M1 |
| AUTH-21 | Auth and security events (session exchange success/failure by provider and reason, `EMAIL_NOT_VERIFIED`, account conflict, Try Demo start, logout, session revocation, admin actions) are audit-logged without ID tokens, session tokens, cookies or CSRF values (MON-04, MON-05). Password signup, verification and reset happen inside Firebase and are not visible to the API. | M1 |
| AUTH-29 | **Firebase Authentication is the only credential system.** Providers enabled: Email/Password and Google. No other provider, no phone, no email-link or one-time-code login, and no Firebase Anonymous Auth. Email OTP is removed from the MVP (OPEN-24). | M1 |
| AUTH-30 | **Session exchange** `POST /v1/auth/session` takes a Firebase ID token and verifies its signature against Google's public keys, issuer, audience (the Firebase project id), expiry, `auth_time` within a short window (initially 5 minutes, so a stolen old token cannot start a session), `email_verified = true`, and a `sign_in_provider` of `password` or `google.com` (anonymous and any other value are refused). On success it loads or creates the `users` row by `uid` and issues the session of AUTH-06. The verifier sits behind an interface so tests use a fake. | M1 |
| AUTH-31 | **Google Sign-In** is offered on the same login screen as email/password (FE-AUTH-02). It uses the Firebase SDK; the API sees only a Firebase ID token and never a Google token. The Admin cannot sign in with Google (AUTH-04). | M1 |
| AUTH-32 | **Account linking is safe.** There is one KnowServe user per Firebase `uid`, and KnowServe never merges or links accounts by matching email itself. Firebase's "one account per email" setting is enabled. A Google sign-in for an email that already has a password account is completed only after the user signs in with the existing method and links the credential in the client. An **unverified** password account is never linked or trusted. The `users.email` column is unique: a different `uid` presenting an already-used email is refused with the generic failure and an audit entry. | M1 |
| AUTH-33 | **Password reset** uses Firebase's reset email. The reset request shows the same confirmation whether or not the email exists (AUTH-02). The reset and verification links open a KnowServe action page that handles success, expired and invalid codes. A reset does not by itself end existing KnowServe sessions: they stay valid until expiry or logout, and a "sign out everywhere" call (`POST /v1/auth/sessions/revoke-all`, CSRF-protected) revokes all of the user's sessions. See Known gaps. | M1 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| AUTH-05 | One manager per department | The target has no manager/employee roles (PROD-02). |
| AUTH-12 | Public registration must not choose the admin role | Merged into AUTH-04. |
| AUTH-22..AUTH-28 | Email OTP request, code, verification, rate limits, "not MFA", logging, parameters | Email OTP removed from the MVP by the user on 2026-11-06 (OPEN-24). The OTP-specific tests are retired with them. |

## Required tests
Integration tests fake the Firebase token verifier (AUTH-30). The Firebase Auth emulator may be used in CI for end-to-end flows. No test calls real Firebase except the deployed smoke.

| Req | Level | Scenario | Expected |
|---|---|---|---|
| AUTH-01 | integration | First session exchange for a new `uid` | `users` row with normalized email and the `uid`; no password or hash column exists in the schema |
| AUTH-02 | review + e2e (emulator or deployed) | Sign in with a wrong password vs an unknown email; reset for an existing vs unknown email | identical UI results; the signup "email already in use" deviation is documented and shown as a neutral message |
| AUTH-03 | review | Firebase password policy configuration; search the target code for password handling | minimum 8 configured; no password hashing, blocklist or password parameter anywhere in the API |
| AUTH-04 | integration | Seeded Admin `uid`; a token for another `uid` with the Admin's email; a Google-provider token for the Admin; a payload with `role: admin` | Admin session only for the seeded `uid` with provider `password`; the others are refused or get no Admin role |
| AUTH-06 | integration | Session exchange by password provider and by Google provider | same session type; cookie `Secure`+`HttpOnly`+`SameSite=Lax`, no `Domain`; DB stores a hash ≠ cookie value; a pre-login session id is not reused; the ID token appears nowhere in the DB or logs |
| AUTH-07 | integration | Forged, expired, wrong-audience, wrong-issuer and malformed tokens | identical 401 bodies |
| AUTH-08 | integration | Logout, then reuse the old cookie | 401 |
| AUTH-09 | integration | With a user, visitor or admin session / with none | correct identity, sign-in method, department and CSRF token / 401 |
| AUTH-10 | integration | Expired session; tampered token | 401 |
| AUTH-11 | integration | Admin route as a registered user and as a visitor | 403 (with SEC-03) |
| AUTH-13 | integration | Token with `email_verified=false`; with true | 403 `EMAIL_NOT_VERIFIED`, no session / session |
| AUTH-14 | integration | Mutation with no CSRF token / wrong token / another session's token / valid token but foreign or missing `Origin` / valid token + allowed origin; session exchange with a foreign `Origin` | rejected ×4 / accepted; exchange rejected |
| AUTH-15 | integration | N+1 session exchanges from one IP; for one `uid`; Try Demo creation above the limit | throttled in each case (429 `RATE_LIMITED`) |
| AUTH-16 | integration | Two demo visitors; visitor after expiry; purge | isolated; 401; data removed |
| AUTH-17 | integration | Visitor selects each seeded department; switch, then request the previous department's conversation; department-scoped call with none selected | all allowed; 404; 409 `ACTIVE_DEPARTMENT_REQUIRED` |
| AUTH-18 | review/unit | Search for JWT session use and SessionMiddleware in target code | the ID token is verified only in the exchange; no other JWT use |
| AUTH-19 | e2e (deploy smoke) | Request straight to the Cloud Run API URL without the secret; the same call through `/api` on the app origin; cookie set through the proxy | 403 `DIRECT_ACCESS_DENIED` / success; the cookie is host-only, HttpOnly, Secure, SameSite=Lax and hidden from page JavaScript |
| AUTH-20 | integration | GET departments | seeded list; no create/update/delete routes |
| AUTH-21 | integration | Failed and successful exchanges; revoke-all | audit entries without the ID token, cookie or CSRF value |
| AUTH-29 | review | Provider configuration and code | only password and Google; no anonymous, email-link or OTP code path |
| AUTH-30 | integration | Token older than the `auth_time` window; anonymous-provider token; provider outside the allow-list | refused with the generic 401 |
| AUTH-31 | e2e (emulator or deployed) | Google sign-in for a new user and for the Admin email | session for the new user; refused for the Admin |
| AUTH-32 | integration + component | Two `uid`s with one email; Google sign-in for an email with an unverified password account; existing verified account and link flow | second `uid` refused and audited; no merge or trust of the unverified account; link only after sign-in with the existing method |
| AUTH-33 | integration + component | Reset flow pages (success/expired/invalid); sign out everywhere with two sessions | three distinct states; both sessions revoked, CSRF required |

## Current implementation (LEGACY, not migrated)
- `routers/auth.py`, `services/auth_service.py` and `utils/jwt.py` issue a **JWT** (python-jose) with `user_id`, `role` and `department_id`. It is read from the `token` cookie or `Authorization: Bearer`, and the cookie has `secure=False`.
- Passwords are hashed with passlib argon2 (`utils/hashing.py`). The target stores no passwords at all (AUTH-01).
- `RegisterRequest.role` is client-controlled (`employee`/`manager`/`admin`), so anyone can register as Admin if none exists. This contradicts AUTH-04.
- Roles employee/manager/admin; a user has a single fixed `department_id`.
- There is no email verification, Email OTP, CSRF, rate limiting, Try Demo, department switch, departments endpoint or audit logging. `/auth/me` returns the raw JWT payload.
- The legacy signup schema requires an uppercase letter and a digit; AUTH-03 drops those composition rules.

## Known gaps
Every AUTH requirement is unimplemented on the target stack. Consequences of the Firebase decision that are not hidden:
- Signup reveals an existing email (AUTH-02) and the password blocklist is dropped (AUTH-03). Both need the user's confirmation (D8 in `../milestones/M1/plan.md`).
- A password reset or a disabled Firebase user does not end existing KnowServe sessions until they expire or the user signs out everywhere (AUTH-33). Session lifetimes (OPEN-05) bound the exposure.
- Firebase behavior for account linking, enumeration protection, the password policy and the unverified-account rules is from general knowledge and must be checked against current documentation and the real project (M1-01, M1-08).

## Related docs
`architecture.md`, `../cross-cutting/security-and-permissions.md`, `../frontend/auth.md`, `../cross-cutting/product-and-ux.md`, `../open-decisions.md`
