# Backend admin document management

**Status:** Target spec (M3 upload; M5 replace/delete/lifecycle hardening). Not implemented: the legacy code takes Google Drive URLs and dispatches Celery.

## Purpose
Admin-only APIs: list all documents, upload a single PDF, import a ZIP with a manifest, change access, replace a version, soft delete, and retry failed jobs. Processing is described in `ingestion.md`; the end-to-end flow is in `../cross-cutting/document-lifecycle.md`.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| ADM-01 | All admin document routes require the Admin: other identities get 403 (SEC-03) and requests without a session get 401. | M3 |
| ADM-02 | The admin list returns every non-deleted document regardless of the Admin's active department (Admin endpoints only, SEC-17), including non-ready and `failed` ones (e.g. `NO_EXTRACTABLE_TEXT`), with title/filename, owner department, allowed departments (ids + names), current revision status and phase, and the last failure reason code and message. | M3 |
| ADM-03 | Single upload: a multipart PDF plus metadata (title, owner department, allowed departments) is validated (ADM-10) and stored in private R2. Then the document, revision, access rows, job and outbox row are written **in one DB transaction** (ING-12), and the response returns the document id with status `queued`. | M3 |
| ADM-04 | Unknown department ids (owner or allowed) are rejected and nothing is created, in either the DB or R2 (any uploaded object is cleaned up). | M3 |
| ADM-05 | At least one authorized (allowed) department is **required** on single upload, ZIP confirmation and access update; an empty list is rejected with 422 (OPEN-16). The backend writes **only** the explicitly submitted `document_department_access` rows and never derives access from `owner_department_id` (SEC-04, SEC-05). Preselecting the owner department is UI behavior (FE-ADM-03). For ZIP/manifest import, a manifest entry must list its allowed departments explicitly; if the import flow offers the owner department as a default for an entry that omits them, the preview shows that default as a planned access row and it becomes binding only through the explicit confirmation (ADM-12, ADM-13). An explicitly empty list is rejected. | M3 |
| ADM-07 | Updating access replaces the allowed departments in one DB update. It takes effect immediately on every path (SEC-09) and **does not re-embed** or reprocess the document. Unknown documents return 404. | M3 |
| ADM-08 | Delete is a **soft delete** that immediately blocks all user paths (SEC-09). Durable asynchronous cleanup later removes R2 objects, chunks and vectors (ING-20). | M5 (M3 basic) |
| ADM-09 | After create, access change or delete, the admin list and the affected users' library reflect the change on the next request. | M3 |
| ADM-10 | Upload validation per SEC-11: PDF signature/type, filename sanitization, and size limits (OPEN-05). Invalid files are rejected with a reason and nothing is stored. | M3 |
| ADM-11 | **ZIP import**: the archive holds PDFs plus `manifest.json`. Validation covers safe paths (no traversal or absolute paths), no symlinks, zip-bomb/ratio limits, file count and size limits, that every manifest entry references a file in the archive, and per-entry metadata and allowed departments. | M3 |
| ADM-12 | ZIP **preview** is read-only: it returns per-file validation results and planned actions, and creates no documents, jobs or objects. | M3 |
| ADM-13 | ZIP **confirmation** is explicit and **idempotent**: repeating the same confirmation does not create duplicates. | M3 |
| ADM-14 | ZIP import supports **partial success**, with per-file results (created / rejected + reason) and a retry for failed files that does not duplicate the successful ones. | M3 |
| ADM-15 | **Replace version** uploads a new revision that is processed privately while the previous ready revision stays served. The new revision is promoted atomically only after its index is completely published; on failure the old revision remains. A document with **no** ready revision (e.g. first upload failed with `NO_EXTRACTABLE_TEXT`, ING-23) can also be given a replacement file, which is then processed as its first ready candidate. There is no end-user revision-history UI. | M5 |
| ADM-16 | A `failed` job (retries exhausted, or a terminal failure such as `NO_EXTRACTABLE_TEXT`) can be retried manually by the Admin (ING-16). | M3 |
| ADM-17 | Admin actions (upload, import confirm, access change, replace, delete, retry) are audit-logged (MON-04). | M3 |

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
| ADM-05 | integration | ZIP manifest entry with `allowed: []`; entry omitting `allowed` | rejected with a reason / preview shows the planned access row explicitly; only confirmation writes it |
| ADM-07 | integration | A,B → B,C | A loses and C gains access on the next request; no new job or embeddings |
| ADM-08 | integration | Soft delete, then user list / bytes / search | absent / 404 / absent; cleanup job enqueued |
| ADM-09 | integration | Create, change access and delete; request the admin list and a permitted user's library after each | each change reflected on the next request |
| ADM-10 | integration | Non-PDF renamed `.pdf`, oversize file, `../` in the filename | rejected with a reason |
| ADM-11 | integration | ZIP with traversal, symlink, bomb, too many files, a manifest missing a file, bad JSON | each rejected with a reason |
| ADM-12 | integration | Preview a valid ZIP | results returned; zero rows and objects created |
| ADM-13 | integration | Confirm twice (same idempotency key) | one set of documents |
| ADM-14 | integration | ZIP with 3 good and 1 bad file; retry the bad one after fixing it | 3 created + 1 rejected; the retry creates exactly 1 more |
| ADM-15 | integration | Replace; the new revision fails / succeeds | old served / new served only after full publish |
| ADM-15 | integration | Document failed with `NO_EXTRACTABLE_TEXT`; Admin uploads a replacement with text | replacement processed; document becomes visible to permitted users only after `ready` |
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
