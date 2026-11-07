# Backend documents (user-facing library and PDF access)

**Status:** Target spec (M2). Metadata and bytes routes (DOC-04, 05, 09, 10, 11) are implemented locally in M2-03 (not deployed, no R2 end-to-end evidence); the library list (DOC-01, 03, 07, 08) is M2-02. The legacy code serves PDFs from local disk with JWT department checks.

## Purpose
User-facing read paths: the document library, metadata, and protected PDF bytes for the viewer. Admin management is in `admin-docs.md`; visibility rules are SEC-04 to SEC-09.

## Data model (target)
- `documents`: id, title/filename, `owner_department_id` (ownership only, SEC-04), soft-delete marker, pointer to the current revision.
- `document_revisions`: revision id, document id, storage key in private R2, status (`queued`/`processing`/`ready`/`failed` + phase), embedding model/index identity (ING-18).
- The **current revision** is the promoted one that users are served. A first upload has no current revision until it becomes `ready`. A replacement of a ready document is a *candidate* revision until it is atomically promoted (ADM-15, M5). A failed document that never had a current revision gets its replacement file as a new revision of the same document (ADM-18, M3), which becomes current through the same first-ready path as an initial upload; no promotion swap is involved.
- `document_department_access` (document_id, department_id): the **only** source of read access (SEC-05).

Exact columns are fixed by the M2/M3 schema contract (ARCH-11).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| DOC-01 | The library endpoint returns only documents visible to the caller's **active department** per SEC-07. Each item has id, title/filename, owner department and the fields the UI needs. The list is cursor-paginated: query `limit` and an opaque `cursor`; the response has `items`, `next_cursor` and `has_more`. Search, owner filter and the visibility predicate apply before pagination, and the order is stable and deterministic (OPEN-28 Q3). No total count. | M2 |
| DOC-03 | A request without an active department returns **409 `ACTIVE_DEPARTMENT_REQUIRED`** and no documents (OPEN-14). The API never falls back to "all documents", including for the Admin (SEC-17). | M2 |
| DOC-04 | A PDF bytes endpoint streams the current ready revision from private R2 **through the API** after a per-request access check (SEC-06). No R2 or public URL is ever returned. Responses are not publicly cacheable. | M2 |
| DOC-05 | Status codes: no session → 401 (SEC-01); forbidden, unknown, not ready or deleted → identical 404 (SEC-02). | M2 |
| DOC-07 | The owner department is returned and filterable, but never grants access (SEC-04). | M2 |
| DOC-08 | The library supports filename search and filtering by owner department, both within the visible set. | M2 |
| DOC-09 | A metadata endpoint used by the viewer and by citation deep links (`/documents/:id?page=N`) returns filename and page count under the same checks as DOC-04. A page outside the range returns a validation error. | M2/M4 |
| DOC-10 | Revocation or soft delete is effective on the very next request to every endpoint here (SEC-09). There is no server cache that can serve stale access. | M2 |
| DOC-11 | The bytes endpoint supports a single byte range (`Range`, with `If-Range`): a valid range returns 206 with `Content-Range`, an unsatisfiable one 416, and the document authorization is rechecked on every request including each range request. Multiple ranges are not supported (OPEN-28 Q2). | M2 |

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
| DOC-01 | integration | 5 visible docs, `limit=2`, follow `next_cursor` to the end, with a search term and an owner filter | each document exactly once in a stable order; `has_more` false on the last page; filtered-out and forbidden documents never appear on any page |
| DOC-11 | integration | Valid range / unsatisfiable range / range on a forbidden or revoked doc / revoke between two range requests | 206 with `Content-Range` / 416 / 404 / second request 404 |

## Current implementation (LEGACY, not migrated)
- `routers/docs.py` exposes `/documents/my/access`, `/my/owned` and `/my/{id}/download`. The controller lives in `controllers/docs_controller.py` and the logic in `services/docs_service.py`.
- Access is based on the JWT `department_id`. Admins see all documents.
- A forbidden download returns **403**, not 404 (it contradicts DOC-05).
- PDFs are read from the committed local folder `backend/app/static/docs/{id}.pdf`.
- `/my/owned` references `Document.owner_department_id`, which does not exist in `models/document.py`, so the endpoint crashes.
- Redis caches are keyed by department, and empty results are never cached.
- There is no `ready`/current-revision concept: `status` is a free string `pending`/`ingested`/`failed`. There is no soft delete and no revisions.

## Known gaps
- DOC-01, DOC-03, DOC-07 and DOC-08 (library list) are M2-02.
- DOC-04, 05, 09, 10, 11 are implemented in M2-03 and tested against `FakeObjectStore` and a mock R2 transport. The R2 path is unverified against a real bucket until M2-00c, and streaming limits of Cloud Run and the Pages Function are unmeasured.
- A range request that is multiple, malformed or of another unit is answered with the full body (200) instead of an error.
- A stream that fails after the headers are sent ends early (short read); the client retries.

## Related docs
`admin-docs.md`, `ingestion.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/document-lifecycle.md`, `../frontend/my-documents.md`
