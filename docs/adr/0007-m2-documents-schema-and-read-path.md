# ADR 0007: M2 documents schema, read path and object store

Status: accepted by the Owner on 2026-11-07 (OPEN-28, Q1 to Q12), implemented in M2-01.

## Context
M2 adds the document library. Three workstreams depend on one definition of "visible", and the bytes
must never leave the API as a storage URL.

## Decisions
- **Migration `0003_m2_documents`** adds `documents`, `document_revisions` and
  `document_department_access`. It only adds tables, so earlier API and Worker revisions keep
  working and rollback needs no schema change (INFRA-05).
- **Full revision column set** from `docs/backend/documents.md` (Q4): status, phase, failure
  reason, page count, size, content type, embedding model and index identity, timestamps.
- **Same-document current revision.** `documents(current_revision_id, id)` has a composite foreign
  key to `document_revisions(id, document_id)`, so a pointer cannot reach another document's
  revision. The pointer is nullable (a NULL skips the check), which also breaks the insert cycle.
  That the current revision is `ready` is enforced only by the shared visibility predicate, not by a
  database constraint, because M3 moves revisions through statuses. A current pointer at a
  non-ready revision is therefore legal in the schema and invisible to every user-facing path.
- **A `ready` revision must have `page_count` and `ready_at`** (check constraint).
- **One predicate.** `knowserve_core.documents_access.visible_documents(department_id)` returns a
  select of `(Document, DocumentRevision)` for documents that are not soft-deleted, whose current
  revision is `ready`, and that have an access row for the department. List, metadata, bytes and
  (M4) retrieval extend it. Access comes only from `document_department_access`; the owner column
  is a label (SEC-04).
- **One 404.** `document_not_found()` is the only not-found the document routes may raise
  (`DOCUMENT_NOT_FOUND`, one fixed message). `parse_document_id` maps malformed ids to it (Q7).
- **Cursor design.** Order is `created_at DESC, id DESC` (index `ix_documents_created_at_id`). The
  cursor is the opaque, URL-safe encoding of the last row's `(created_at, id)`. It holds no
  document data. Anything that does not decode to that shape returns 422. Page size defaults to 20,
  maximum 50. Implemented in M2-02.
- **Object store.** `ObjectStore` has `put`, `size` and `stream` (optional inclusive byte range).
  `FakeObjectStore`, `FilesystemObjectStore` and (M2-03) `R2ObjectStore`. `build_object_store`
  refuses `fake` and `filesystem` when `KS_ENV=production`. No method returns a URL. Storage keys
  follow `documents/{document_id}/{revision_id}.pdf` and are never sent to clients.

## Consequences
- The production guard sits in the factory, not in `Settings`, so a deployed M1 revision with no
  `KS_OBJECT_STORE` keeps starting. M2-03 must call the factory at startup of the document routes
  and Terraform must set `KS_OBJECT_STORE=r2` before the M2 deploy (needs separate approval). Once the
  R2 configuration is wired (M2-03), production startup must fail clearly when the object store
  configuration is missing or selects `fake` or `filesystem`.
- `updated_at` has no database trigger or `onupdate`; M3 must set it when document records change.
- The list route stub returns 501 until M2-02.

### M2-03 additions (bytes, R2 and the startup guard)
- **`R2ObjectStore`** uses `httpx` (already a dependency) with a small AWS SigV4 signer for HEAD, ranged GET and PUT (path-style, region `auto`). No boto3, so the lockfile and the image are unchanged. The signer is checked against AWS's published example; there is no R2 end-to-end evidence until M2-00c.
- **Startup guard.** `create_app` builds the store once. In production only `KS_OBJECT_STORE=r2` with `KS_R2_ENDPOINT` (https), `KS_R2_BUCKET`, `KS_R2_ACCESS_KEY_ID` and `KS_R2_SECRET_ACCESS_KEY` starts; anything else raises `RuntimeError` naming the missing setting (never a value). Outside production the default stays `filesystem`.
- **Deployed M1 revisions keep starting** because they do not contain this code: they ignore the new `KS_*` variables (`extra="ignore"`). Terraform therefore sets the R2 variables on the API service **before** the M2 image is rolled out (a separate approval). If the M2 image is rolled out first, the new revision fails its startup check and Cloud Run keeps routing traffic to the previous healthy revision, so the failure is loud and does not take the service down. A lazy check at first request was rejected because it would let a production API start with no store and fail users later.
- **Range semantics.** A single well-formed `bytes=` range gives 206; one outside the object gives 416 (`RANGE_NOT_SATISFIABLE`, `Content-Range: bytes */size`). Multiple ranges, a unit other than `bytes` and malformed specs are ignored and the full body is served (RFC 9110). `ETag` is the strong revision id; `If-Range` honours the range only on an exact match.
- **Log hygiene.** `configure_logging` raises the `httpx` and `httpcore` loggers to WARNING, because httpx logs every request URL at INFO and the R2 URL contains the bucket host and the storage key.
