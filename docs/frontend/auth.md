# Frontend auth, demo and department selection

**Status:** Target spec (M1), revised 2026-11-06 for **Firebase Authentication** (OPEN-24) and the Demo, session and department decisions of OPEN-25. Not implemented: the legacy code has login/register pages, `AuthContext`, a JWT cookie and the user's name in localStorage.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-AUTH-01 | On app load, the current-identity endpoint (AUTH-09) hydrates the session state (identity kind, display data, active department, expiry, CSRF token). Until it resolves, protected routes show a loading state, not a redirect flicker. | M1 |
| FE-AUTH-02 | **One login screen offers**: email + password, **Continue with Google**, **Forgot password**, **Sign up** and **Try Demo**. Email is the only identifier (no usernames). Password and Google sign-in use the Firebase SDK, then call the session exchange (AUTH-30) with the ID token; Firebase's generic invalid-credential error is shown as one generic message. On success it navigates to the dashboard. An unverified password account sees the "verify your email" state with a resend action. When a session ends after its 24 hours the user is taken to this screen. On `401 REAUTH_REQUIRED` it shows an explicit "confirm it is you" step (password, or the Google popup) and retries once; it never retries silently. There is no Email OTP option. | M1 |
| FE-AUTH-03 | Signup (Firebase Email/Password) checks client-side only the minimum length of 8 and allows Unicode and long passphrases, with no composition rules; the final policy is Firebase's (AUTH-03). After signup it sends the verification email and shows the "check your email" state. If Firebase reports the email is already in use, it shows a neutral message that points to sign-in and password reset (AUTH-02 deviation). The user never chooses a role. | M1 |
| FE-AUTH-04 | Logout calls the API, signs out of Firebase, clears **all** query cache and local state, and returns to the public entry page. | M1 |
| FE-AUTH-05 | Any 401 from an authenticated call clears the identity-scoped state and redirects to login (FE-ARCH-03). A 429 `QUOTA_EXCEEDED` or `RATE_LIMITED` shows a clear message with the retry time and does not log the user out; a 503 `AI_UNAVAILABLE` shows the degraded-chat message while the library stays usable. | M1 |
| FE-AUTH-06 | No KnowServe token, session id, CSRF token or credential is stored in localStorage/sessionStorage. **Exception:** the Firebase SDK keeps its own auth state with **session (tab-scoped) persistence**, which survives a page reload and is needed so a Demo user can still link a credential after a reload (AUTH-34). The ID token is never copied into KnowServe state. Per-viewer conveniences (such as UI preferences) only. | M1 |
| FE-AUTH-07 | A KnowServe **action page** (`/auth/action`) handles Firebase email-verification and password-reset links. For each it shows success, an expired code and an invalid code as three distinct states, and offers to resend (verification) or request a new reset. After a successful verification it shows "email verified" and **does not start a session**: if the Firebase user is still signed in in this tab it asks them to confirm their credential when their sign-in is older than 5 minutes (FE-AUTH-02), otherwise it sends them to the login screen. This works in a different tab or browser from the one used to sign up. | M1 |
| FE-AUTH-08 | **Try Demo** signs in with Firebase Anonymous Authentication and calls `POST /v1/demo/start`; no registration is required. The Demo Mode indicator and the remaining session time are visible (PROD-01). If the Demo identity has expired (`DEMO_EXPIRED`) the client signs out of Firebase and starts a new Demo. | M1 |
| FE-AUTH-09 | A department selector lists **all** API departments for every user (AUTH-20, OPEN-12), with a Demo Mode note that department choice is self-selected. After login the last active department is restored; on first login (none stored) the selector is shown and required before department-scoped screens. Switching calls the API, then resets the department-scoped cache, open chat and multi-turn context (SEC-10). A `409 ACTIVE_DEPARTMENT_REQUIRED` response opens the selector instead of showing a generic error. Choosing a department is presented as a view choice, never as extra access. | M1 |
| FE-AUTH-11 | **Password reset**: a request form that always shows the same confirmation whether or not the email exists, and a new-password form on the action page (FE-AUTH-07). | M1 |
| FE-AUTH-12 | **Account linking**: when Google sign-in reports that the email already has a password account, the UI explains this and asks the user to sign in with their password first, then links Google to that account. It never links silently and never offers to link an unverified account. The Admin sees the same sign-in options and the same linking flow as any user; Admin rights come only from the server (AUTH-04). | M1 |
| FE-AUTH-13 | **Create account from Demo**: a Demo user can register without losing history, by email + password or Google, using Firebase's anonymous-account linking (AUTH-34). The UI says the history is kept; for a password signup it shows the "verify your email" pending state (the user stays in Demo until verified, then the app calls `POST /v1/auth/convert`) and for Google it converts at once. If the email or Google account already exists, the UI says so, explains that the Demo history will **not** be moved into that account, and offers to sign in instead. On success it shows the Registered state with the same chats and departments. | M1 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| FE-AUTH-10 | Email OTP login | Email OTP removed from the MVP (OPEN-24). |

## Required tests
Component and unit tests run with a mocked API and Firebase SDK; e2e flows run in Playwright against the Firebase Authentication Emulator; real Firebase appears only in the pre-release smoke.

| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-AUTH-01 | component | Identity endpoint pending / 200 / 401 | loader / state set / public view, with no protected flash |
| FE-AUTH-02 | component | Login screen render; password success / invalid credential / unverified; Google success; expired session | the five entries on one screen and no OTP; dashboard / one generic error / verify notice with resend; dashboard; back to login |
| FE-AUTH-02 | e2e (emulator) | Password login and Google login; `401 REAUTH_REQUIRED` from a stale token | session created; Demo Mode visible; same identity shape for both; confirm step, then a session |
| FE-AUTH-03 | component | 7-char password / 8 lower-case chars / Unicode passphrase / email already in use | inline error with no Firebase call / submitted / submitted / neutral message pointing to sign-in and reset |
| FE-AUTH-04 | component | Logout | query cache empty; Firebase signed out; redirect |
| FE-AUTH-05 | unit | 401 from a query; 429 `QUOTA_EXCEEDED`; 503 `AI_UNAVAILABLE` | redirect + cache cleared; message with retry time, still signed in; degraded message |
| FE-AUTH-06 | component | After login | no KnowServe credential, session or CSRF keys in web storage; Firebase uses session persistence |
| FE-AUTH-07 | component + e2e (emulator) | Verify and reset action pages: success / expired / invalid; verify more than 5 minutes after sign-up, in the same tab and in a fresh browser | the three distinct states for each; "email verified" with no session, then reauthentication or login, then the dashboard |
| FE-AUTH-08 | e2e (emulator) | Try Demo; reload; expired Demo | visitor session; Demo Mode and time left visible; library loads; still Demo after reload; a new Demo starts |
| FE-AUTH-09 | component + e2e | First login; later login; switch A→B; all departments listed; a 409 `ACTIVE_DEPARTMENT_REQUIRED` | selector required; last department restored; B data shown, no A chats or docs visible; every API department selectable; selector opened |
| FE-AUTH-11 | component | Reset request for an existing vs unknown email | identical confirmation |
| FE-AUTH-12 | component | Google sign-in hits an existing password account; unverified account | prompt to sign in with the password first, then link; no link offered for unverified; no silent link |
| FE-AUTH-13 | e2e (emulator) + component | Demo with representative records (fixtures; real chats are covered in M4) → create account by password (verify, then convert) and by Google; email already registered; Google already linked elsewhere; reload before verifying | records and departments kept in the Registered account; neutral explanation, no merge, sign-in offered; pending state survives the reload |

## Current implementation (LEGACY, not migrated)
- `src/context/AuthContext.jsx` calls `/auth/me` (which returns the JWT payload) and stores `user_name` in localStorage.
- `src/pages/Login.jsx` and `src/pages/Register.jsx` exist. Register always sends `role: 'employee'` with a hard-coded department dropdown, and enforces an uppercase-and-digit rule that AUTH-03 drops.
- The `auth:unauthorized` event handler calls `logout()`, which can re-trigger the event (a possible loop).
- There is no email verification, Google sign-in, password reset, Try Demo, department switch or CSRF.

## Known gaps
Every FE-AUTH requirement is unimplemented on the target stack. Firebase SDK behavior (popup vs redirect on `pages.dev`, session persistence, anonymous linking error codes, the state of the user object after linking) is to be verified in M1-06 and the pre-release smoke. Redirect-based Google sign-in may be affected by browsers' third-party storage rules, so the popup flow is the default.

## Related docs
`architecture.md`, `../backend/auth.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/product-and-ux.md`
