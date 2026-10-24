# Backend auth, sessions and identities

**Status:** Target spec (M1). Not implemented: the legacy code uses JWT, self-registered roles and no email verification (see "Current implementation").

## Purpose
This is the focused FastAPI auth module. It covers email/password signup with verification, opaque DB-backed sessions, CSRF, Try Demo visitors, the single private Admin, and active-department selection. Access-control rules are in `../cross-cutting/security-and-permissions.md`.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| AUTH-01 | Signup with email and password creates an **unverified** user. The email is normalized (trimmed, lower-case) and the password is hashed with **pwdlib Argon2id**. | M1 |
| AUTH-02 | Signing up with an email that already exists does not create a second account. The response and enumeration posture are OPEN-14. | M1 |
| AUTH-03 | Password policy: at least 8 characters, with a digit and an uppercase letter. This is carried over from the legacy spec and awaits confirmation (OPEN-15). | M1 |
| AUTH-04 | There is exactly one private **Admin** identity, provisioned out-of-band (seed/CLI/secret). No public API or UI path can create or elevate to Admin. | M1 |
| AUTH-06 | Login for a verified user with correct credentials creates a new **opaque random session token**. Only a **hash** of the token is stored in PostgreSQL. The token is set in a `Secure`, `HttpOnly`, appropriately scoped `SameSite` cookie. Any pre-existing session id is not reused, which rotates the session against fixation. | M1 |
| AUTH-07 | A wrong email or a wrong password returns the same `401` with the same generic message. | M1 |
| AUTH-08 | Logout revokes the server-side session (the row is invalidated) and clears the cookie. | M1 |
| AUTH-09 | A "current identity" endpoint returns the identity type (registered/visitor/admin), its display data and the active department for a valid session, and `401` otherwise. | M1 |
| AUTH-10 | Each request is validated by hashing the cookie token and looking up an unexpired, unrevoked session. Expired or revoked sessions get `401`. Sessions have an expiration (value OPEN-05). | M1 |
| AUTH-11 | Admin-only routes return `403` to registered users and visitors (SEC-03). | M1 |
| AUTH-13 | Email verification is mandatory before normal access, and the verification email is sent via **Resend**. Verification tokens cannot be forged and expire. An unverified account cannot access protected resources. | M1 |
| AUTH-14 | Cookie-authenticated state-changing requests require CSRF protection. The mechanism is OPEN-04. | M1 |
| AUTH-15 | Login attempts are bounded, with per-client and per-user rate limits on auth endpoints (values OPEN-05). | M1 |
| AUTH-16 | **Try Demo** creates a distinct, temporary anonymous visitor identity and session without signup. It is separate from registered accounts, isolated per visitor and department (SEC-16), and expires and is purged (lifetime OPEN-05). | M1 |
| AUTH-17 | The active department is stored server-side on the session and selected/switched among the seeded departments (PROD-04; restriction rules OPEN-12). A switch never carries over data or context from the previous department (SEC-10). | M1 |
| AUTH-18 | JWT is **not** used as the primary session scheme, and Starlette's signed-cookie `SessionMiddleware` is **not** used as the session store. | M1 |
| AUTH-19 | Cookie attributes and the CORS/origin policy match the actual Pages and Cloud Run domains (topology OPEN-04). Only the approved frontend origin may send credentialed requests. | M0 spike / M1 |
| AUTH-20 | A departments endpoint returns the seeded departments. There is no department or user CRUD in the MVP (PROD-03). | M1 |
| AUTH-21 | Auth and security events (signup, verify, login success/failure, logout, admin actions) are audit-logged without passwords, tokens or cookies (MON-04). | M1 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| AUTH-05 | One manager per department | The target has no manager/employee roles (PROD-02). |
| AUTH-12 | Public registration must not choose the admin role | Merged into AUTH-04. |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| AUTH-01 | integration | Valid signup | user row unverified, email normalized, hash is Argon2id and not the password |
| AUTH-02 | integration | Sign up twice with the same email (different case) | one account only |
| AUTH-03 | unit | Short password / no digit / no uppercase / valid | rejected ×3 / accepted |
| AUTH-04 | integration | Signup payload with `role: admin`; any attempt to elevate | ignored or rejected; no Admin created |
| AUTH-06 | integration | Login | cookie flags Secure+HttpOnly+SameSite; the DB stores a hash ≠ cookie value; a pre-login session id is not reused |
| AUTH-07 | integration | Unknown email vs wrong password | identical 401 bodies |
| AUTH-08 | integration | Logout, then reuse the old cookie | 401 |
| AUTH-09 | integration | With a user, visitor or admin session / with none | correct identity + department / 401 |
| AUTH-10 | integration | Expired session; tampered token | 401 |
| AUTH-11 | integration | Admin route as a registered user and as a visitor | 403 (with SEC-03) |
| AUTH-13 | integration | Login before verification; reused or expired/forged token | blocked; verification fails |
| AUTH-14 | integration | Mutation without or with a wrong CSRF token | rejected |
| AUTH-15 | integration | N+1 failed logins | throttled |
| AUTH-16 | integration | Two demo visitors; visitor after expiry; purge job | isolated; 401; data removed |
| AUTH-17 | integration | Switch department, then request the previous department's conversation | 404 |
| AUTH-18 | review/unit | Grep for JWT and SessionMiddleware usage in target code | none |
| AUTH-19 | e2e (deploy smoke) | Credentialed call from the Pages origin vs another origin | allowed / blocked |
| AUTH-20 | integration | GET departments | seeded list; there are no create/update/delete routes |
| AUTH-21 | integration | Login failure | audit log entry without the password or token |

## Current implementation (LEGACY, not migrated)
- `routers/auth.py`, `services/auth_service.py` and `utils/jwt.py` issue a **JWT** (python-jose) with `user_id`, `role` and `department_id`. It is read from the `token` cookie or `Authorization: Bearer`, and the cookie has `secure=False`.
- Passwords are hashed with passlib argon2 (`utils/hashing.py`), not pwdlib.
- `RegisterRequest.role` is client-controlled (`employee`/`manager`/`admin`), so anyone can register as Admin if none exists. This contradicts AUTH-04.
- Roles employee/manager/admin; a user has a single fixed `department_id`.
- There is no email verification, CSRF, rate limiting, Try Demo, department switch, departments endpoint or audit logging. `/auth/me` returns the raw JWT payload.

## Known gaps
Every AUTH requirement is unimplemented on the target stack. AUTH-07 (same 401 for both cases) is the only behavior already present in legacy code.

## Related docs
`architecture.md`, `../cross-cutting/security-and-permissions.md`, `../frontend/auth.md`, `../cross-cutting/product-and-ux.md`, `../open-decisions.md`
