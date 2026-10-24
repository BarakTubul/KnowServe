# Document lifecycle (submission to searchable)

## Purpose
End-to-end flow for a document: an admin submits it, it is ingested in the background, its status reaches the admin UI, and it becomes visible to permitted employees (My Documents, PDF download, chat search). Use this doc first for any submission/upload task, then the detailed specs it links.

## Flow
1. **Submit** (`frontend/admin-upload.md`): admin fills title, Drive URL, departments -> `POST /admin/docs/`.
2. **Create** (`backend/admin-docs.md`): row inserted with `status=pending` and department access; response `{id}`; Celery task dispatched after commit.
3. **Ingest** (`backend/ingestion.md`): worker downloads PDF to `static/docs/{id}.pdf`, chunks it, writes vectors with `db_doc_id`; publishes `ingestion_complete` or `ingestion_failed` on Redis.
4. **Record + notify**: API-side listener sets `status` (`ingested`/`failed`), invalidates caches, pushes `{doc_id,status,message}` to `WS /ws/documents/{id}` (buffered if the client isn't connected yet).
5. **UI update**: the admin page shows the result and refreshes its list.
6. **Consume** (`backend/documents.md`, `backend/chat.md`): departments with access see the document, can download the PDF once `ingested`, and the chat agent can retrieve its chunks.
7. **Change / remove**: access edit (`PATCH`) or delete (`DELETE`) updates DB, caches, and (on delete) vectors and file.

## Requirements
| ID | Requirement |
|---|---|
| LIFE-01 | A valid submission yields a document in `pending` that is immediately visible in the admin list. |
| LIFE-02 | A pending or failed document is never returned by chat search, and its PDF is not offered for viewing in the UI. |
| LIFE-03 | Every document reaches a terminal status (`ingested` or `failed`) within a bounded time; failures carry a human-readable reason to the admin. |
| LIFE-04 | When ingestion succeeds, the admin sees the new status without reloading (WebSocket), and permitted employees see the document on their next load of My Documents. |
| LIFE-05 | A document is searchable and downloadable only by departments in its access list, and by admin; changing the list takes effect without waiting for cache TTL. |
| LIFE-06 | Deleting a document removes its DB rows, vectors, PDF file and cache entries; it disappears from chat results immediately. |
| LIFE-07 | Retrying or re-ingesting a document does not create duplicate vectors. |

## Required tests
Component-level tests live in the linked specs; these cover the whole flow.
| Req | Level | Scenario | Expected |
|---|---|---|---|
| LIFE-01 | integration | Admin POST (Celery mocked) then GET admin list | doc present, `pending` |
| LIFE-02 | integration | Doc `pending`/`failed` with chunks absent; employee chats / lists | no chunks returned; list shows status; view link hidden (frontend) |
| LIFE-03 | system | Worker with an unreachable URL | doc ends `failed`, WS message has reason, within timeout |
| LIFE-04 | system | Submit fixture PDF, connect WS | receives `ingested`; employee's `/my/access` shows `ingested` |
| LIFE-05 | integration | Grant A then change to B; prime caches first | A loses and B gains access to list, download, search, immediately |
| LIFE-06 | system | Delete ingested doc | row, Chroma entries, file gone; chat no longer finds it |
| LIFE-07 | unit | Run ingest twice for same id | vector count unchanged |
| happy path | system | Admin submits -> status ingested -> employee asks a question about content | answer cites document title |

## Known gaps
Collected from the detailed specs; fix these before relying on LIFE-* guarantees:
- LIFE-03: no timeout/retry for the worker; failure reason isn't forwarded over WS; frontend shows `failed` as pending (`status === 'error'` check).
- LIFE-05: stale caches (`docs:department:*` vs `docs:access:*` key mismatch; old departments not invalidated on PATCH).
- LIFE-06: PDF file isn't removed on delete.
- LIFE-07: no vector cleanup before insert.
- Titles aren't stored in vector metadata, so chat citations read "Unknown Document".
- URL validation (Drive only) and non-empty departments aren't enforced by the backend.
- WebSocket endpoint is unauthenticated.

## Related docs
`../backend/admin-docs.md`, `../backend/ingestion.md`, `../backend/documents.md`, `../backend/chat.md`, `../frontend/admin-upload.md`, `../frontend/my-documents.md`
