# Admin API contract (M3)

**Status:** Shapes fixed by M3-01 for approval at CP1 (`docs/milestones/M3/plan.md`). The routes are 501 stubs until their slices land. A change to anything here needs Owner approval and a regenerated `openapi.json` (WF-03). The behavior stays in `../backend/admin-docs.md` and `../backend/ingestion.md`; this file fixes the concrete names.

Code: `apps/api/src/knowserve_api/admin/` (routes and `schemas.py`), `packages/backend_core/src/knowserve_core/ingestion_contract.py` (codes, phases, messages), `job_hooks.py` (Worker interfaces), `embeddings.py`, `object_store.py`. The frontend catalogs are in `apps/frontend/src/features/admin/admin-error-messages.ts`.

## Routes

All routes live under `/v1/admin`. A second `DELETE` of a deleted document is 404 (the id is deleted, as for any route), changes nothing and writes no second audit row. Every one needs a session (401) and the Admin role (403). Mutations also need the allowed Origin and the CSRF token (`X-CSRF-Token`), multipart ones included. None needs an active department, and none is affected by it (SEC-17 applies to the user routes). Ids in paths are uuids. A malformed, unknown or deleted document id is the same 404 `DOCUMENT_NOT_FOUND`, and it is checked after the session and the Admin role, so 401 and 403 always come first (OPEN-28 Q7). The id is a string in the OpenAPI schema for that reason; the `admin_document_id` dependency parses it.

| Method and path | Request | Success | Errors |
|---|---|---|---|
| `GET /documents` | query `limit` (1..50, default 20), `cursor`, `q`, `status` | 200 `AdminDocumentList` (cursor page, newest first, no total) | 401, 403, 422 |
| `POST /documents` | multipart `file`, `title`, `owner_department_id`, `allowed_department_ids` (repeated); header `Idempotency-Key` | 202 `AdminDocumentOut` | 401, 403, 409, 413, 422, 429, 503 |
| `GET /documents/{id}` | | 200 `AdminDocumentOut` | 401, 403, 404 |
| `GET /documents/{id}/events` | | 200 `text/event-stream` | 401, 403, 404 |
| `PATCH /documents/{id}/access` | JSON `{allowed_department_ids}` | 200 `AdminDocumentOut` | 401, 403, 404, 422 |
| `DELETE /documents/{id}` | | 204 | 401, 403, 404 |
| `POST /documents/{id}/retry` | | 202 `AdminDocumentOut` | 401, 403, 404, 409 |
| `POST /documents/{id}/replace` | multipart `file`; header `Idempotency-Key` | 202 `AdminDocumentOut` | 401, 403, 404, 409, 413, 422, 429, 503 |
| `POST /imports/preview` | multipart `file` (the ZIP) | 200 `ImportPreviewResponse` | 401, 403, 413, 422, 503 |
| `POST /imports/confirm` | multipart `file` (the same ZIP again); header `Idempotency-Key` | 200 `ImportConfirmResponse` | 401, 403, 409, 413, 422, 429, 503 |

Upload and replace answer 202 because processing continues in the Worker (the spec's "200" is replaced; ADM-03). A partially successful ZIP confirmation is 200 with per-file results (ADM-14). The ZIP is sent again at confirmation because preview stores nothing (ADM-12) and confirmation validates everything again (ADM-11).

`allowed_department_ids` is optional in the OpenAPI schema on purpose: the route answers with `ALLOWED_DEPARTMENTS_MISSING` or `ALLOWED_DEPARTMENTS_EMPTY` instead of a generic validation error (ADM-05). `PATCH .../access` takes an empty list for the same reason.

### Upload-producing routes and the stop switch

`POST /documents`, `POST /documents/{id}/replace`, `POST /imports/preview` and `POST /imports/confirm` depend on `require_uploads_enabled`. With `KS_UPLOADS_ENABLED=false` they answer 503 `UPLOADS_DISABLED` after the auth checks. Reads, access changes, delete and retry do not depend on it, and running jobs are never cancelled (OPEN-31 D14).

### Idempotency

`Idempotency-Key` (`^[A-Za-z0-9_-]{8,128}$`) is required on create, replace and import confirmation. A key is scoped to the Admin and to one operation. The same key with the same request (a hash of the file bytes and the normalized metadata) returns the stored status and body, with no second document and no second job. The same key with a different request is 409 `IDEMPOTENCY_KEY_REUSED`. A replay still passes the session, CSRF and Admin checks of the request, so a revoked Admin gets nothing from an old key. A new key re-checks the operation's preconditions inside the transaction that performs it (for replace, the atomic `failed` to `queued` change), so stale state cannot start a second attempt. Two concurrent requests with one key cannot both create rows: the idempotency row is written in the same transaction as the document rows, the unique key makes the second transaction fail and roll back, and that request then replays the first result. Table `admin_idempotency_keys` (migration `0004`) holds the completed result; it is written in the same transaction as the rows it describes. `import_batch_entries` records each manifest entry's outcome, so a confirmation that stopped half way resumes under the same key without creating an entry twice.

## Models

`AdminDocumentOut` extends `DocumentProcessingStatus`.

| Field | Meaning |
|---|---|
| `document_id`, `revision_id` | The document and its latest revision (ADM-02 shows the latest revision, not the current one). |
| `status` | `queued`, `processing`, `ready` or `failed`. |
| `phase` | `fetching`, `extracting`, `chunking`, `embedding` or `publishing` while processing; no percentages (ING-07). |
| `failure_code`, `failure_message` | A `FailureCode` and its English fallback text. The interface text comes from the frontend catalog by code. |
| `delivery_state` | The derived job state from `job_recovery.py` (`publish_failed`, `unpublished_stuck`, `queued_stuck`, `processing_stuck`, `failed` and the rest), or null. |
| `can_retry`, `can_replace` | Computed on the server, so the client keeps no action rules (ADM-16, ADM-18). `can_retry` stays true for a failed `NO_EXTRACTABLE_TEXT` document, as FE-ADM-06 requires; the UI puts Replace file first for terminal reasons. Each mutation re-checks its precondition atomically, whatever the flags said when the screen loaded. Both are computed in `admin/document_views.py` only. `can_retry`: the latest revision is not `ready` and its job's delivery state is one `retry_job` accepts. `can_replace`: no current revision, latest revision `failed`, and no active job. |
| `title`, `filename`, `owner_department`, `allowed_departments`, `page_count`, `size_bytes`, `created_at`, `updated_at` | Document data. Departments are `{id, slug, name}`. |

`ImportEntryPreview` and `ImportEntryResult` identify an entry by `index` and `file`, carry an `error_code` (an `AdminErrorCode`), the English fallback `error_message` and an optional `detail` (for example the unknown slug). Preview never creates anything.

### ZIP manifest

`manifest.json` in the archive root, at most `KS_UPLOAD_MAX_MANIFEST_BYTES`:

```json
{"version": 1, "documents": [
  {"file": "leave-policy.pdf", "title": "Leave policy",
   "owner_department": "human-resources",
   "allowed_departments": ["human-resources", "finance"]}
]}
```

`owner_department` and every entry of `allowed_departments` are department slugs, checked against the departments table (OPEN-31 D10). `allowed_departments` is required and non-empty for every entry; nothing is inferred from `owner_department` (OPEN-16). The archive is read in memory and never extracted to disk. Limits are the D1 values in `config-and-deploy.md`.

## Status stream

`GET /documents/{id}/events` is for the Admin only and is scoped to one document. Every message is built from the database.

```
event: status
data: {"document_id": "...", "revision_id": "...", "status": "processing", "phase": "embedding", ...}

: keepalive

event: end
data: {"reason": "terminal"}
```

`status` carries `DocumentProcessingStatus`, sent on connect and on every change. A comment line goes out every `KS_SSE_KEEPALIVE_SECONDS` (15). `end` follows a `ready` or `failed` status (`terminal`), or comes after `KS_SSE_MAX_SECONDS` (120) with reason `timeout`, and the client reconnects. There are no event ids, no persisted event history and no replay, because a reconnect starts with a fresh `status` read from the database. Connecting or reconnecting never creates or requeues a job. The document list is the fallback when the stream fails.

Implemented (M3-05a): the snapshot is read before the response starts, so 401, 403 and 404 are real statuses. After that the stream reads the database once a second and sends a `status` event whenever the payload changes (a phase, the delivery state or an action flag counts), a keepalive comment after `KS_SSE_KEEPALIVE_SECONDS` without an event, and `end` with `terminal` after `ready` or `failed`, or when the document is deleted while watched, or with `timeout` after `KS_SSE_MAX_SECONDS`. The Pages proxy already passes `text/event-stream` through unbuffered (`proxy.md`), so it needs no change.

## Error codes

The error envelope is the shared one (`api.md`). The codes below are stable; the English text in `ingestion_contract.ADMIN_ERRORS` is the fallback and the frontend catalog (English and Hebrew) is what users read. The OpenAPI `AdminErrorCode` enum is generated from the same Python enum, and the frontend catalog is typed on it, so adding a code breaks the build until both languages have text.

| Group | Codes (status) |
|---|---|
| Not found | `DOCUMENT_NOT_FOUND` (404) |
| Single file | `FILE_EMPTY` (422), `FILE_TOO_LARGE` (413), `NOT_A_PDF` (422), `INVALID_FILENAME` (422), `TITLE_INVALID` (422) |
| Departments | `UNKNOWN_DEPARTMENT`, `ALLOWED_DEPARTMENTS_MISSING`, `ALLOWED_DEPARTMENTS_EMPTY` (all 422) |
| ZIP | `ZIP_TOO_LARGE` (413); 422: `ZIP_INVALID`, `ZIP_TOO_MANY_FILES`, `ZIP_UNSAFE_PATH`, `ZIP_SYMLINK`, `ZIP_RATIO_EXCEEDED`, `ZIP_UNCOMPRESSED_TOO_LARGE`, `ZIP_NESTED_ARCHIVE`, `ZIP_ENCRYPTED`, `ZIP_DUPLICATE_NAME`, `ZIP_UNLISTED_FILE` |
| Manifest | 422: `MANIFEST_MISSING`, `MANIFEST_INVALID`, `MANIFEST_VERSION_UNSUPPORTED`, `MANIFEST_TOO_LARGE`, `MANIFEST_FILE_MISSING` |
| State | `DOCUMENT_NOT_REPLACEABLE`, `DOCUMENT_NOT_RETRYABLE`, `IDEMPOTENCY_KEY_REUSED` (all 409) |
| Limits | `UPLOAD_BACKLOG_FULL`, `DAILY_UPLOAD_LIMIT` (429), `UPLOADS_DISABLED` (503) |

Failure codes (stored in `document_revisions.failure_reason`, shown through `failure_code`):

| Kind | Codes |
|---|---|
| Terminal (no automatic retry, ING-23) | `NO_EXTRACTABLE_TEXT`, `INVALID_PDF`, `PDF_ENCRYPTED`, `TOO_MANY_PAGES`, `DOCUMENT_DELETED` |
| Retried until the cap, then `failed` | `STORAGE_UNAVAILABLE`, `EMBEDDING_FAILED`, `PROCESSING_TIMEOUT`, `PROCESSING_CRASHED`, `INTERNAL_ERROR` |

## Interfaces

- `ObjectStore.delete(key)`: idempotent. The API uses it to remove an object when the database transaction fails. The Worker's credential is read-only and never calls it.
- `EmbeddingProvider.embed(texts)`: one vector per text, all or nothing, raising `EmbeddingError`. `FakeEmbeddingProvider` is deterministic and refused in production. The OpenAI provider is written in M3-02b.
- `job_hooks.py`: `NonRetryableJobError` and `RetryableJobError` (raised by handlers with a `FailureCode`), `TerminalFailureHook` (called in the transaction that marks a job `failed`; sets the revision `failed`, and never touches a `ready` revision) and `RequeueHook` (called by `retry_job`; sets the revision back to `queued`). M3-00a implements them in the Worker and `job_recovery`; M3-05a calls `retry_job`.

## Schema (migration `0004`)

Additive only. `document_chunks` (document and revision with a composite key, `page`, `ordinal`, `text`, `token_count`, `embedding vector(1536)`, unique `(revision_id, ordinal)`, no vector index). `document_revisions.job_id` (nullable, unique where set). `admin_idempotency_keys` and `import_batch_entries`. Rollback of the application needs no downgrade (INFRA-05); `alembic downgrade 0003` drops the new tables and every chunk.

## Implemented behaviour: upload and import (M3-03, M3-04)

- **Creation service** (`admin/creation.py`): the object is stored first under `documents/{document_id}/{revision_id}.pdf`; then one transaction takes an advisory lock, re-checks the in-flight and per-day limits, writes document, revision, access rows, job, outbox and audit rows, and writes the idempotency row last. A failed transaction deletes the object (kept and logged if the database cannot confirm the revision is absent). `publish_after_commit` runs after the commit.
- **Validation split.** The API rejects empty, oversize, wrong-signature or truncated files (`FILE_EMPTY`, `FILE_TOO_LARGE`, `NOT_A_PDF`), bad names (`INVALID_FILENAME`) and bad titles. Encrypted, image-only and over-page-limit PDFs are accepted and fail in the Worker with `PDF_ENCRYPTED`, `NO_EXTRACTABLE_TEXT` and `TOO_MANY_PAGES`. The structural check is `validation.check_pdf_structure`; set `app.state.pdf_check` to replace it.
- **Multipart.** Unknown form fields are rejected with 422 `VALIDATION_ERROR` (no mass assignment). A blank `allowed_department_ids` value means none chosen (`ALLOWED_DEPARTMENTS_EMPTY`); an absent field is `ALLOWED_DEPARTMENTS_MISSING`.
- **Limits.** 429 `UPLOAD_BACKLOG_FULL` counts non-deleted revisions that are `queued` or `processing`; 429 `DAILY_UPLOAD_LIMIT` counts documents created since 00:00 UTC.
- **Import.** Archive-level problems reject the request with 422 and a code (unsafe path, symlink, encryption, ratio, totals, file count, nested archive, duplicate or case-folded duplicate names, unlisted file, manifest errors). Entry-level problems (title, departments, missing or non-PDF member) invalidate only that entry. Confirm checks headroom for all valid entries first (429, nothing created), records an in-progress `admin_idempotency_keys` row (`result_status` 0), creates each entry in its own transaction together with its `import_batch_entries` row, and stores the final 200 body on the key row. The same key and ZIP resumes; the same key with another ZIP is 409.
