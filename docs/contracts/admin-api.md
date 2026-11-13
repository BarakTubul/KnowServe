# Admin API contract (M3)

**Status:** Shapes fixed by M3-01 for approval at CP1 (`docs/milestones/M3/plan.md`). The routes are 501 stubs until their slices land. A change to anything here needs Owner approval and a regenerated `openapi.json` (WF-03). The behavior stays in `../backend/admin-docs.md` and `../backend/ingestion.md`; this file fixes the concrete names.

Code: `apps/api/src/knowserve_api/admin/` (routes and `schemas.py`), `packages/backend_core/src/knowserve_core/ingestion_contract.py` (codes, phases, messages), `job_hooks.py` (Worker interfaces), `embeddings.py`, `object_store.py`. The frontend catalogs are in `apps/frontend/src/features/admin/admin-error-messages.ts`.

## Routes

All routes live under `/v1/admin`. Every one needs a session (401) and the Admin role (403). Mutations also need the allowed Origin and the CSRF token (`X-CSRF-Token`), multipart ones included. None needs an active department, and none is affected by it (SEC-17 applies to the user routes). Ids in paths are uuids; a malformed id is a normal 422.

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

`Idempotency-Key` (`^[A-Za-z0-9_-]{8,128}$`) is required on create, replace and import confirmation. A key is scoped to the Admin and to one operation. The same key with the same request (a hash of the file bytes and the normalized metadata) returns the stored status and body, with no second document and no second job. The same key with a different request is 409 `IDEMPOTENCY_KEY_REUSED`. Table `admin_idempotency_keys` (migration `0004`) holds the completed result; it is written in the same transaction as the rows it describes. `import_batch_entries` records each manifest entry's outcome, so a confirmation that stopped half way resumes under the same key without creating an entry twice.

## Models

`AdminDocumentOut` extends `DocumentProcessingStatus`.

| Field | Meaning |
|---|---|
| `document_id`, `revision_id` | The document and its latest revision (ADM-02 shows the latest revision, not the current one). |
| `status` | `queued`, `processing`, `ready` or `failed`. |
| `phase` | `fetching`, `extracting`, `chunking`, `embedding` or `publishing` while processing; no percentages (ING-07). |
| `failure_code`, `failure_message` | A `FailureCode` and its English fallback text. The interface text comes from the frontend catalog by code. |
| `delivery_state` | The derived job state from `job_recovery.py` (`publish_failed`, `unpublished_stuck`, `queued_stuck`, `processing_stuck`, `failed` and the rest), or null. |
| `can_retry`, `can_replace` | Computed on the server, so the client keeps no rules (ADM-16, ADM-18). |
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

`status` carries `DocumentProcessingStatus`, sent on connect and on every change. A comment line goes out every `KS_SSE_KEEPALIVE_SECONDS` (15). `end` follows a `ready` or `failed` status (`terminal`), or comes after `KS_SSE_MAX_SECONDS` (120) with reason `timeout`, and the client reconnects. There are no event ids and no replay, because a reconnect starts with a fresh `status`. The document list is the fallback when the stream fails.

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
