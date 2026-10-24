# Frontend auth, demo and department selection

**Status:** Target spec (M1). Not implemented: the legacy code has login/register pages, `AuthContext`, a JWT cookie and the user's name in localStorage.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-AUTH-01 | On app load, the current-identity endpoint (AUTH-09) hydrates the session state (identity type, display data, active department). Until it resolves, protected routes show a loading state, not a redirect flicker. | M1 |
| FE-AUTH-02 | Login (RHF+Zod) shows the server's generic error on failure. On success it navigates to the dashboard. An unverified account sees the "verify your email" state. | M1 |
| FE-AUTH-03 | Signup validates the password client-side with the same policy as the server (AUTH-03) and then shows the "check your email" state. The user never chooses a role. | M1 |
| FE-AUTH-04 | Logout calls the API, clears **all** query cache and local state, and returns to the public entry page. | M1 |
| FE-AUTH-05 | Any 401 from an authenticated call clears the identity-scoped state and redirects to login (FE-ARCH-03). | M1 |
| FE-AUTH-06 | No token, session id or credential is stored in localStorage/sessionStorage. Per-viewer conveniences (such as UI preferences) only. | M1 |
| FE-AUTH-07 | The email verification page handles success, an expired token and an invalid token, and offers to resend. | M1 |
| FE-AUTH-08 | A **Try Demo** entry starts a visitor session without signup. The Demo Mode indicator is visible (PROD-01). | M1 |
| FE-AUTH-09 | A department selector lists the API departments (AUTH-20). Switching calls the API, then resets the department-scoped cache, open chat and multi-turn context (SEC-10). | M1 |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-AUTH-01 | component | Identity endpoint pending / 200 / 401 | loader / state set / public view, with no protected flash |
| FE-AUTH-02 | component | Login success / 401 / unverified | dashboard / generic error / verify notice |
| FE-AUTH-03 | component | Weak password / valid / server error | inline error with no API call / check-email state / error banner |
| FE-AUTH-04 | component | Logout | query cache empty; redirect |
| FE-AUTH-05 | unit | 401 from a query | redirect + cache cleared |
| FE-AUTH-06 | component | After login | no credential keys in web storage |
| FE-AUTH-07 | component | Success / expired / invalid token responses | the three distinct states |
| FE-AUTH-08 | e2e | Try Demo | visitor session; Demo Mode visible; library loads |
| FE-AUTH-09 | component + e2e | Switch A→B | B data shown; no A chats or docs visible |

### Retired IDs (do not reuse)
None. All FE-AUTH-01..06 are kept with updated meaning.

## Current implementation (LEGACY, not migrated)
- `src/context/AuthContext.jsx` calls `/auth/me` (which returns the JWT payload) and stores `user_name` in localStorage.
- `src/pages/Login.jsx` and `src/pages/Register.jsx` exist. Register always sends `role: 'employee'` with a hard-coded department dropdown.
- The `auth:unauthorized` event handler calls `logout()`, which can re-trigger the event (a possible loop).
- There is no email verification, Try Demo, department switch or CSRF.

## Known gaps
Every FE-AUTH requirement is unimplemented on the target stack.

## Related docs
`architecture.md`, `../backend/auth.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/product-and-ux.md`
