# Legacy conflicts and resolutions (reconciliation 2026-10-24)

The first section is the discrepancy matrix between the previous repo docs and the approved source package. The second lists current-code gaps. The third recommends an implementation order. Code was **not** changed.

## 1. Discrepancy matrix (previous doc claim → required claim → impacted paths)
| # | Previous doc claim | Required (source) | Resolution in docs | Impacted paths (docs; code) |
|---|---|---|---|---|
| 1 | AGENTS.md: "Stop and wait for the user's approval before editing code" for every task | Owner-led parallel work; approval at milestone PR and for material scope/contract changes only (07) | Rule removed; workflow summary + WF-04..06, WF-13 | `AGENTS.md`, `CLAUDE.md`, `docs/workflow/agent-workflow.md` |
| 2 | Auth via JWT in a cookie or Bearer header (AUTH-06, AUTH-10) | Opaque random token, hash in PG, Secure/HttpOnly/SameSite cookie, rotation, CSRF; no JWT (02) | AUTH-06/10 reworded; AUTH-14, AUTH-18 added | `docs/backend/auth.md`; `backend/app/utils/{auth,jwt}.py`, `services/auth_service.py` |
| 3 | Roles employee/manager/admin; one manager per department (AUTH-05) | Registered user, Try Demo visitor, single private Admin; no user CRUD (01) | AUTH-05 retired; AUTH-04 rewritten; AUTH-16 added | `docs/backend/auth.md`; `models/user.py`, `pydantic_schemas/auth_schema.py` |
| 4 | User has a fixed `department_id` from the JWT | Active department selected and switched in the session; isolation on switch (01, 02) | AUTH-17, SEC-10, FE-AUTH-09; all departments selectable (OPEN-12, resolved) | `docs/backend/auth.md`, `docs/frontend/auth.md`; `utils/auth.py`, `context/AuthContext.jsx` |
| 5 | Admins see all docs in the user library (DOC-02) | Not stated; admin-only APIs return 403 to others (02) | DOC-02 retired; no Admin bypass in user paths, SEC-17 (OPEN-13, resolved) | `docs/backend/documents.md` |
| 6 | Forbidden download returns 403 (DOC-05) | Forbidden or unknown document returns an indistinguishable 404 (02) | DOC-05, SEC-02 | `docs/backend/documents.md`; `routers/docs.py`, `services/docs_service.py` |
| 7 | "Owned" docs endpoint via `owner_department_id` (DOC-07), unclear relation to access | `owner_department_id` never implies access; explicit join rows (02) | DOC-07, SEC-04, SEC-05 | `docs/backend/documents.md`; `repositories/document_repository.py`, `models/document.py` |
| 8 | Redis caches `docs:access:*` with TTL (ARCH-08, DOC-06, ING-06) | No Redis in target; caches partitioned by identity/department and invalidated on logout, switch, revocation (02, 05) | Retired; SEC-10, DOC-10 | `docs/backend/{architecture,documents,ingestion}.md`; `core/redis_client.py` |
| 9 | Source is a Google Drive URL via gdown (ADM-06, ING-01) | PDF upload / ZIP + manifest to private R2; gdown removed (03) | Retired; ADM-03, ADM-10..14 | `docs/backend/{admin-docs,ingestion}.md`, `docs/frontend/admin-upload.md`; `services/ingestion_service.py`, `pages/AdminUpload.jsx` |
| 10 | Celery task + Redis pub/sub events (ING-03/04) | Transactional outbox + QStash + Cloud Scheduler recovery; at-least-once; leases (03) | Retired; ING-12..16, ING-19 | `docs/backend/ingestion.md`; `tasks/ingestion_task.py`, `core/{celery_app,event_listener}.py` |
| 11 | WebSocket status `/ws/documents/{id}` (ING-07/08, FE-ADM-05/06) | SSE status from DB truth; no WebSocket (03, 05) | ING-07 reworded, ING-08 retired, FE-ADM-05/06 reworded | `docs/backend/ingestion.md`, `docs/frontend/admin-upload.md`; `routers/ws.py`, `core/websocket_manager.py` |
| 12 | Chunking 1024/100 into Chroma, `db_doc_id` only (ING-02) | PyMuPDF4LLM per page, 512/64, page-bounded, doc/revision/page metadata, pgvector (03, 04) | ING-02 rewritten; ING-18 | `docs/backend/ingestion.md`; `services/ingestion_service.py`, `core/vector_store.py` |
| 13 | Status `pending`/`ingested`/`failed` | `queued` / `processing` + phase / `ready` / `failed`; revisions with atomic promote (03) | ING-05, ADM-15, LIFE-08, FE-ADM-10 | ingestion, admin-docs, lifecycle, admin-upload specs; `models/document.py` |
| 14 | Hard delete + Chroma delete (ADM-08) | Soft delete that blocks immediately; durable async cleanup (03) | ADM-08, ING-20, LIFE-06 | `docs/backend/admin-docs.md`; `services/docs_service.py` |
| 15 | Agent tools `list_accessible_documents`, `fetch_document` (CHAT-06/07) | App code controls authorization/retrieval/citations; LlamaIndex as a library (04) | Retired; CHAT-04, CHAT-11, CHAT-16 | `docs/backend/chat.md`; `agent/llama_tools.py`, `agent/llama_agent.py` |
| 16 | Chroma `IN` filter, `similarity_top_k=6` (CHAT-04) | SQL+pgvector filter before Top-K; initial k=5 plus threshold (04) | CHAT-04, SEC-08 | `docs/backend/chat.md`; `agent/llama_tools.py` |
| 17 | `gpt-4o-mini` direct via OpenAI | OpenRouter → OpenAI-family model chosen by benchmark (04) | CHAT-16; **OPEN-02** | `docs/backend/chat.md`; `agent/llama_agent.py` |
| 18 | SSE events `token`/`tool`; client sends the last 10/20 messages (CHAT-02/03, FE-CHAT-04) | `searching`/`generating`/delta/`done`/`error`; server-persisted conversations; per-turn retrieval (04) | CHAT-02/03 reworded; FE-CHAT-04 retired; CHAT-14 | `docs/backend/chat.md`, `docs/frontend/chat.md`; `services/chat_service.py`, `pages/Chat.jsx` |
| 19 | No Stop, no citation validation, no history | AbortController Stop, validated citations, history whose citations lose link/content after revocation while answer text stays (04 as amended by OPEN-11) | CHAT-11..15, FE-CHAT-10..11 | chat specs |
| 20 | Monitor route placeholder (MON-01) | Structured JSON logs, correlation ids, audit, basic metrics; no Sentry (06) | MON-01 retired; MON-03..06 | `docs/backend/monitoring.md`; `routers/monitor.py` |
| 21 | Frontend React JS + npm + `api.js` + Context (FE-ARCH-01..05) | React TS strict, pnpm, generated OpenAPI client, TanStack Query, Tailwind/shadcn, RHF/Zod (05) | FE-ARCH-01..05 reworded, 08..13 added | `docs/frontend/architecture.md`; `frontend/` |
| 22 | Test methodology: TestClient with Redis/Celery/Chroma fakes; frontend tool "recommended" | pytest-asyncio + HTTPX on real PG+pgvector; Vitest+RTL; Playwright; tiered gates; traceability (05, 07) | `docs/README.md` rules, TEST-01..09 | `docs/README.md`, `docs/workflow/testing.md` |
| 23 | Commands: uvicorn/celery/npm only | uv/pnpm/Compose (target); legacy commands kept as labeled LEGACY | AGENTS.md "Commands" | `AGENTS.md` |
| 24 | My Documents filters by *allowed* departments; "View PDF" opens a raw download | Filter by **owner** department; protected React-PDF viewer with `?page=N` (01) | FE-DOC-03, FE-DOC-07..09 | `docs/frontend/my-documents.md`; `pages/MyDocuments.jsx` |

| 25 | Password needs ≥8 chars, an uppercase letter and a digit (old AUTH-03; `auth_schema.py`, `Register.jsx`) | 8-char minimum, no composition rules, blocklist, Unicode (OPEN-15) | AUTH-03, FE-AUTH-03 rewritten | `docs/backend/auth.md`, `docs/frontend/auth.md`; `pydantic_schemas/auth_schema.py`, `pages/Register.jsx` |
| 26 | Login only by email + password | Password **or** Email OTP, same session type (new auth decision) | AUTH-22..28, FE-AUTH-10 added | auth specs, `docs/milestones/M1/plan.md` |
| 27 | Source 01/02/04: persisted history must not expose revoked documents; "redact/hide" historical text | OPEN-11: saved answer text stays visible; citations, viewer, retrieval and streams are restricted | Source package superseded for historical text only; tradeoff documented in the security spec | `docs/cross-cutting/security-and-permissions.md`, `docs/backend/chat.md`, `docs/frontend/chat.md`, `docs/cross-cutting/product-and-ux.md` |
| 28 | Source 02: "appropriately scoped SameSite"; CSRF mechanism open | `SameSite=Lax`, host-only API cookie, session-bound CSRF token + Origin check, `app.`/`api.` same-site subdomains (OPEN-04) | AUTH-06, AUTH-14, AUTH-19, INFRA-11 | auth and infrastructure specs; `backend/app/main.py` CORS (Vercel origin) |
| 29 | Text-less PDF handling undecided | `failed` + `NO_EXTRACTABLE_TEXT`, retained for Admin, never published, replace + retry; no OCR (OPEN-17) | ING-23 added | `docs/backend/ingestion.md`, `docs/backend/admin-docs.md`, `docs/frontend/admin-upload.md` |

**Duplicates reconciled:** rules about access, status codes and caching were previously repeated in several specs. They now live once in SEC-* and are referenced elsewhere. Logging and quota rules moved to MON-* and COST-*.

**Ambiguities:** OPEN-12 to OPEN-18 were reported in the first pass and have since been resolved by the user. New ambiguities found in the second pass were OPEN-19 (Admin and Email OTP; resolved in the third pass as password-only) and OPEN-20 (confirm reconciliation-added M0 IDs, still open). The third pass also replaced the second pass's ZIP owner-default interpretation with explicit `allowed_departments`, and moved failed-document file replacement into M3 (ADM-18) (see `../open-decisions.md`).

## 2. Current-code gaps (legacy, not migrated)
Every target requirement is **not implemented**. Of these, the following legacy behaviors are actively unsafe or contradict the target, and should not be "fixed in place" on the legacy stack without a decision:
1. Anyone can self-register as Admin (`pydantic_schemas/auth_schema.py`), contradicting AUTH-04.
2. A global agent singleton with shared Chroma vector memory can mix users' conversation context (`agent/llama_agent.py`), contradicting SEC-10 and CHAT-14.
3. The WebSocket status endpoint is unauthenticated (`routers/ws.py`), contradicting ING-11.
4. Forbidden downloads return 403, which reveals that the document exists (`routers/docs.py`), contradicting SEC-02.
5. Stale-cache access after revocation, caused by the cache key mismatch (`core/event_listener.py`) and by PATCH not invalidating departments that lost access. This contradicts SEC-09.
6. Tool outputs containing document content are printed to logs (`services/chat_service.py`, `agent/llama_tools.py`), contradicting MON-05.
7. The session cookie has `secure=False` (`routers/auth.py`).
8. Binary data is committed: `backend/app/chroma_data/` and `backend/app/static/docs/*.pdf`. This contradicts the "no committed static PDFs" rule. Left untouched per the guardrails; removal is an M0 decision.
9. `/documents/my/owned` crashes (a non-existent column). `fetch_document_tool` always fails.
10. `requirements.txt` is unpinned and incomplete. There are no tests.

## 3. Recommended implementation order (for user decision; nothing started)
1. **Approve this docs-only PR and explicitly authorize M0.** OPEN-01 and OPEN-18 are now resolved, so nothing else blocks M0.
2. **M0** in task-graph order: M0-01 repository transition skeleton, contracts and tooling; then M0-02/03/04/05 as dynamically allocated parallel workstreams (WF-16); then M0-06 integration CI/deploy; then M0-07 review package. This covers the INFRA-03 spike, the same-site domain feasibility (INFRA-11, M0-AC11), OPEN-06, OPEN-09 and OPEN-10.
3. **M1 Auth & Demo**, including Email OTP (`../milestones/M1/plan.md`). This removes JWT, the self-registered Admin and the shared-memory risks at the root (items 1, 2 and 7 above). Security tests for SEC-01, SEC-03, SEC-13, SEC-16 and SEC-17 run from the start. The Admin is password-only (OPEN-19).
4. **M2 Library & Access.** Owner/access schema, R2 bytes endpoint, viewer, 404 semantics (items 4, 5, 9).
5. **M3 Upload & Ingestion.** Outbox, QStash, Worker, ZIP with explicit `allowed_departments`, failed-document file replacement (ADM-18), SSE status (item 3 is retired along with the WebSocket).
6. **M4 RAG Chat & Citations** (first usable MVP). Authorized Retriever, citations, history, quotas and kill switch, plus the seed of the eval suite.
7. **M5 Lifecycle/Hardening** (ready-document replacement with atomic promotion, soft delete cleanup, revocation in history), then **M6 Evaluation & Production hardening**.

Until a milestone replaces it, the legacy app should not be deployed publicly, because of items 1–6.
