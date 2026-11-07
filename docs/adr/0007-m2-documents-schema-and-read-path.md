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
  That the revision is `ready` is enforced by the predicate, not by the schema, because M3 moves
  revisions through statuses.
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
  and Terraform must set `KS_OBJECT_STORE=r2` before the M2 deploy (needs separate approval).
- The route stubs return 501 until M2-02 and M2-03.
