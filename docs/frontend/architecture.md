# Frontend architecture

## Purpose
Conventions for `frontend/` (React 19, Vite, plain JS, react-router 7). Read before any frontend change.

## Requirements
| ID | Requirement |
|---|---|
| FE-ARCH-01 | All HTTP goes through `src/services/api.js`; pages/components never call `fetch` directly (the WebSocket in `AdminUpload` is the one exception today). |
| FE-ARCH-02 | API calls use base `/api` (Vite proxy strips it and forwards to `localhost:8000`) and `credentials: 'include'` so the HttpOnly cookie is sent. |
| FE-ARCH-03 | API wrapper functions are named `<verb><Thing>Api`; `handleResponse` throws `Error(detail)` for non-2xx and fires `auth:unauthorized` on 401 (except where `ignoreAuth` is set). |
| FE-ARCH-04 | Shared state lives in React context providers in `src/context/`; page-local state stays in the page. |
| FE-ARCH-05 | Pages are `PascalCase.jsx` in `src/pages/` with a sibling `.css`; shared components in `src/components/`. |
| FE-ARCH-06 | Routes: `/login`, `/register` (public); `/chat` (default), `/my-docs`, `/admin/upload` inside `Layout`, which redirects to `/login` when there is no user. |
| FE-ARCH-07 | Admin-only UI is hidden for non-admins (`Navbar`) and the route itself is protected (see gap); the backend remains the real authority. |

## Files
`src/App.jsx`, `src/services/api.js`, `src/context/*.jsx`, `src/components/Layout.jsx`, `src/components/Navbar.jsx`, `vite.config.js`, `eslint.config.js`

## Required tests
No frontend test tool is installed. Recommended: Vitest + React Testing Library + MSW (mock `/api`). Scenarios to cover once chosen:
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-ARCH-02/03 | unit | `handleResponse` with 401, 422 array detail, 500 without JSON | event fired, joined messages, `HTTP Error: 500` |
| FE-ARCH-06 | component | Render `Layout` with no user after load | redirects to `/login` |
| FE-ARCH-07 | component | Navbar as employee vs admin | "Manage Docs" only for admin |
| FE-ARCH-07 | component | Employee navigates to `/admin/upload` | redirected or blocked (once implemented) |

## Known gaps
- No tests; only `npm run lint` exists.
- `/admin/upload` route is not role-guarded in `App.jsx`; an employee who types the URL sees the page (API calls still 403).
- Department list is hard-coded (ids 1-5) in `AdminUpload.jsx` and `Register.jsx`; there is no departments API.
- `api.js` logs every response and stream chunk with `console.log`.
- `Layout` redirect runs while `loading` is false only; unauthenticated flicker is possible.
- Inline styles are widespread in pages.

## Related docs
`auth.md`, `chat.md`, `my-documents.md`, `admin-upload.md`, `../backend/architecture.md`
