# Backend documents (user-facing library and PDF access)

**Status:** Target spec (M2). Not implemented: the legacy code serves PDFs from local disk with JWT department checks.

## Purpose
User-facing read paths: the document library, metadata, and protected PDF bytes for the viewer. Admin management is in `admin-docs.md`; visibility rules are SEC-04 to SEC-09.

## Data model (target)
- `documents`: id, title/filename, `owner_department_id` (ownership only, SEC-04), soft-delete marker, pointer to the current revision.
- `document_revisions`: revision id, document id, storage key in private R2, status (`queued`/`processing`/`ready`/`failed` + phase), embedding model/index identity (ING-18).
- The **current revision** is the promoted one that users are served. A first upload has no current revision until it becomes `ready`. A replacement is a *candidate* revision until it is atomically promoted (ADM-15).
- `document_department_access` (document_id, department_id): the **only** source of read access (SEC-05).

Exact columns are fixed by the M2/M3 schema contract (ARCH-11).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| DOC-01 | The library endpoint returns only documents visible to the caller's **active department** per SEC-07. Each item has id, title/filename, owner department and the fields the UI needs. | M2 |
| DOC-03 | A request without an active department returns **409 `ACTIVE_DEPARTMENT_REQUIRED`** and no documents (OPEN-14). The API never falls back to "all documents", including for the Admin (SEC-17). | M2 |
| DOC-04 | A PDF bytes endpoint streams the current ready revision from private R2 **through the API** after a per-request access check (SEC-06). No R2 or public URL is ever returned. Responses are not publicly cacheable. | M2 |
| DOC-05 | Status codes: no session → 401 (SEC-01); forbidden, unknown, not ready or deleted → identical 404 (SEC-02). | M2 |
| DOC-07 | The owner department is returned and filterable, but never grants access (SEC-04). | M2 |
| DOC-08 | The library supports filename search and filtering by owner department, both within the visible set. | M2 |
| DOC-09 | A metadata endpoint used by the viewer and by citation deep links (`/documents/:id?page=N`) returns filename and page count under the same checks as DOC-04. A page outside the range returns a validation error. | M2/M4 |
| DOC-10 | Revocation or soft delete is effective on the very next request to every endpoint here (SEC-09). There is no server cache that can serve stale access. | M2 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| DOC-02 | Admins see all documents in `/documents/my/access` | Rejected by OPEN-13: no Admin bypass in user-facing paths (SEC-17). The Admin sees all documents only via the Admin list (ADM-02). |
| DOC-06 | Redis cache `docs:access:{dept}` / `docs:all` with TTLs | Redis is not in the target; superseded by SEC-10 and DOC-10. |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| DOC-01 | integration | Docs shared with A, with B, with A not ready, with A `failed` (`NO_EXTRACTABLE_TEXT`), with A soft-deleted; caller active in A | only the ready, non-deleted A doc listed |
| DOC-03 | integration | Session (user and Admin) without an active department | 409 `ACTIVE_DEPARTMENT_REQUIRED` envelope; no document data |
| DOC-04 | integration | Allowed caller fetches bytes (R2 faked) | 200, `application/pdf`, no-store/private caching; the body never contains a storage URL |
| DOC-05 | integration | No session / forbidden / unknown id / deleted | 401 / 404 / 404 / 404 with identical bodies |
| DOC-07 | integration | Owner = A, access = B only; caller in A | not listed; 404 on bytes |
| DOC-08 | integration | Search "hand" + owner filter | intersection, within the visible set only |
| DOC-09 | integration | Valid page / page 0 / page > count / forbidden doc | 200 / 422 / 422 / 404 |
| DOC-10 | integration | Revoke, then immediately request the list and the bytes | absent / 404 |

## Current implementation (LEGACY, not migrated)
- `routers/docs.py` exposes `/documents/my/access`, `/my/owned` and `/my/{id}/download`. The controller lives in `controllers/docs_controller.py` and the logic in `services/docs_service.py`.
- Access is based on the JWT `department_id`. Admins see all documents.
- A forbidden download returns **403**, not 404 (it contradicts DOC-05).
- PDFs are read from the committed local folder `backend/app/static/docs/{id}.pdf`.
- `/my/owned` references `Document.owner_department_id`, which does not exist in `models/document.py`, so the endpoint crashes.
- Redis caches are keyed by department, and empty results are never cached.
- There is no `ready`/current-revision concept: `status` is a free string `pending`/`ingested`/`failed`. There is no soft delete and no revisions.

## Known gaps
Every DOC requirement is unimplemented on the target (R2, revisions, active department, 404 semantics).

## Related docs
`admin-docs.md`, `ingestion.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/document-lifecycle.md`, `../frontend/my-documents.md`
