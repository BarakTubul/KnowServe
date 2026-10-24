# Frontend auth

## Purpose
Login and registration pages plus `AuthContext`, which holds the current user and rehydrates it from the cookie on page load.

## Requirements
| ID | Requirement |
|---|---|
| FE-AUTH-01 | On app load `AuthContext` calls `GET /auth/me`; on success `user` is set (name from `localStorage.user_name`), on failure `user` stays null; `loading` ends false either way. |
| FE-AUTH-02 | Login submits email+password; on success it stores only the user's name in localStorage, sets `user`, and navigates to `/chat`. Failure shows the server message in an error banner. |
| FE-AUTH-03 | Register validates the password client-side (>= 8 chars, uppercase, digit) with the same rule as the backend, then calls register with role `employee` and the chosen department, and navigates to `/login`. Server errors show in a banner. |
| FE-AUTH-04 | Logout calls the API (ignoring failure), clears localStorage and `user`, and the Navbar sends the user to `/login`. |
| FE-AUTH-05 | Any 401 from a non-auth call logs the user out and redirects to `/login`. |
| FE-AUTH-06 | No token or credential is stored in localStorage/sessionStorage; only the display name. |

## Files
`src/context/AuthContext.jsx`, `src/pages/Login.jsx`, `src/pages/Register.jsx`, `src/pages/Auth.css`, `src/components/Navbar.jsx`, `src/services/api.js` (`loginApi`, `registerApi`, `logoutApi`, `fetchMeApi`)

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-AUTH-01 | component | `/auth/me` returns user / 401 | user set with stored name / null, `loading=false` |
| FE-AUTH-02 | component | Login success / 401 | navigates to `/chat`, localStorage has only `user_name` / banner shows message |
| FE-AUTH-03 | component | Weak password; valid password; server 400 | banner without API call; API called with `role: 'employee'` then redirect; banner with detail |
| FE-AUTH-04 | component | Click logout with API failing | user cleared, redirected to `/login` |
| FE-AUTH-05 | unit | Dispatch `auth:unauthorized` | logout invoked and location set to `/login` |
| FE-AUTH-06 | component | After login inspect storage | no token keys |

## Known gaps
- `/auth/me` returns the JWT payload (`user_id`, `role`, `department_id`), not name/email, so after refresh the name comes from localStorage and may be null on a new device.
- The unauthorized handler calls `logout()`, which itself calls the API, which on 401 dispatches the event again (possible loop; `logout` ignores failures but `handleResponse` fires the event for 401 on `logoutApi`).
- Register always sends role `employee`; the department dropdown is hard-coded.

## Related docs
`architecture.md`, `../backend/auth.md`
