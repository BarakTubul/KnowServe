# Backend ingestion pipeline

## Purpose
Turn a newly added document into searchable vectors in the background, then record the outcome and tell any waiting client. Pipeline: Celery task -> Redis pub/sub -> event listener (DB + cache) -> WebSocket.

## Requirements
| ID | Requirement |
|---|---|
| ING-01 | The Celery task `run_ingestion_task(doc_id, source_url, department_ids)` downloads the PDF from Google Drive (gdown) to `static/docs/{doc_id}.pdf`. |
| ING-02 | It splits the text (SentenceSplitter, 1024/100) and inserts nodes into the Chroma-backed LlamaIndex, each with `db_doc_id` metadata (int) and the document title so citations work. |
| ING-03 | On success it publishes `ingestion_complete` with `{doc_id, status: "ingested", departments}`. |
| ING-04 | On any exception it publishes `ingestion_failed` with `{doc_id, status: "failed", error, departments}`; the task does not raise. |
| ING-05 | The event listener updates `documents.status` to the event's status, and does nothing harmful if the document no longer exists. |
| ING-06 | After the DB update, the listener invalidates `docs:all` and `docs:access:{dept}` for each department in the event. |
| ING-07 | The listener sends `{doc_id, status, message}` (plus `error` on failure) to the WebSocket client for that doc. |
| ING-08 | `WS /ws/documents/{doc_id}` accepts a connection; if a status was sent before the client connected, it is delivered on connect. |
| ING-09 | A failed download or unreadable/empty PDF ends as status `failed`, never stuck as `pending`. |
| ING-10 | Re-running ingestion for the same doc must not duplicate vectors. |
| ING-11 | Only an authorized admin may open a document's status socket (see gap). |

## Behavior / API
- Channels: `ingestion_complete`, `ingestion_failed` (Redis pub/sub, published with a sync client from the worker).
- Status machine: `pending` -> `ingested` | `failed`.
- WebSocket payload: `{"doc_id": int, "status": str, "message": str}`; the connection manager keeps one socket per doc and buffers undelivered messages.
- The listener task starts in FastAPI `startup` and uses its own `SessionLocal`.

## Files
`tasks/ingestion_task.py`, `services/ingestion_service.py`, `core/celery_app.py`, `core/redis_client.py` (`publish_sync`, `invalidate_caches`), `core/event_listener.py`, `core/websocket_manager.py`, `routers/ws.py`, `controllers/ws_controller.py`, `core/vector_store.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| ING-01 | unit | `_extract_drive_file_id` with valid `/file/d/<id>/view`, non-Drive, Drive without `/file/d/` | id, None, None |
| ING-01 | unit | `_download_file` with gdown mocked to write bytes / write nothing | path returned / RuntimeError |
| ING-02 | unit | `ingest_from_url_sync` with reader and index mocked | nodes inserted, each with int `db_doc_id` and title metadata |
| ING-03 | unit | Task with service mocked OK; `publish_sync` mocked | published once on `ingestion_complete` with correct payload |
| ING-04 | unit | Service raises | published on `ingestion_failed` with error text; task returns without raising |
| ING-05 | integration | Feed an event for existing doc / missing doc into the listener handler | status updated / no exception |
| ING-06 | integration | Event with departments [1,2] | `invalidate_caches` called with `docs:all`, `docs:access:1`, `docs:access:2` |
| ING-07 | integration | Listener with manager mocked | `send_status` gets status and message; failed includes error |
| ING-08 | integration | `send_status` before connect, then connect with TestClient WebSocket | buffered message received first |
| ING-09 | unit | Empty file / bad PDF in ingest | exception -> ING-04 path |
| ING-10 | unit | Ingest same doc id twice | vectors for that doc replaced, count unchanged |
| ING-11 | integration | WS connect as anonymous / non-admin | rejected (once implemented) |
| ING-* | system | Real worker + Redis + Postgres, small Drive-like fixture | document ends `ingested`; chat search finds its text |

## Known gaps
- ING-02: title is never put in node metadata (`search_documents_tool` reads `metadata['title']`, so citations show "Unknown Document").
- ING-06: listener invalidates `docs:department:{id}` but the cache keys are `docs:access:{id}`, so department lists stay stale up to 15 minutes. Fix the key name.
- ING-07: `send_status` only forwards `status` and `message`; the `error` field the frontend reads is dropped.
- ING-10: no deletion of existing vectors before insert; Celery retries/re-runs duplicate chunks.
- ING-11: the WS endpoint has no auth; any client can subscribe to any doc id. One socket per doc (a second connection replaces the first); `pending_messages` for docs nobody connects to are never cleared (leak).
- Listener and ws manager are in-process: with more than one API instance, a socket may be on a different instance than the one receiving the Redis event.
- No Celery retry/timeouts, so a hung gdown call blocks the worker.
- `ingest_from_url_sync` downloads to `static/docs` even on failure, leaving partial files.

## Related docs
`admin-docs.md`, `../cross-cutting/document-lifecycle.md`, `../frontend/admin-upload.md`
