# Backend auth, sessions and identities

**Status:** Target spec (M1). Not implemented: the legacy code uses JWT, self-registered roles and no email verification (see "Current implementation").

## Purpose
This is the focused FastAPI auth module. It covers email/password signup with verification, two login methods (password and Email OTP), opaque DB-backed sessions, CSRF, Try Demo visitors, the single private Admin, and active-department selection. Access-control rules are in `../cross-cutting/security-and-permissions.md`. Approved decisions: OPEN-04, OPEN-12, OPEN-14, OPEN-15 and the Email OTP decision (`../open-decisions.md`).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| AUTH-01 | Signup with email and password creates an **unverified** user. The email is normalized (trimmed, lower-case) and the password is hashed with **pwdlib Argon2id**. | M1 |
| AUTH-02 | Signing up with an email that already exists does not create a second account and returns the **same generic response** as a new signup, so the API never reveals whether an email is registered (OPEN-14). | M1 |
| AUTH-03 | Password policy (demo, OPEN-15): minimum **8 characters**; **no** mandatory uppercase, digit or special-character rules; common, weak, predictable or known-compromised passwords are rejected; long passphrases and Unicode are accepted. The 8-character minimum is a deliberate demo choice and must **not** be described as meeting the stricter NIST single-factor password length recommendation. The blocklist/breach-check mechanism is chosen in an M1 ADR and never sends the plaintext password to a third party. | M1 |
| AUTH-04 | There is exactly one private **Admin** identity, provisioned out-of-band (seed/CLI/secret). No public API or UI path can create or elevate to Admin. | M1 |
| AUTH-06 | A successful login (password, AUTH-07, or Email OTP, AUTH-24) for a verified user creates a new **opaque random session token**. Only a **hash** of the token is stored in PostgreSQL. The token is set in a `Secure`, `HttpOnly`, `SameSite=Lax`, **host-only** cookie on the API host (OPEN-04). Any pre-existing session id is not reused, which rotates the session against fixation. | M1 |
| AUTH-07 | A wrong email or a wrong password returns the same `401` with the same generic message. | M1 |
| AUTH-08 | Logout revokes the server-side session (the row is invalidated) and clears the cookie. | M1 |
| AUTH-09 | A "current identity" endpoint returns the identity type (registered/visitor/admin), its display data and the active department for a valid session, and `401` otherwise. | M1 |
| AUTH-10 | Each request is validated by hashing the cookie token and looking up an unexpired, unrevoked session. Expired or revoked sessions get `401`. Sessions have an expiration (value OPEN-05). | M1 |
| AUTH-11 | Admin-only routes return `403` to registered users and visitors (SEC-03). | M1 |
| AUTH-13 | Email verification is mandatory before normal access, and the verification email is sent via **Resend**. Verification tokens cannot be forged and expire. An unverified account cannot access protected resources. | M1 |
| AUTH-14 | Every cookie-authenticated state-changing request requires **both** a valid CSRF token bound to the session **and** an `Origin` matching an allowed frontend origin; otherwise it is rejected (OPEN-04). CORS is not treated as a CSRF defense. How the frontend obtains the token is fixed in the M1 API contract. | M1 |
| AUTH-15 | Brute-force protection: login, signup, verification and OTP endpoints have per-account/email and per-IP rate limits (values OPEN-05). | M1 |
| AUTH-16 | **Try Demo** creates a distinct, temporary anonymous visitor identity and session without signup. It is separate from registered accounts, isolated per visitor and department (SEC-16), and expires and is purged (lifetime OPEN-05). | M1 |
| AUTH-17 | The active department is stored server-side on the session. Every registered user and Try Demo visitor (and the Admin) may select and switch among **all** seeded departments (OPEN-12, Demo Mode). An operation that needs an active department when none is set returns **409 `ACTIVE_DEPARTMENT_REQUIRED`** (OPEN-14). A switch never carries over data or context from the previous department (SEC-10). | M1 |
| AUTH-18 | JWT is **not** used as the primary session scheme, and Starlette's signed-cookie `SessionMiddleware` is **not** used as the session store. | M1 |
| AUTH-19 | Same-site topology (OPEN-04): frontend and API are served from subdomains of one registrable domain (e.g. `app.<domain>`, `api.<domain>`). CORS allows credentialed requests only from explicitly listed frontend origins. The default Pages and Cloud Run domains are **not** assumed same-site. The domain and its cost are validated in M0 (INFRA-11); if infeasible, the blocker and alternatives go to the user, and insecure cross-site cookies (`SameSite=None` as a workaround) are not adopted silently. | M0 spike / M1 |
| AUTH-20 | A departments endpoint returns the seeded departments. There is no department or user CRUD in the MVP (PROD-03). | M1 |
| AUTH-21 | Auth and security events (signup, verify, login success/failure by method, OTP request/verify outcome, logout, admin actions) are audit-logged without passwords, OTP codes, tokens or cookies (MON-04, MON-05). | M1 |
| AUTH-22 | **Email OTP request**: a user enters an email to receive a one-time code. A code is issued and sent via **Resend** only for an existing, **email-verified, non-Admin** account. The **Admin is password-only** (OPEN-19): the backend refuses to issue a code for the Admin email. For unknown, unverified and Admin emails the response is **identical** to the eligible case (status, body, and no observable timing difference beyond normal variance) and no email is sent, so the response never reveals whether an email belongs to the Admin, an unverified account or no account. | M1 |
| AUTH-23 | **OTP code**: a cryptographically secure random **6-digit** code, valid for **5 minutes**. Only a secure verification representation (e.g. a keyed hash) is stored, never the plaintext. Issuing a replacement code invalidates the previous one. | M1 |
| AUTH-24 | **OTP verification**: a code is single-use and is consumed **atomically**, so replay and concurrent double use are impossible. At most **5** verification attempts per challenge; after that the challenge is dead. Expired, wrong, consumed or exhausted codes all return the same generic failure. A session (AUTH-06) is created **only** after successful verification. Verification for the Admin account always fails with the same generic failure and never creates a session, even if a challenge were somehow present (OPEN-19); this check is enforced server-side regardless of any frontend behavior. | M1 |
| AUTH-25 | **OTP rate limits**: a resend cooldown of initially **60 seconds**, plus limits per account/email, per IP and a **global email-sending budget**, protecting against enumeration and email flooding (values beyond the ones above: OPEN-05). | M1 |
| AUTH-26 | Email OTP is a **password-alternative login**, **not** MFA and not phishing-resistant. The UI and docs never describe it otherwise. Registration stays email + password with mandatory verification (AUTH-01, AUTH-13). | M1 |
| AUTH-27 | OTP codes never appear in application logs, audit records, error messages or analytics (MON-05). | M1 |
| AUTH-28 | The OTP numbers in AUTH-23 to AUTH-25 (6 digits, 5 min, 5 attempts, 60 s cooldown) are **initial, configurable security parameters**, validated later; changing them is a config change, not a contract change. | M1 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| AUTH-05 | One manager per department | The target has no manager/employee roles (PROD-02). |
| AUTH-12 | Public registration must not choose the admin role | Merged into AUTH-04. |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| AUTH-01 | integration | Valid signup | user row unverified, email normalized, hash is Argon2id and not the password |
| AUTH-02 | integration | Sign up twice with the same email (different case); compare with a fresh signup | one account only; identical status and body for both |
| AUTH-03 | unit | 7 chars / 8 lower-case chars not on the blocklist / common password (e.g. `password1`) / long Unicode passphrase | rejected / accepted / rejected / accepted |
| AUTH-04 | integration | Signup payload with `role: admin`; any attempt to elevate | ignored or rejected; no Admin created |
| AUTH-06 | integration | Login by password and by OTP | same session type; cookie `Secure`+`HttpOnly`+`SameSite=Lax`, no `Domain` attribute; the DB stores a hash ≠ cookie value; a pre-login session id is not reused |
| AUTH-07 | integration | Unknown email vs wrong password | identical 401 bodies |
| AUTH-08 | integration | Logout, then reuse the old cookie | 401 |
| AUTH-09 | integration | With a user, visitor or admin session / with none | correct identity + department / 401 |
| AUTH-10 | integration | Expired session; tampered token | 401 |
| AUTH-11 | integration | Admin route as a registered user and as a visitor | 403 (with SEC-03) |
| AUTH-13 | integration | Login before verification; reused or expired/forged token | blocked; verification fails |
| AUTH-14 | integration | Mutation with no CSRF token / wrong token / another session's token / valid token but foreign or missing `Origin` / valid token + allowed origin | rejected ×4 / accepted |
| AUTH-15 | integration | N+1 failed logins for one account; from one IP across accounts | throttled in both cases |
| AUTH-16 | integration | Two demo visitors; visitor after expiry; purge job | isolated; 401; data removed |
| AUTH-17 | integration | Visitor selects each seeded department; switch, then request the previous department's conversation; department-scoped call with none selected | all allowed; 404; 409 `ACTIVE_DEPARTMENT_REQUIRED` |
| AUTH-18 | review/unit | Grep for JWT and SessionMiddleware usage in target code | none |
| AUTH-19 | e2e (deploy smoke) | Credentialed call from the `app.` origin vs another origin | allowed / blocked (CORS and Origin check) |
| AUTH-20 | integration | GET departments | seeded list; there are no create/update/delete routes |
| AUTH-21 | integration | Login failure; OTP verify failure | audit entries without the password, code or token |
| AUTH-22 | integration | OTP request for verified / unknown / unverified email | identical responses; email (faked Resend) sent only for the verified account |
| AUTH-22 | integration | OTP request for the Admin email, compared with verified non-Admin / unknown / unverified emails | no code issued and no email sent for the Admin; status and body identical across all four |
| AUTH-24 | integration | Verify call for the Admin email (with a guessed code, and with a challenge row inserted directly in the test DB) | generic failure in both cases; no session created; audit entry without the code |
| AUTH-24 | integration | Admin password login after OTP attempts | password login still works (password-only path unaffected); same session type |
| AUTH-23 | unit + integration | Issue a code; inspect the DB; issue a replacement; use the first code | 6 digits; no plaintext stored; first code rejected |
| AUTH-23 | integration | Verify after 5 minutes (clock faked) | generic failure; no session |
| AUTH-24 | integration | Correct code twice (replay) | first creates a session; second fails |
| AUTH-24 | integration | Two concurrent verifications with the correct code | exactly one session created |
| AUTH-24 | integration | 5 wrong codes, then the correct code | all fail; challenge dead; no session |
| AUTH-25 | integration | Resend within 60 s; exceed per-email, per-IP and global budgets | refused with a generic response; no extra emails sent |
| AUTH-26 | review | Login UI copy and docs | OTP never labeled as MFA or "more secure" |
| AUTH-27 | unit + integration | Logging filter and captured logs during an OTP flow | no code value present |
| AUTH-28 | unit | Override OTP parameters via config | new values applied without code changes |

## Current implementation (LEGACY, not migrated)
- `routers/auth.py`, `services/auth_service.py` and `utils/jwt.py` issue a **JWT** (python-jose) with `user_id`, `role` and `department_id`. It is read from the `token` cookie or `Authorization: Bearer`, and the cookie has `secure=False`.
- Passwords are hashed with passlib argon2 (`utils/hashing.py`), not pwdlib.
- `RegisterRequest.role` is client-controlled (`employee`/`manager`/`admin`), so anyone can register as Admin if none exists. This contradicts AUTH-04.
- Roles employee/manager/admin; a user has a single fixed `department_id`.
- There is no email verification, Email OTP, CSRF, rate limiting, Try Demo, department switch, departments endpoint or audit logging. `/auth/me` returns the raw JWT payload.
- The legacy signup schema requires an uppercase letter and a digit; AUTH-03 drops those composition rules.

## Known gaps
Every AUTH requirement is unimplemented on the target stack. AUTH-07 (same 401 for both cases) is the only behavior already present in legacy code.

## Related docs
`architecture.md`, `../cross-cutting/security-and-permissions.md`, `../frontend/auth.md`, `../cross-cutting/product-and-ux.md`, `../open-decisions.md`
