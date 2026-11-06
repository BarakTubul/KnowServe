# Auth and session contract (M1)

Requirements: AUTH-04, 06..10, 14..17, 29..36, SEC-01, 03, 13, 17. Decisions: OPEN-24, OPEN-25, OPEN-26. Rationale: `../adr/0004-firebase-identity-and-sessions.md`. Behavior lives in `../backend/auth.md`; this file fixes only the shapes the workstreams share. Changes need Owner approval and notice to dependent workstreams first (WF-03).

## Flow
1. The browser signs in with the Firebase SDK (Email/Password, Google or Anonymous) and holds a Firebase ID token.
2. It calls one session-creating endpoint with `{"id_token": "..."}`. The API verifies the token (`TokenVerifier`), creates a KnowServe session and answers with the identity, the CSRF token and `Set-Cookie`.
3. Every later request carries the cookie. The API never looks at Firebase again for that session (O2).

## Endpoints
| Route | Auth | Body | Result | Notes |
|---|---|---|---|---|
| `POST /v1/auth/session` | Origin check, fresh ID token | `{id_token}` | 200 `IdentityResponse` + cookie | providers `password`, `google.com`; `email_verified` required; completes a pending Demo conversion for the same uid |
| `POST /v1/demo/start` | Origin check, fresh ID token | `{id_token}` | 200 `IdentityResponse` + cookie | provider `anonymous` only; rate limited per IP |
| `POST /v1/auth/convert` | Demo session + CSRF + Origin; ID token issued within the freshness window | `{id_token}` | 200 `IdentityResponse` + new cookie | revokes the Demo session; new 24 h session (O3) |
| `GET /v1/auth/me` | session | none | 200 `IdentityResponse` | hydrates the frontend and returns the CSRF token |
| `POST /v1/auth/logout` | session + CSRF + Origin | none | 204, cookie cleared | |
| `POST /v1/auth/sessions/revoke-all` | session + CSRF + Origin | none | 200 `{revoked}` | "Sign out everywhere" |
| `GET /v1/departments` | session | none | 200 `{departments: [...]}` | the five seeded departments |
| `PUT /v1/session/department` | session + CSRF + Origin | `{department_id}` | 200 `IdentityResponse` | persists `users.last_active_department_id` |
| `GET /v1/admin/ping` | session, Admin | none | 200 `{status:"ok"}` | proves the Admin guard (SEC-03) |

The models are in `apps/api/src/knowserve_api/schemas.py` and the generated `openapi.json`.

## Session cookie
Name `KS_SESSION_COOKIE_NAME` (default `ks_session`); value is `secrets.token_urlsafe(32)`; `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, **no `Domain`**; `Max-Age` equals the remaining lifetime. Only `sha256(token)` is stored (`sessions.token_hash`). `expires_at = created_at + KS_SESSION_TTL_SECONDS` (24 h) for every kind and is never updated by use. A new session never reuses an old id.

## CSRF and Origin
- Every cookie-authenticated mutation (`POST`, `PUT`, `PATCH`, `DELETE`) needs header `X-CSRF-Token` equal to `sessions.csrf_secret` **and** an `Origin` header in `KS_API_ALLOWED_ORIGINS`. Failures: 403 `CSRF_INVALID` or `ORIGIN_INVALID`.
- The session-creating endpoints have no session yet: they require the Origin check and a fresh token instead.
- The Pages Function already forwards `X-CSRF-Token` and `Origin` (`proxy.md`).

## Identity dependencies (`knowserve_api.auth`, M1-02a)
`get_identity` (401 without a valid session), `require_registered` (kind `registered` or `admin`), `require_admin` (403 otherwise), `require_active_department` (409 `ACTIVE_DEPARTMENT_REQUIRED`). The type is `knowserve_core.identity.Identity`. Authorization for Admin comes only from `users.kind = 'admin'` for the session's user (AUTH-04); it never reads the email, provider or request fields.

## Token verification (`knowserve_core.firebase_tokens`)
`TokenVerifier.verify(id_token, require_fresh=True) -> VerifiedToken`. Checks: signature, issuer `https://securetoken.google.com/<project>`, audience `KS_FIREBASE_PROJECT_ID`, expiry, `iat` not older than `KS_AUTH_MAX_AGE_SECONDS`, and with `require_fresh` also `auth_time` within that window.
- `InvalidToken` is the generic 401. `StaleSignIn` (only after every other check passed) is 401 `REAUTH_REQUIRED`. `VerifierUnavailable` is 503 and fails closed.
- Endpoint rules on top of the token: `/v1/auth/session` needs `email_verified` (else 403 `EMAIL_NOT_VERIFIED`) and a provider in {`password`, `google.com`}; `/v1/demo/start` needs `anonymous`; `/v1/auth/convert` needs a non-anonymous provider and `email_verified`.
- The Firebase Admin SDK is the implementation. With `KS_FIREBASE_AUTH_EMULATOR_HOST` set it accepts the emulator's unsigned tokens; the settings validator refuses that key when `KS_ENV=production`.

## Error codes added by M1
| Status | Code | When |
|---|---|---|
| 401 | `UNAUTHENTICATED` | no/expired/revoked session, or any invalid ID token |
| 401 | `REAUTH_REQUIRED` | valid token whose sign-in is older than the freshness window |
| 401 | `DEMO_EXPIRED` | the Demo identity is past its 24 hours |
| 403 | `EMAIL_NOT_VERIFIED` | password account whose email is not verified |
| 403 | `CSRF_INVALID`, `ORIGIN_INVALID` | AUTH-14 |
| 403 | `FORBIDDEN` | non-Admin on an Admin route |
| 409 | `ACTIVE_DEPARTMENT_REQUIRED` | an operation needs a department and none is set |
| 409 | `CONFLICT` | conversion or account collisions (no merge) |
| 429 | `RATE_LIMITED` | Demo creation above 5 per hour per IP |
| 429 | `QUOTA_EXCEEDED` | a per-user daily AI quota is used up (chat, M4) |
| 503 | `AI_UNAVAILABLE` | kill switch on or global daily quota reached (chat, M4) |
| 429, 503 | (any) | carry a `Retry-After` header in seconds when a retry time is known (`AppError(headers=...)`) |
| 501 | `NOT_IMPLEMENTED` | M1-01 stubs only; removed as each slice lands |

## Shared interfaces (`knowserve_core`)
`audit.record(session, event, user_id=, ip=, **details)` (redacts), `TokenVerifier` and `FakeTokenVerifier`, `RateLimiter` (PostgreSQL fixed-window counters, M1-02a), `QuotaService` (M1-10), `Clock`/`FakeClock`, `security` (token and CSRF helpers), `testing.mint_emulator_token`. Test fixtures in the root `conftest.py`: `make_user`, `make_session`, `make_token`, `clock`.

## Rules for dependents of a user
Later tables (conversations, messages, ...) reference `users.id` with `ON DELETE CASCADE` and store department as a column; they never store the Firebase uid or email. This makes conversion keep history and Demo cleanup delete it (ADR 0005).
