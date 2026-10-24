# KnowServe

Organizational knowledge assistant. Employees chat with a RAG agent over company PDFs; access is restricted by department. Admins ingest documents (Google Drive links) and control which departments can see them.

- **Backend:** `backend/` — FastAPI, SQLAlchemy/Postgres, Redis (cache + pub/sub), Celery, ChromaDB, LlamaIndex (gpt-4o-mini agent).
- **Frontend:** `frontend/` — React 19 + Vite, plain JS, react-router 7. Dev server proxies `/api` to `localhost:8000`.

## Commands
- Backend (from `backend/`, needs `.env`, Postgres, Redis): `uvicorn app.main:app --reload`; worker: `celery -A app.core.celery_app.celery_app worker`
- Backend tests: `cd backend && pytest` (no tests exist right now; see each spec's "Required tests")
- Frontend (from `frontend/`): `npm run dev`, `npm run build`, `npm run lint` (no test tool yet)

## Workflow (follow for every feature or fix)
1. Find the task in the **Doc index** below and read only the docs listed for it. Don't read the others.
2. Read the code the specs point to, then write a plan: what changes, which requirement IDs it satisfies, which tests will cover them.
3. **Stop and wait for the user's approval** before editing code.
4. Implement, with the tests listed in the spec's "Required tests" table. Reference requirement IDs in test names (e.g. `test_adm_03_...`).
5. If behavior changes, update the spec in the same change (requirements, tests table, "Known gaps").

Specs state intended behavior; a "Known gaps" section lists where the code currently differs. Don't assume code is correct just because a spec describes it.

## Doc index
Read `docs/README.md` only when adding or editing a spec.

| Task area | Read |
|---|---|
| Any backend change | `docs/backend/architecture.md` |
| Any frontend change | `docs/frontend/architecture.md` |
| Login, register, roles, JWT, route guards | `docs/backend/auth.md`, `docs/frontend/auth.md` |
| Chat, agent, tools, streaming | `docs/backend/chat.md`, `docs/frontend/chat.md` |
| Listing/downloading documents as a user, department access | `docs/backend/documents.md`, `docs/frontend/my-documents.md` |
| Admin: add/delete document, change access | `docs/backend/admin-docs.md`, `docs/frontend/admin-upload.md` |
| Document submission / upload end to end | `docs/cross-cutting/document-lifecycle.md` (then `docs/backend/admin-docs.md`, `docs/backend/ingestion.md`, `docs/frontend/admin-upload.md`) |
| Celery, Redis events, status updates, WebSocket | `docs/backend/ingestion.md` |
| Monitoring | `docs/backend/monitoring.md` |
