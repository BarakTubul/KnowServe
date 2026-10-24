# Product, personas and user journeys

## Product intent
KnowServe is a portfolio demonstration of a fictional organization's departmental knowledge assistant. It lets users discover and read permissioned PDF documents and ask grounded, cited questions via RAG. All documents and organizational data are fictional. Clearly mark the environment **Demo Mode**, not real corporate access.

## Identity and department journeys
- A public user can sign up using email/password, verify email before normal access, log in/out, and select/switch among seeded departments. Switching department changes dashboard context and never leaks history/document context from a previous department.
- Anonymous **Try Demo** works without signup via distinct temporary visitor identity/session, isolated conversations by visitor and department, expiration and cleanup.
- Registered users have persistent conversations, isolated by user and active department.
- One private Admin identity, not public Admin registration. No user/department CRUD in MVP. Departments are seeded, relatively static data; UI must not hardcode department IDs.

## UI and routes
- Dashboard: active department, Ask AI, document library and recent chats. Sidebar: Dashboard, Chat, Documents; admin controls only for Admin.
- Document library: list only authorized **ready/current** documents; filename search and filter by owner department. Distinguish document *ownership* from document *access*.
- Dedicated protected PDF Viewer: page navigation, zoom and deep links like `/documents/:id?page=3`. React-PDF UI; never direct public R2 URL. API checks access per request.
- Chat: session history/list by department, search by title, rename/delete, streaming answer, stop generation, citations linked to PDF pages. Persisted chat and rendered history must not expose subsequently revoked documents.
- Admin: single PDF + metadata and allowed departments; ZIP + `manifest.json`; preview, explicit confirmation and per-file results/retry; update permissions, replace version, delete.

## Product constraints
- Avoid building organization management, user admin, Google OAuth or OCR in the MVP absent new approval.
- Public demonstration must remain functional when AI budget is exhausted: permitted docs/viewer/history still available, optional clearly labeled pre-verified sample conversations that also respect active department permissions.
- Distinguish authorization enforced by Backend from frontend route hiding; frontend controls are UX only.
