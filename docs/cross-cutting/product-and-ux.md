# Product and UX (cross-cutting)

**Status:** Target spec. The legacy UI (plain-JS pages `/chat`, `/my-docs`, `/admin/upload`) does not implement it.

## Purpose
What KnowServe is, who uses it, and which product-level rules every feature must respect. Detailed screen behavior lives in the `../frontend/` specs.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| PROD-01 | KnowServe is a portfolio demo of a **fictional** organization's departmental knowledge assistant. All documents and organizational data are fictional, and the UI clearly shows **Demo Mode**, never implying real corporate access. | M1 |
| PROD-02 | Identities: an anonymous **Try Demo** visitor (no signup, temporary, isolated, expires); a registered user (signup with email/password and mandatory email verification; login with **email + password or email + one-time code (Email OTP)**; persistent conversations); one private **Admin** identity (no public Admin signup; **password-only** login, OPEN-19). Email OTP is a password alternative for non-Admin accounts, not MFA (AUTH-26). | M1 |
| PROD-03 | Departments are seeded and relatively static. There is no user or department CRUD in the MVP. The UI loads departments from the API and never hard-codes department ids. | M1 |
| PROD-04 | Every registered user and Try Demo visitor may select and switch among **all** seeded fictional departments (OPEN-12). The UI states that this is Demo Mode and that department choice is self-selected for demonstration. Switching changes the dashboard context and never leaks history or document context from the previous department (SEC-10). | M1 |
| PROD-05 | The dashboard shows the active department, an Ask AI entry, the document library and recent chats. The sidebar has Dashboard, Chat and Documents; admin controls appear only for the Admin (UX only, SEC-15). In the regular library, viewer and chat the Admin sees only what the active department allows (SEC-17). | M1/M2 |
| PROD-06 | The document library lists only authorized ready/current documents, with filename search and a filter by owner department. The UI distinguishes ownership from access. | M2 |
| PROD-07 | A dedicated protected PDF Viewer has page navigation, zoom and deep links (`/documents/:id?page=N`). It is built with React-PDF and receives bytes only via the API, never a public storage URL. | M2 |
| PROD-08 | Chat has per-department session history, title search, rename and delete, a streaming answer, Stop, and citations linked to PDF pages. After access to a source document is revoked, saved answer text stays visible but its citations lose their link and content, and the document cannot be opened (SEC-09, OPEN-11). | M4 |
| PROD-09 | The Admin can upload a single PDF with metadata and allowed departments, or a ZIP plus `manifest.json` (preview, explicit confirmation, per-file results and retry), and can update permissions, replace the file of a failed document (M3), replace a ready document's version (M5) and delete. | M3/M5 |
| PROD-10 | The public demo stays usable when the AI budget is exhausted: permitted documents, the viewer and history still work. Optional pre-verified sample conversations are clearly labeled and respect active-department permissions (COST-05). | M4/M6 |
| PROD-11 | Out of MVP scope unless newly approved: organization management, user admin, Google OAuth, OCR, a user model chooser. | all |
| PROD-12 | Curating the fictional document corpus is **deferred** (DEF-01). It is not designed in this phase. | — |

Route paths other than the viewer deep link (`/documents/:id?page=N`) are fixed in the frontend route contract of M1/M2. They are not invented here.

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| PROD-01 | e2e | Visit as a visitor and as a registered user | Demo Mode indicator visible on all authenticated screens |
| PROD-02 | e2e | Try Demo without signup; sign up without verifying; attempt Admin signup; log in by password and by Email OTP | demo works; unverified access blocked (AUTH-13); no Admin path exists; both logins reach the dashboard |
| PROD-03 | component | Department selector with an API-mocked list | renders the API values; there are no literal ids in the source (lint/grep check) |
| PROD-04 | e2e | Visitor and registered user each switch through every department | all selectable; Demo Mode notice shown; library, chats and dashboard reload for the new department (SEC-10) |
| PROD-05 | e2e | Registered user vs Admin | admin controls are shown only to the Admin |
| PROD-06..09 | — | Covered by FE-DOC-*, FE-CHAT-*, FE-ADM-* and the backend specs | — |
| PROD-11/12 | review | Milestone PR scope check | no out-of-scope features (OAuth, OCR, model chooser, org/user admin); no corpus design work |
| PROD-10 | e2e | Kill switch on (COST-04) | chat input shows the disabled state; documents and history still load |

## Current implementation (LEGACY)
- Pages `/login`, `/register`, `/chat`, `/my-docs`, `/admin/upload` in plain JS (`frontend/src/pages/*.jsx`).
- Departments are hard-coded (ids 1–5) in `AdminUpload.jsx` and `Register.jsx`.
- There is no Demo Mode, Try Demo, email verification, dashboard, PDF viewer, chat history list or department switch. Self-registration with a `role` field exists.

## Related docs
`security-and-permissions.md`, `../frontend/architecture.md`, `../frontend/auth.md`, `../frontend/my-documents.md`, `../frontend/chat.md`, `../frontend/admin-upload.md`, `../open-decisions.md`
