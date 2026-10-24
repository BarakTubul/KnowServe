# M1 — Authentication & Demo (provisional scope and acceptance)

**Status:** Provisional and **not started**. Requirements-level planning only; the Owner adds the task graph, dependency analysis and agent allocation (WF-16) when M1 starts, after M0 is merged. Nothing here is implemented.

## Scope (normative text lives in the specs)
- Identities, signup with mandatory email verification, password policy: AUTH-01..04, AUTH-13, PROD-02.
- Sessions, cookies, CSRF + Origin check, same-site topology: AUTH-06..10, AUTH-14, AUTH-18, AUTH-19 (topology proven in M0, M0-AC11).
- **Email OTP login** (password alternative, not MFA): AUTH-22..28, FE-AUTH-10.
- Rate limiting and brute-force protection: AUTH-15, AUTH-25.
- Try Demo, departments, active department and switching (Demo Mode): AUTH-16, AUTH-17, AUTH-20, PROD-01, PROD-04, SEC-10, SEC-16.
- Admin identity and Admin-only 403: AUTH-04, AUTH-11, SEC-03, SEC-15, SEC-17 (user-facing rules apply to the Admin).
- Error envelope and status codes, including 409 `ACTIVE_DEPARTMENT_REQUIRED`: ARCH-05, FE-ARCH-03.
- Audit and logging hygiene: AUTH-21, AUTH-27, MON-04, MON-05.
- Frontend: FE-AUTH-01..10, FE-ARCH-02..04, FE-ARCH-12/13.

## Acceptance criteria (draft)
| ID | Acceptance criterion | Evidence | Covers |
|---|---|---|---|
| M1-AC01 | Signup → verify → password login → logout works end to end; signup with an existing email is indistinguishable from a new one | integration + Playwright e2e | AUTH-01, AUTH-02, AUTH-06..08, AUTH-13 |
| M1-AC02 | Password policy: 8-char minimum, no composition rules, blocklist rejection, Unicode/passphrases accepted | unit tests | AUTH-03, FE-AUTH-03 |
| M1-AC03 | Email OTP login creates the same session type as password login | integration + e2e (Resend faked) | AUTH-06, AUTH-22, AUTH-24, FE-AUTH-10 |
| M1-AC04 | OTP security: expiry, wrong code, replay, concurrent verification, 5-attempt cap, replacement invalidation, no plaintext storage | integration tests | AUTH-23, AUTH-24 |
| M1-AC05 | OTP rate limits and cooldown (per email, per IP, global email budget) and enumeration resistance (verified vs unknown vs unverified email) | integration tests | AUTH-22, AUTH-25 |
| M1-AC06 | No OTP codes, passwords, tokens or cookies in logs or audit records | log-capture tests | AUTH-21, AUTH-27, MON-05 |
| M1-AC07 | CSRF token + Origin check enforced on every cookie-authenticated mutation; CORS limited to the app origin | integration + deploy smoke | AUTH-14, AUTH-19 |
| M1-AC08 | Every user and visitor can select every department; switching isolates data; missing department returns 409 `ACTIVE_DEPARTMENT_REQUIRED` | integration + e2e | AUTH-17, PROD-04, SEC-10, FE-AUTH-09 |
| M1-AC09 | Security hard gates: 401 without session, 403 on Admin APIs for non-Admins, no public Admin creation, Admin has no bypass in user paths | integration tests | SEC-01, SEC-03, AUTH-04, SEC-17 |
| M1-AC10 | Error envelope with `request_id` on every error status used in M1 | integration + contract (OpenAPI) check | ARCH-05, FE-ARCH-03 |

## Open items affecting M1
- OPEN-05: session and demo lifetimes, purge cadence and rate-limit values (beyond the approved OTP initial parameters).
- OPEN-19: whether the Admin may log in with Email OTP (password-only until decided).

## Related docs
`../../backend/auth.md`, `../../frontend/auth.md`, `../../cross-cutting/security-and-permissions.md`, `../../cross-cutting/product-and-ux.md`, `../M0/plan.md`, `../../open-decisions.md`
