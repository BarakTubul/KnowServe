# Backend ingestion pipeline

**Status:** Target spec. M0 proves only the signed Worker, one idempotency path and recovery feasibility. Full ingestion is M3 and lifecycle hardening is M5. Not implemented: the legacy pipeline is gdown → Celery → Chroma → Redis pub/sub → WebSocket.

## Purpose
Turn an uploaded revision into page-aware, embedded chunks in pgvector and publish it atomically. Delivery is at-least-once through a transactional outbox and QStash, and the DB holds the status.

## Flow
1. The API transaction writes the document, revision, job and **outbox** row together (ING-12).
2. After commit, the API attempts an immediate publish to **QStash**. A **Cloud Scheduler**-triggered Recovery Dispatcher publishes any outbox rows left pending (ING-13).
3. QStash calls the **Worker** Cloud Run HTTPS service with `{schema_version, job_id}`. The Worker verifies the signature and job eligibility (ING-14) and atomically claims the job with a lease (ING-15).
4. `ProcessDocument(job_id)` runs these stages: secure read from R2 → PyMuPDF4LLM per-page extraction → SentenceSplitter chunks bounded by page → OpenAI embeddings → pgvector write → atomic publish (ING-17).
5. The DB status moves `queued` → `processing` (with a phase) → `ready` or `failed`, and an admin SSE stream reports it (ING-05, ING-07).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| ING-02 | Extraction uses PyMuPDF4LLM per page. Chunking uses LlamaIndex SentenceSplitter, initially **512 tokens with 64 overlap** (tunable, OPEN-03). Chunks **never span pages** in the MVP. Each chunk stores the document id, revision id and page number. | M3 |
| ING-05 | The DB is the source of truth for status: `queued`, `processing` plus an explicit phase, `ready` or `failed`, with a failure reason. | M3 |
| ING-07 | Admin status updates are delivered over **SSE**, derived from DB state. Meaningful stages are shown, with no invented progress percentages. | M3 |
| ING-09 | Every job reaches `ready` or `failed` (with a human-readable reason), never stays stuck in `queued`/`processing`. This covers download/read errors, invalid or unreadable PDFs, and PDFs with no extractable text (ING-23). The failure is recorded as a stable reason code plus a message. | M3 |
| ING-10 | Retries and duplicate deliveries never publish a partial index or create duplicate final chunks for a revision. | M0 (minimal) / M3 |
| ING-11 | The status SSE stream is Admin-only (SEC-03) and scoped to the requested document. | M3 |
| ING-12 | **Transactional outbox**: the document, revision, job and outbox rows are committed in a single PostgreSQL transaction. | M0 (feasibility) / M3 |
| ING-13 | After commit the API attempts an immediate QStash publish. A Cloud Scheduler-triggered **Recovery Dispatcher** publishes pending outbox rows. Both paths coordinate through DB claims and leases. No single-process fire-and-forget delivery is relied on. | M0 (feasibility) / M3 |
| ING-14 | The Worker verifies the QStash signature, then checks that the job exists and is eligible, before doing any work (SEC-14). | M0 |
| ING-15 | Delivery is **at-least-once**. An atomic DB claim, leases, idempotency and checkpoints make duplicates safe. Docs and code must not claim exactly-once. | M0 (minimal) / M3 |
| ING-16 | Retries use bounded backoff with a cap. Once exhausted, the job is `failed` and can be retried manually (ADM-16). | M3 |
| ING-17 | A single `ProcessDocument(job_id)` orchestrates the stages (secure R2 read, extraction, chunking, embedding, vector write, atomic publish). It is split into more jobs only for demonstrated necessity. | M3 |
| ING-18 | Embeddings use OpenAI `text-embedding-3-small` directly. The embedding model/version and the index identity are recorded per revision. Changing the model requires rebuilding and revalidating the index, and vector spaces are never mixed. | M3 |
| ING-19 | After a Worker crash, an expired lease lets the job be reclaimed and resumed or retried from a checkpoint. | M3 |
| ING-20 | Durable asynchronous cleanup eventually removes objects, chunks and vectors of soft-deleted documents and orphaned revisions. | M5 |
| ING-21 | The job envelope is minimal and versioned: `{schema_version, job_id}`. All other data is read from the DB. | M0 |
| ING-22 | Worker processing is independent of the HTTP request lifecycle, so it can move to Cloud Run Jobs if limits require it. The Cloud Run request timeout vs job size is measured in the M0 spike (INFRA-03). | M0/M3 |
| ING-23 | **No extractable text** (OPEN-17): if PyMuPDF4LLM yields no usable text, the revision ends `failed` with reason `NO_EXTRACTABLE_TEXT`, since retrying cannot help. The document and its stored file are **retained** for Admin inspection (ADM-02), and are never published to the library, the regular viewer or retrieval (SEC-07). The Admin may replace the file and retry (ADM-15, ADM-16). There is no OCR in the MVP and no `view_only` status. | M3 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| ING-01 | Download the PDF from Google Drive with gdown | Drive/gdown removed; the source is an R2 object (ADM-03). |
| ING-03 | Publish `ingestion_complete` on Redis | Redis pub/sub is not the status truth (STACK-X); replaced by ING-05. |
| ING-04 | Publish `ingestion_failed` on Redis | Same as ING-03; replaced by ING-05 and ING-09. |
| ING-06 | Listener invalidates Redis caches | No Redis; SEC-10 and DOC-10. |
| ING-08 | WebSocket `/ws/documents/{id}` with buffering | WebSocket is not in the target; replaced by ING-07 (SSE). |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| ING-02 | unit | Two-page PDF fixture | no chunk spans pages; metadata has doc, revision and page |
| ING-05 | integration | Run a job through success and failure (providers faked) | DB status transitions and the reason are recorded |
| ING-07 | integration | Subscribe to SSE during a job | stage events match the DB phases; terminal event; no percentages |
| ING-09 | integration | Corrupt PDF, text-less PDF, embedding provider error | `failed` + reason; never left `processing` |
| ING-10 | integration | The same job delivered twice concurrently | one claim executes; final chunk count = single run |
| ING-11 | integration | SSE as a non-admin / anonymous | 403 / 401 |
| ING-12 | integration | Fault injected after the outbox insert but before commit | no document, job or outbox row |
| ING-13 | integration | Immediate publish "crashes" after commit; run the recovery dispatcher | job published exactly once by recovery (M0-AC10) |
| ING-14 | integration | Missing signature / bad signature / valid signature + unknown or ineligible job | 401/403 / 401/403 / no-op response; no processing (M0-AC04) |
| ING-15 | integration | Redelivery after success | no re-execution; 2xx ack (M0-AC05) |
| ING-16 | integration | The provider fails N times | backoff respected; `failed` after the cap; manual retry works |
| ING-17 | integration | Happy path with faked R2/embeddings on a two-page fixture | stages run in order; phase recorded per stage; revision `ready` with the expected chunks |
| ING-18 | unit | Revision metadata | model and index identity stored; a query across a mismatched index identity is refused |
| ING-19 | integration | Worker killed mid-job; lease expires | another delivery reclaims it and completes without duplicates |
| ING-20 | integration | Soft-delete, then run cleanup | object, chunks and vectors removed; user paths were already blocked |
| ING-23 | integration | Image-only PDF fixture | `failed` + `NO_EXTRACTABLE_TEXT` with no backoff retries; R2 object and document kept; no chunks; absent from library/retrieval, viewer 404; listed in the Admin list |
| ING-22 | spike report | Measure Cloud Run request timeout vs the processing time of the largest allowed PDF | documented limit and decision (M0-AC09) |
| ING-21 | unit | Envelope schema validation | extra or missing fields rejected; unknown version rejected |

## Current implementation (LEGACY, not migrated)
- `services/docs_service.add_document` calls `tasks/ingestion_task.run_ingestion_task.delay(...)` (**Celery**/**Redis** broker) after commit. There is no outbox.
- `services/ingestion_service.py` downloads with **gdown** from a Google Drive link to `app/static/docs/{id}.pdf`. It reads with PyMuPDFReader, uses `SentenceSplitter(1024, 100)` with no page boundary, and inserts into **Chroma** with `db_doc_id` only (no title, revision or page).
- The task publishes `ingestion_complete`/`ingestion_failed` on **Redis pub/sub**.
- `core/event_listener.py` updates `documents.status` and invalidates the wrong cache keys (`docs:department:*`).
- `core/websocket_manager.py` pushes to an **unauthenticated WebSocket** that keeps one socket per document and leaks buffered messages.
- There is no retry, lease, idempotency or duplicate-chunk protection, and no revision model.

## Known gaps
Every ING requirement is unimplemented. The legacy pipeline contradicts ING-05 (Redis holds the status), ING-07/ING-11 (WebSocket, no auth), ING-10 (duplicates possible) and ING-12/ING-13 (fire-and-forget).

## Related docs
`admin-docs.md`, `documents.md`, `../cross-cutting/document-lifecycle.md`, `../cross-cutting/security-and-permissions.md`, `../architecture/infrastructure.md`, `../milestones/M0/plan.md`, `../frontend/admin-upload.md`
