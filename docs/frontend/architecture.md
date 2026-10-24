# Frontend architecture

**Status:** Target spec (M0 shell; features M1–M5). Not implemented: the legacy `frontend/` is React 19 + Vite in **plain JS/JSX** with npm, raw CSS and React Context for server data. Read this spec before any frontend change.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-ARCH-01 | All HTTP goes through one typed API client whose types are **generated from the approved OpenAPI contract** (STACK-38). Components never call `fetch` ad hoc; the SSE chat stream helper is part of the client. | M0 |
| FE-ARCH-02 | Requests include credentials (session cookie, AUTH-06) and send the CSRF token on mutations (AUTH-14). The API base URL is configured per environment (Vite locally, Pages → Cloud Run in prod). | M0/M1 |
| FE-ARCH-03 | API errors are normalized into one typed error shape. A 401 sends the user to the session-expired/login flow and clears identity-scoped caches. A 404 on a document shows a neutral "not found or not available" view (SEC-02). | M1/M2 |
| FE-ARCH-04 | Server data uses **TanStack Query**, with query keys that include the identity and the **active department**. All identity- and department-scoped queries are cleared on logout and on department switch (SEC-10). Local state uses `useState`/`useReducer`, with Context limited to session and active department. There is no Redux or Zustand. | M0/M1 |
| FE-ARCH-05 | TypeScript `strict`. Folder layout is decided in M0 (proposal: `src/{app,features,components,lib}`, OPEN-18). Pages and features are grouped by feature. | M0 |
| FE-ARCH-06 | Routing uses React Router (declarative). Route paths follow the product spec (PROD-05 to PROD-08); the viewer deep link is `/documents/:id?page=N`. Protected routes redirect to login without a session. | M0/M1 |
| FE-ARCH-07 | Admin UI is shown only to the Admin. This is UX only, and the backend is the authority (SEC-15). | M1 |
| FE-ARCH-08 | Styling uses Tailwind CSS + shadcn/ui with shared design tokens. There are no ad-hoc inline styles for layout. | M0 |
| FE-ARCH-09 | Forms use React Hook Form + Zod. Client validation mirrors the contract, and the server validates independently. | M1 |
| FE-ARCH-10 | Tooling is pnpm with `pnpm-lock.yaml`, ESLint, Prettier and `tsc --noEmit`, all blocking in CI (STACK-34, STACK-36). | M0 |
| FE-ARCH-11 | Tests use Vitest + React Testing Library for components and Playwright for e2e (TEST-06). | M0 |
| FE-ARCH-12 | The dashboard shows the active department, Ask AI, a library preview and recent chats. The sidebar has Dashboard / Chat / Documents (+ Admin for the Admin) (PROD-05). A Demo Mode indicator is always visible (PROD-01). | M1/M2 |
| FE-ARCH-13 | Departments always come from the API (AUTH-20). No department ids are hard-coded. | M1 |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-ARCH-01 | CI | `tsc` against regenerated OpenAPI types | compiles; no drift (M0-AC06) |
| FE-ARCH-02 | unit | Client mutation call | `credentials: 'include'` and CSRF header present |
| FE-ARCH-03 | unit | 401 / 422 with details / 404 / network error | redirect + cache clear / field errors / not-found view / retryable error |
| FE-ARCH-04 | component | Switch department | department-scoped queries removed and refetched with new keys |
| FE-ARCH-05/08 | CI | `tsc --noEmit` with `strict`; lint rule against inline layout styles | passes on main; violations fail |
| FE-ARCH-09 | component | Form submit with invalid fields; server 422 | Zod errors without a request; server errors mapped to fields |
| FE-ARCH-11 | CI | `pnpm test` and Playwright smoke jobs | run on PRs and block merge on failure |
| FE-ARCH-06 | component | Protected route without a session | redirect to login |
| FE-ARCH-07 | component | Registered user vs Admin | admin nav only for the Admin |
| FE-ARCH-10 | CI | Lint, format or type error | check fails (M0-AC07) |
| FE-ARCH-12 | component | Dashboard render | department, Ask AI, library preview, recent chats, Demo Mode |
| FE-ARCH-13 | CI | Grep for literal department-id arrays | none |

## Current implementation (LEGACY, not migrated)
- JS/JSX and npm. The Vite proxy forwards `/api` to `localhost:8000`.
- `src/services/api.js` is hand-written fetch with `console.log` of every response.
- Server data is held in `AuthContext`, `ChatContext` and `DocsContext`, with no partitioning or invalidation.
- Routes are `/login`, `/register`, `/chat`, `/my-docs` and `/admin/upload`. The admin route is not role-guarded.
- Departments 1–5 are hard-coded. Styling is raw CSS plus many inline styles.
- There are no tests and no TypeScript. `frontend/README.md` is the unmodified Vite template.

## Known gaps
Every FE-ARCH requirement is unimplemented. Migrating to TypeScript, pnpm, Tailwind and TanStack Query is M0/M1 work.

## Related docs
`auth.md`, `chat.md`, `my-documents.md`, `admin-upload.md`, `../architecture/tech-stack.md`, `../cross-cutting/product-and-ux.md`, `../cross-cutting/security-and-permissions.md`
