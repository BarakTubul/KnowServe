# Backend admin document management

**Status:** Target spec (M3 upload and failed-document file replacement; M5 ready-document replacement/delete/lifecycle hardening). Not implemented: the legacy code takes Google Drive URLs and dispatches Celery.

## Purpose
Admin-only APIs: list all documents, upload a single PDF, import a ZIP with a manifest, change access, replace the file of a failed document (M3) or a ready version (M5), soft delete, and retry failed jobs. Processing is described in `ingestion.md`; the end-to-end flow is in `../cross-cutting/document-lifecycle.md`.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| ADM-01 | All admin document routes require the Admin: other identities get 403 (SEC-03) and requests without a session get 401. | M3 |
| ADM-02 | The admin list returns every non-deleted document regardless of the Admin's active department (Admin endpoints only, SEC-17), including non-ready and `failed` ones (e.g. `NO_EXTRACTABLE_TEXT`), with title/filename, owner department, allowed departments (ids + names), current revision status and phase, and the last failure reason code and message. | M3 |
| ADM-03 | Single upload: a multipart PDF plus metadata (title, owner department, allowed departments) is validated (ADM-10) and stored in private R2. Then the document, revision, access rows, job and outbox row are written **in one DB transaction** (ING-12), and the response returns the document id with status `queued`. | M3 |
| ADM-04 | Unknown department ids (owner or allowed) are rejected and nothing is created, in either the DB or R2 (any uploaded object is cleaned up). | M3 |
| ADM-05 | At least one authorized (allowed) department is **required** on single upload, ZIP confirmation and access update; an empty list is rejected with 422 (OPEN-16). The backend writes **only** the explicitly submitted `document_department_access` rows and never derives access from `owner_department_id` (SEC-04, SEC-05). **Single-PDF upload:** preselecting the owner department is UI behavior only (FE-ADM-03); the Admin may change it, and the submitted list must be nonempty. **ZIP/manifest import (intentionally different):** there is **no default**. Every manifest entry must carry an explicit, nonempty `allowed_departments` list of known department ids; the backend never infers access from the entry's `owner_department` (ADM-11). | M3 |
| ADM-07 | Updating access replaces the allowed departments in one DB update. It takes effect immediately on every path (SEC-09) and **does not re-embed** or reprocess the document. Unknown documents return 404. | M3 |
| ADM-08 | Delete is a **soft delete** that immediately blocks all user paths (SEC-09). Durable asynchronous cleanup later removes R2 objects, chunks and vectors (ING-20). | M5 (M3 basic) |
| ADM-09 | After create, access change or delete, the admin list and the affected users' library reflect the change on the next request. | M3 |
| ADM-10 | Upload validation per SEC-11: PDF signature/type, filename sanitization, and size limits (OPEN-05). Invalid files are rejected with a reason and nothing is stored. | M3 |
| ADM-11 | **ZIP import**: the archive holds PDFs plus `manifest.json`. Validation covers safe paths (no traversal or absolute paths), no symlinks, zip-bomb/ratio limits, file count and size limits, that every manifest entry references a file in the archive, and per-entry metadata. Per entry, `allowed_departments` is **required**: a missing field, an empty list, or any unknown/invalid department id makes the entry invalid (OPEN-16 follow-up). The backend applies these checks itself at preview **and** again at confirmation; the frontend preview is never trusted. | M3 |
| ADM-12 | ZIP **preview** is read-only: it returns per-entry validation results and planned actions, and creates no documents, jobs or objects. Each invalid entry is identified (filename / manifest index) with an actionable error code and message (e.g. `ALLOWED_DEPARTMENTS_MISSING`, `ALLOWED_DEPARTMENTS_EMPTY`, `UNKNOWN_DEPARTMENT` with the offending id). Invalid entries are never imported; valid entries proceed only through the explicit confirmation (ADM-13, ADM-14), and no ingestion job is created before it. | M3 |
| ADM-13 | ZIP **confirmation** is explicit and **idempotent**: repeating the same confirmation does not create duplicates. | M3 |
| ADM-14 | ZIP import supports **partial success**, with per-file results (created / rejected + reason) and a retry for failed files that does not duplicate the successful ones. | M3 |
| ADM-15 | **Replace version of a ready document** (general versioning): uploads a new revision that is processed privately while the previous ready revision stays served. The new revision is promoted atomically only after its index is completely published; on failure the old revision remains. There is no end-user revision-history UI. Not available before M5; failed-document recovery is ADM-18. | M5 |
| ADM-16 | A `failed` job (retries exhausted, or a terminal failure such as `NO_EXTRACTABLE_TEXT`) can be retried manually by the Admin (ING-16). | M3 |
| ADM-17 | Admin actions (upload, import confirm, access change, replace, delete, retry) are audit-logged (MON-04). | M3 |
| ADM-18 | **Failed-document file replacement** (limited recovery, not versioning). The Admin may upload a replacement PDF for an existing document only while it has **no current (ready) revision** and its latest revision is `failed` with no active job. Rules: (1) the `document_id`, `owner_department_id` and `document_department_access` rows are unchanged; (2) the file passes the same validation as ADM-10/SEC-11, and an invalid file is rejected with 422 leaving the document `failed` as before; (3) the replacement is stored under a new private R2 key and recorded as a new revision row with a new job and outbox row in one transaction (ING-12), so the failed revision's chunks or partial artifacts can never become current or retrievable (SEC-07) and are cleaned up asynchronously (ING-20); (4) the state change `failed → queued` is an atomic conditional update, so concurrent or duplicate requests start at most one attempt, and a repeated request with the same idempotency key returns the original result; (5) worker crashes and redeliveries follow ING-15/ING-19; (6) the document stays out of the library, viewer and retrieval until the new revision is `ready`, which then becomes current through the normal first-ready path; (7) if the attempt fails, the document is `failed` again with an actionable reason and can be replaced or retried again (ADM-16). A request for a document that is `ready`, `queued` or `processing` returns 409 with a stable error code fixed in the M3 API contract; an unknown or soft-deleted id returns 404. | M3 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| ADM-06 | `source_url` must be a Google Drive file link | Drive/gdown ingestion was removed (STACK-X); replaced by ADM-10 and ADM-11. |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| ADM-01 | integration | Each route as visitor / registered user / anonymous | 403 / 403 / 401 |
| ADM-02 | integration | Docs in queued, processing, ready and failed states | all listed with status, phase and reason |
| ADM-03 | integration | Valid upload (R2 and QStash faked) | 200 `{id}`; document+revision+access+job+outbox rows exist; object stored |
| ADM-03 | integration | DB failure after the R2 put | no DB rows; orphan object cleaned or tracked for cleanup |
| ADM-04 | integration | Unknown department id | 4xx; no rows; no object |
| ADM-05 | integration | Single upload with an empty allowed list; access update to `[]` | 422; nothing created / access unchanged |
| ADM-05 | integration | Upload with owner = A and allowed = [B] | access rows exactly {B}; a user active in A cannot see the doc (SEC-04) |
| ADM-05 | integration | Single upload with owner = A and allowed = [A] (the UI default) | accepted; access rows {A} written explicitly, not derived from the owner |
| ADM-07 | integration | A,B → B,C | A loses and C gains access on the next request; no new job or embeddings |
| ADM-08 | integration | Soft delete, then user list / bytes / search | absent / 404 / absent; cleanup job enqueued |
| ADM-09 | integration | Create, change access and delete; request the admin list and a permitted user's library after each | each change reflected on the next request |
| ADM-10 | integration | Non-PDF renamed `.pdf`, oversize file, `../` in the filename | rejected with a reason |
| ADM-11 | integration | ZIP with traversal, symlink, bomb, too many files, a manifest missing a file, bad JSON | each rejected with a reason |
| ADM-11 | integration | Manifest entries: `allowed_departments` missing / `[]` / containing an unknown id / only `owner_department` set / valid | invalid ×4 with `ALLOWED_DEPARTMENTS_MISSING` / `_EMPTY` / `UNKNOWN_DEPARTMENT` / `_MISSING`; valid entry accepted; no access row ever derived from the owner |
| ADM-11 | integration | Confirmation request that includes an entry the preview marked invalid (tampered client) | backend re-validates and rejects that entry; it is not imported and no job is created for it |
| ADM-12 | integration | Preview a valid ZIP; preview a ZIP with 2 valid and 1 invalid-permission entry | results returned, zero rows/objects/jobs created; the invalid entry is identified with its error code and the 2 valid ones listed as planned |
| ADM-13 | integration | Confirm twice (same idempotency key) | one set of documents |
| ADM-14 | integration | ZIP with 3 good and 1 bad file; retry the bad one after fixing it | 3 created + 1 rejected; the retry creates exactly 1 more |
| ADM-15 | integration | Replace; the new revision fails / succeeds | old served / new served only after full publish |
| ADM-18 | integration | Document failed with `NO_EXTRACTABLE_TEXT`; Admin uploads a replacement with text | same `document_id`, owner and access rows; new revision + job; invisible to users while `queued`/`processing`; visible to permitted users only after `ready` |
| ADM-18 | integration | Replacement request for a `ready`, a `queued` and a `processing` document; for an unknown id | 409 ×3 with the contract error code; 404; nothing changed |
| ADM-18 | integration | Replacement with a non-PDF / oversize file | 422; document stays `failed`; no new revision, job or object |
| ADM-18 | integration | Two concurrent replacement requests; a repeated request with the same idempotency key | exactly one new attempt; the repeat returns the first result |
| ADM-18 | integration | Previous failed revision had partial chunks; replacement succeeds | old partial chunks never retrieved; only the new revision is current; cleanup removes the old artifacts |
| ADM-18 | integration | Replacement also fails; Admin replaces again | `failed` with an actionable reason; second replacement accepted |
| ADM-18 | integration | Worker killed during the replacement job | lease expiry and redelivery complete it without duplicate chunks (ING-19) |
| ADM-16 | integration | Exhausted job, then manual retry | job re-queued; eventually ready |
| ADM-17 | integration | Each admin action | audit entry with the admin id and target, without file content |

## Current implementation (LEGACY, not migrated)
- `routers/admin/docs.py` exposes `GET /admin/docs/`, `POST /` (JSON `{title, source_url, allowed_department_ids}`), `PATCH /{id}/access` and `DELETE /{id}`. The controller is `controllers/admin_docs_controller.py` and the logic is in `services/docs_service.py`.
- Create inserts `status="pending"`, then calls `run_ingestion_task.delay(...)` after commit. This is fire-and-forget: if Redis is down, the document stays `pending` forever.
- There is no file upload and no ZIP import. The only source is a Google Drive URL (no validation).
- PATCH invalidates only the new departments' Redis keys.
- Delete is a hard delete plus a Chroma delete after commit. The PDF file is not removed.
- There is no owner department, revisions, soft delete, retry or audit log.

## Known gaps
Every ADM requirement is unimplemented on the target. ADM-04 (reject unknown departments) is the only one partially present in the legacy code.

## Related docs
`ingestion.md`, `documents.md`, `../cross-cutting/document-lifecycle.md`, `../cross-cutting/security-and-permissions.md`, `../frontend/admin-upload.md`
