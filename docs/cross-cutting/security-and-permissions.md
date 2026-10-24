# Security and permissions (cross-cutting)

**Status:** Target spec. Not implemented: the legacy code uses JWT, a department taken from the token, Redis caches and Chroma (see "Current implementation"). Applies from M1 onward. Security tests are added in the earliest milestone they affect, not deferred to M6 (WF-14).

## Purpose
This is the single normative source for access-control rules, HTTP status semantics, isolation and defense-in-depth. Feature specs reference these IDs instead of restating them.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| SEC-01 | A request with no valid session (neither a registered user nor a Try Demo visitor) to a protected resource returns `401`. | M1 |
| SEC-02 | An authenticated request for a document that is forbidden, unknown, not ready, not current or soft-deleted returns `404`, indistinguishable from a request for a non-existent id. This covers metadata, PDF bytes, previews, citations, chunks and history references. | M2 |
| SEC-03 | A non-Admin calling an Admin-only API gets `403`. | M1 |
| SEC-04 | `owner_department_id` identifies the owning department only and **never implies read access**. | M2 |
| SEC-05 | Read access is granted only by explicit `document_department_access` rows. An organization-wide document has one row per department; there is no special "all" scope. | M2 |
| SEC-06 | Every route that returns PDF bytes, document metadata, previews, citations, RAG chunks or chat history enforces identity, session, active department and document state on the server on every request. Frontend checks are never relied on. | M2 |
| SEC-07 | A document is user-visible only if it is not soft-deleted, has a **current (promoted) revision** that is `ready`, and has an access row for the caller's active department. Unpromoted candidate revisions are never user-visible (definitions in `../backend/documents.md`). | M2 |
| SEC-08 | Retrieval applies the SEC-07 constraints in SQL **before** similarity ordering and Top-K. It never retrieves globally and filters afterwards. | M4 |
| SEC-09 | Revocation or soft delete takes effect immediately for the direct PDF/viewer, the library, retrieval and RAG generation, and citation links/content (OPEN-11). An in-flight stream revalidates and stops sending further content derived from the revoked document. **Previously saved answer text stays visible in history** (see "Historical answers after revocation" below), but its citations to the revoked document lose their link and content, and that text is never reused as trusted model context. | M2 (docs) / M4 (chat) / M5 (hardening) |
| SEC-10 | Data is isolated per identity and active department. A department switch resets frontend data and bounds multi-turn context to the new department. Cached data is partitioned by identity and department, and is invalidated on logout, switch and revocation. | M1 / M2 / M4 |
| SEC-11 | Uploaded PDFs and ZIPs are untrusted. The system validates signatures and types, filenames and paths, archive traversal, symlinks, zip bombs and count/size limits, and processes them with bounded resources and time. There is no OCR and no separate antivirus in the MVP. | M3 |
| SEC-12 | Documents and user prompts rank below system and developer instructions. The model has no administrative tool access. Prompt-injection content is treated as adversarial test input. | M4 |
| SEC-13 | If the DB or auth is unavailable, the system fails closed: no access is granted on error. An LLM outage only degrades chat (INFRA-10). | M1 |
| SEC-14 | The Worker endpoint accepts only deliveries with a valid QStash signature that reference an eligible DB job. URL secrecy is not authentication. | M0 (spike) / M3 |
| SEC-15 | Frontend route hiding and admin-control hiding are UX only. All authorization is enforced by the backend. | M1 |
| SEC-16 | Try Demo visitors are isolated from registered users, from each other, and per department. | M1 |
| SEC-17 | The Admin's elevated permissions apply **only** to dedicated Admin endpoints and UI (ADM-*). In the regular library, PDF viewer and RAG chat the Admin follows exactly the same active-department rules (SEC-07) as any user; there is **no global Admin bypass** (OPEN-13). | M1/M2/M4 |

### Demo authorization model (OPEN-12)
Any user or visitor may choose any fictional department, so department membership is self-selected. This is a demonstration model, clearly labeled Demo Mode (PROD-01), and not a claim that it suits a real enterprise. The guarantees that **are** enforced: per-request authorization by the active department, and no leakage of another department's conversations or documents across a switch (SEC-10).

### Historical answers after revocation (OPEN-11, approved tradeoff)
For this fictional demo the user approved a less strict historical-disclosure policy. Answer text generated while a user had access stays readable in that user's saved conversation after access is revoked, so information derived from the revoked document may remain visible there. Everything else is restricted immediately: the viewer, citation links/content, new retrieval and generation, and active streams. Historical answer text is not trusted context for new generation. This must not be reinterpreted as hiding or deleting old answers, nor presented as suitable for real confidential data.

Related normative rules live elsewhere:
- Session, CSRF + Origin check, password policy/hashing, Email OTP (password alternative, not MFA) and rate limits: `../backend/auth.md` (AUTH-03, AUTH-06, AUTH-10, AUTH-14, AUTH-15, AUTH-22..28).
- Secrets and IAM: `../architecture/infrastructure.md` (INFRA-07).
- Logging and audit: `../backend/monitoring.md` (MON-03 to MON-05).
- Quotas and budget: `../architecture/infrastructure.md` (COST-02 to COST-04).

## Status code summary
All errors use the envelope `{"error": {"code", "message", "request_id"}}` defined in ARCH-05 (OPEN-14).

| Situation | Code |
|---|---|
| No valid session | 401 |
| Valid session, non-Admin on an Admin API | 403 |
| Valid session, document forbidden / unknown / not ready / deleted | 404 (identical body, e.g. `DOCUMENT_NOT_FOUND`) |
| Operation needs an active department and none is selected | 409 `ACTIVE_DEPARTMENT_REQUIRED` |
| Validation error | 422 |
| Required dependency/service unavailable (where applicable; never a 200 with data, SEC-13) | 503 |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| SEC-01 | integration | Each protected route without a cookie; with an expired or revoked session | 401 |
| SEC-02 | integration | Direct URL to a restricted PDF; to a non-existent id; compare the responses | both 404 with identical bodies |
| SEC-03 | integration | Registered user and demo visitor call each Admin route | 403 |
| SEC-04 | integration | Owner department has no access row; user of that department lists, views and searches the document | not listed, 404 on view, absent from retrieval |
| SEC-05 | integration | Org-wide document with rows for every department | visible in each department; removing one row hides it there only |
| SEC-06 | integration | Matrix of every document-returning route × {allowed, forbidden, deleted, not-ready} | only allowed+ready returns data |
| SEC-07 | integration | Ready current revision with a replacement candidate still `processing` | the current revision is served; candidate chunks are never retrieved (ADM-15) |
| SEC-07 | integration | Document with no ready current revision (first upload still processing) | 404 / not listed |
| SEC-08 | integration (real pgvector) | Forbidden chunks are the nearest neighbours of the query | none returned; Top-K is filled from permitted chunks only |
| SEC-09 | integration | Revoke access, then hit PDF, library, search and citation link | 404 / absent / absent / citation without link or content |
| SEC-09 | integration | Revoke, then open the conversation history containing an answer based on the document | answer text still shown; its citation to the revoked doc has no link or content |
| SEC-09 | integration | Revoke, then ask a follow-up in that conversation | the old answer text is not passed as trusted context; retrieval excludes the doc |
| SEC-09 | integration | Revoke during an active stream | stream ends with an `error` or `done`; no further content drawn from the revoked document |
| SEC-10 | e2e | Switch department A→B; check library, chats and multi-turn follow-up | nothing from A visible; a follow-up does not reuse A context |
| SEC-11 | integration | Bad PDF signature, path traversal in a ZIP, a symlink, a zip bomb, over-count/over-size | rejected with a per-file reason; nothing stored |
| SEC-12 | eval | Prompt-injection cases in the golden set (EVAL-01) | hard-fail if any instruction is followed or data leaks |
| SEC-13 | integration | DB unavailable during session lookup | 5xx/401, never 200 with data |
| SEC-14 | integration | Worker called with no signature, a bad signature, a valid signature + unknown job | rejected; no processing |
| SEC-15 | e2e | Non-admin navigates to an admin URL | UI blocks it and the API returns 403 |
| SEC-16 | integration | Two demo visitors; one visitor in two departments | no cross-visitor or cross-department history or data |
| SEC-17 | integration | Admin with active department A requests the library, bytes and chat retrieval for a doc shared only with B | not listed / 404 / not retrieved; the same doc is visible via the Admin list endpoint |

## Current implementation (LEGACY, not migrated)
- `backend/app/utils/auth.py`: a JWT is read from a cookie or `Authorization: Bearer`. The department comes from the token, not from a server-side active department.
- Forbidden downloads return `403` rather than `404` (`routers/docs.py`), contradicting SEC-02.
- There is no `owner_department_id` column (the repository references it but `models/document.py` lacks it), so SEC-04 cannot be expressed.
- Retrieval filters Chroma by an `IN` list of allowed ids (`agent/llama_tools.py`). This is permission-scoped, but not SQL-before-Top-K in Postgres, and has no ready/current-revision rule.
- Redis caches (`docs:access:*`) are keyed by department only and invalidated inconsistently. This contradicts SEC-09 and SEC-10.
- The WebSocket status endpoint is unauthenticated. The Worker is Celery with no signed delivery.
- Admin can be self-registered (`pydantic_schemas/auth_schema.py`), contradicting AUTH-04.

## Known gaps
Every SEC requirement is unimplemented. The ones above are where the legacy code actively contradicts the target.

## Related docs
`../backend/auth.md`, `../backend/documents.md`, `../backend/chat.md`, `../backend/ingestion.md`, `document-lifecycle.md`, `../open-decisions.md`
