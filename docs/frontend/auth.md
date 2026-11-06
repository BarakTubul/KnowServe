# Frontend auth, demo and department selection

**Status:** Target spec (M1), revised 2026-11-06 for **Firebase Authentication** (OPEN-24). Not implemented: the legacy code has login/register pages, `AuthContext`, a JWT cookie and the user's name in localStorage.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-AUTH-01 | On app load, the current-identity endpoint (AUTH-09) hydrates the session state (identity type, display data, active department, CSRF token). Until it resolves, protected routes show a loading state, not a redirect flicker. | M1 |
| FE-AUTH-02 | **One login screen offers both methods**: email + password and **Continue with Google**, plus the Try Demo entry (FE-AUTH-08) and links to sign up and to password reset. Email is the only identifier (no usernames). Password sign-in uses the Firebase SDK (RHF+Zod), then calls the session exchange (AUTH-30) with the ID token; Firebase's generic invalid-credential error is shown as one generic message. On success it navigates to the dashboard. An unverified password account sees the "verify your email" state with a resend action. | M1 |
| FE-AUTH-03 | Signup (Firebase Email/Password) checks client-side only the minimum length of 8 and allows Unicode and long passphrases, with no composition rules; the final policy is Firebase's (AUTH-03). After signup it sends the verification email and shows the "check your email" state. If Firebase reports the email is already in use, it shows a neutral message that points to sign-in and password reset (AUTH-02 deviation). The user never chooses a role. | M1 |
| FE-AUTH-04 | Logout calls the API, signs out of Firebase, clears **all** query cache and local state, and returns to the public entry page. | M1 |
| FE-AUTH-05 | Any 401 from an authenticated call clears the identity-scoped state and redirects to login (FE-ARCH-03). | M1 |
| FE-AUTH-06 | No KnowServe token, session id, CSRF token or credential is stored in localStorage/sessionStorage. The Firebase SDK's own persistence is set to the least persistent option that works (in-memory, since the KnowServe session cookie is the source of truth), and the exchanged ID token is never kept. Per-viewer conveniences (such as UI preferences) only. | M1 |
| FE-AUTH-07 | A KnowServe **action page** (`/auth/action`) handles Firebase email-verification and password-reset links. For each it shows success, an expired code and an invalid code as three distinct states, and offers to resend (verification) or request a new reset. | M1 |
| FE-AUTH-08 | A **Try Demo** entry starts a KnowServe visitor session without signup and without Firebase (AUTH-16). The Demo Mode indicator is visible (PROD-01). | M1 |
| FE-AUTH-09 | A department selector lists **all** API departments for every user and visitor (AUTH-20, OPEN-12), with a Demo Mode note that department choice is self-selected. Switching calls the API, then resets the department-scoped cache, open chat and multi-turn context (SEC-10). A `409 ACTIVE_DEPARTMENT_REQUIRED` response opens the selector instead of showing a generic error. | M1 |
| FE-AUTH-11 | **Password reset**: a request form that always shows the same confirmation whether or not the email exists, and a new-password form on the action page (FE-AUTH-07). | M1 |
| FE-AUTH-12 | **Account linking**: when Google sign-in reports that the email already has a password account, the UI explains this and asks the user to sign in with their password first, then links Google to that account. It never links silently and never offers to link an unverified account. The Admin is not offered Google (the API refuses it regardless; AUTH-04). | M1 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| FE-AUTH-10 | Email OTP login | Email OTP removed from the MVP (OPEN-24). |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-AUTH-01 | component | Identity endpoint pending / 200 / 401 | loader / state set / public view, with no protected flash |
| FE-AUTH-02 | component | Login screen render; password success / invalid credential / unverified; Google success | both methods and Try Demo on one screen; dashboard / one generic error / verify notice with resend / dashboard |
| FE-AUTH-02 | e2e (emulator) | Password login and Google login | session created; Demo Mode visible; same identity shape for both |
| FE-AUTH-03 | component | 7-char password / 8 lower-case chars / Unicode passphrase / email already in use | inline error with no Firebase call / submitted / submitted / neutral message pointing to sign-in and reset |
| FE-AUTH-04 | component | Logout | query cache empty; Firebase signed out; redirect |
| FE-AUTH-05 | unit | 401 from a query | redirect + cache cleared |
| FE-AUTH-06 | component | After login | no credential, session or CSRF keys in web storage |
| FE-AUTH-07 | component | Verify and reset action pages: success / expired / invalid | the three distinct states for each |
| FE-AUTH-08 | e2e | Try Demo | visitor session; Demo Mode visible; no Firebase call; library loads |
| FE-AUTH-09 | component + e2e | Switch A→B; all departments listed; a 409 `ACTIVE_DEPARTMENT_REQUIRED` | B data shown, no A chats or docs visible; every API department selectable; selector opened |
| FE-AUTH-11 | component | Reset request for an existing vs unknown email | identical confirmation |
| FE-AUTH-12 | component | Google sign-in hits an existing password account; unverified account | prompt to sign in with the password first, then link; no link offered for unverified; no silent link |

## Current implementation (LEGACY, not migrated)
- `src/context/AuthContext.jsx` calls `/auth/me` (which returns the JWT payload) and stores `user_name` in localStorage.
- `src/pages/Login.jsx` and `src/pages/Register.jsx` exist. Register always sends `role: 'employee'` with a hard-coded department dropdown, and enforces an uppercase-and-digit rule that AUTH-03 drops.
- The `auth:unauthorized` event handler calls `logout()`, which can re-trigger the event (a possible loop).
- There is no email verification, Google sign-in, password reset, Try Demo, department switch or CSRF.

## Known gaps
Every FE-AUTH requirement is unimplemented on the target stack. Firebase SDK behavior (popup vs redirect on `pages.dev`, persistence options, link-flow error codes) is to be verified in M1-06 and the deployed smoke; redirect-based Google sign-in may be affected by browsers' third-party storage rules, so the popup flow is the default.

## Related docs
`architecture.md`, `../backend/auth.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/product-and-ux.md`
