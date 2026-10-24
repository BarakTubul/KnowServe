# Document lifecycle (submission → ready → change → delete)

**Status:** Target spec (M2/M3 core, M5 replace/delete hardening). Not implemented: the legacy flow is Drive URL → Celery → Chroma → Redis → WebSocket. Read this first for any submission, upload or ingestion task, then the linked detailed specs.

## Flow
1. **Submit** (`../frontend/admin-upload.md`): the Admin uploads a single PDF with metadata, or a ZIP + `manifest.json` through preview and explicit confirm (ADM-03, ADM-11 to ADM-14).
2. **Store and record** (`../backend/admin-docs.md`): the bytes go to private R2. The document, revision, access rows, job and outbox row are written in one transaction (ING-12), and the status is `queued`.
3. **Dispatch** (`../backend/ingestion.md`): an immediate QStash publish after commit, plus the Cloud Scheduler recovery dispatcher (ING-13). Delivery is at-least-once.
4. **Process**: the Worker verifies the signature and job (ING-14), claims it with a lease (ING-15), and runs `ProcessDocument`: extract per page, chunk 512/64 within pages, embed, write pgvector, then atomically publish (ING-17). The status becomes `processing` (with a phase), then `ready` or `failed`.
5. **Observe**: the Admin UI follows the DB-derived SSE status (ING-07).
6. **Consume** (`../backend/documents.md`, `../backend/chat.md`): departments with access rows see the ready, current revision in the library and viewer and can retrieve it in chat (SEC-07, SEC-08).
7. **Change**: an access change is an immediate DB update with no re-embedding (ADM-07). Replace version is processed privately and promoted atomically (ADM-15). Soft delete blocks access immediately and is followed by async cleanup (ADM-08, ING-20).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| LIFE-01 | A valid submission yields a `queued` document that is immediately visible in the Admin list. | M3 |
| LIFE-02 | A document without a ready current revision, and any candidate revision that is not yet promoted, is never visible to users, in retrieval or in citations (SEC-07). | M2/M3 |
| LIFE-03 | Every job reaches `ready` or `failed` with bounded retries, the failure reason is visible to the Admin, and manual retry is possible (ING-09, ING-16, ADM-16). | M3 |
| LIFE-04 | The Admin sees stage changes without reloading (SSE). Permitted users see the document on their next library request once it is `ready`. | M3 |
| LIFE-05 | Access changes take effect immediately on every path without re-embedding (ADM-07, SEC-09). | M3 |
| LIFE-06 | Soft delete blocks every user path immediately. Objects, chunks and vectors are cleaned up asynchronously and durably (ADM-08, ING-20). | M5 (basic M3) |
| LIFE-07 | Retries and duplicate deliveries never duplicate chunks or publish a partial index (ING-10). | M0/M3 |
| LIFE-08 | Replacement keeps the old ready revision served until the new one is fully published, and keeps the old one if the new one fails (ADM-15). | M5 |
| LIFE-09 | An outbox row whose immediate publish was lost is published by the recovery dispatcher (ING-13). | M0/M3 |

## Required tests (end-to-end; component tests are in the linked specs)
| Req | Level | Scenario | Expected |
|---|---|---|---|
| LIFE-01 | integration | Admin upload, then admin list | doc present, `queued` |
| LIFE-02 | integration | Doc in processing/failed; user lists, views, chats | absent / 404 / no chunks |
| LIFE-03 | integration | Provider always fails | `failed` + reason after the cap; manual retry re-queues |
| LIFE-04 | e2e | Upload a fixture on the local stack | the Admin UI shows the stages then `ready`; a user in a permitted department sees it |
| LIFE-05 | integration | Change access A→B | A loses and B gains access to the list, bytes and retrieval immediately; no job created |
| LIFE-06 | integration | Soft delete a ready doc, then run cleanup | blocked immediately; storage and vectors removed later |
| LIFE-07 | integration | Duplicate delivery | chunk count unchanged |
| LIFE-08 | integration | Replace with a failing / succeeding revision | old served / new served after publish only |
| LIFE-09 | integration | Lose the immediate publish; run recovery | job processed once |
| happy path | e2e | Upload → ready → a user asks about the content | answer cites filename + page; the citation opens the viewer at that page |

## Current implementation (LEGACY, not migrated)
The Admin posts a Google Drive URL, and the document is created `pending`. `Celery.delay` runs gdown → Chroma, and the result goes over Redis pub/sub to the API listener, which updates the status and sends it over an unauthenticated WebSocket. Legacy defects, all superseded by the target:
- stale caches from a key mismatch
- the PDF file is not removed on delete
- duplicate vectors on re-run
- no titles in the vector metadata
- the frontend shows `failed` as pending

## Known gaps
Every LIFE requirement is unimplemented on the target stack.

## Related docs
`../backend/admin-docs.md`, `../backend/ingestion.md`, `../backend/documents.md`, `../backend/chat.md`, `security-and-permissions.md`, `../frontend/admin-upload.md`, `../frontend/my-documents.md`
