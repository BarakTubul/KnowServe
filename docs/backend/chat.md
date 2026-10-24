# Backend RAG chat and citations

**Status:** Target spec (M4, the first usable MVP). Not implemented: the legacy code is a LlamaIndex FunctionAgent with tools over Chroma, calling `gpt-4o-mini` directly.

## Purpose
Answer questions grounded only in documents the caller's active department may read, with validated page citations, streamed over SSE. Conversations are persisted per identity and department. Quality is measured in `../cross-cutting/evaluation.md`.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| CHAT-01 | A chat endpoint accepts a POST (conversation id or new conversation, plus the user message) and responds with an **SSE stream over the fetch response**. An invalid body returns 422 and no session returns 401. | M4 |
| CHAT-02 | Multi-turn: prior messages **of the same conversation** may be used to rewrite the question, but **every turn performs a new retrieval** under current permissions. Previously retrieved chunks are never assumed to still be authorized. | M4 |
| CHAT-03 | SSE events are `searching`, `generating`, token/delta, `done` (with validated citations) and `error`. The exact payload schema is part of the API contract. | M4 |
| CHAT-04 | The **Authorized Retriever** uses custom SQLAlchemy + pgvector SQL that applies the SEC-07 constraints before ordering and Top-K (SEC-08). Top-K is initially **5**, with a tunable similarity threshold (OPEN-03). There is no reranker or keyword hybrid search in the MVP. | M4 |
| CHAT-05 | With no active department, or no authorized relevant chunks above the threshold, the answer contains no document content and says the information was not found. | M4 |
| CHAT-08 | Answers state only supported organizational facts. They give a partial answer when the evidence is partial, explicitly describe contradictions between documents with each source cited, and admit "not found" when support is insufficient. | M4 |
| CHAT-09 | Authorization comes only from the backend session and active department, never from model output or user text. Documents and prompts are lower trust than system instructions, and the model has no admin tools (SEC-12). | M4 |
| CHAT-10 | Failures during streaming produce an `error` event and close the stream. The stream never hangs, and a partial response is recorded honestly. | M4 |
| CHAT-11 | **Citations are validated by the backend**: they map only to chunks actually retrieved and authorized in this turn (document, revision, page). Invented or unknown source ids are rejected. Final citations are emitted only after validation. | M4 |
| CHAT-12 | **Stop**: the client aborts with AbortController. The backend cancels downstream token generation where possible and records the response as aborted/partial. | M4 |
| CHAT-13 | If access to a cited or retrieved document is revoked during a stream, the backend revalidates (at least before final citations) and stops or omits the affected content (SEC-09, OPEN-11). | M4/M5 |
| CHAT-14 | Conversations and messages are stored per identity **and** department. Users can list, search by title, rename and delete conversations. | M4 |
| CHAT-15 | Displaying conversation history re-checks the citations' current access. Citations and quoted text from revoked or deleted documents are hidden or redacted. | M4/M5 |
| CHAT-16 | LlamaIndex is used as library components. Authorization, lifecycle, orchestration and citations stay in application code. The chat LLM goes through **OpenRouter** (initially an OpenAI-family model; the exact model is OPEN-02). There is no user model selection, automatic fallback or multi-cloud failover. | M4 |
| CHAT-17 | When the budget is exhausted, the kill switch is on (COST-04/05) or the LLM is down, no live generation happens and a clear message is shown. Documents and history stay available, and optional labeled pre-verified samples respect the active department's permissions. | M4 |
| CHAT-18 | Try Demo visitor conversations are isolated per visitor and department and are purged with the visitor (AUTH-16). | M4 |
| CHAT-19 | Every LLM call goes through quota checks and budget reservation first (COST-02, COST-03). | M4 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| CHAT-06 | `list_accessible_documents_tool` agent tool | The target keeps retrieval and authorization in application code (CHAT-16), not model-invoked tools. |
| CHAT-07 | `fetch_document_tool` returning full text | Same as CHAT-06; full-text access goes through the protected viewer (DOC-04). |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| CHAT-01 | integration | Empty message / no session / valid request | 422 / 401 / `text/event-stream` |
| CHAT-02 | integration | Turn 1 cites doc X; X is revoked; turn 2 asks a follow-up | turn 2 retrieval excludes X; no X content |
| CHAT-03 | integration | Fake LLM stream | event order: searching → generating → token… → done |
| CHAT-04 | integration (pgvector) | Forbidden chunks are nearest; threshold set | only permitted chunks, ≤5, above the threshold |
| CHAT-05 | integration | Question with no permitted evidence | "not found" answer; no citations |
| CHAT-08 | eval | Partial / conflicting / negative cases (EVAL-01) | rubric pass |
| CHAT-09 | eval + unit | Prompt injection asks for another department's docs or admin actions | refused; retrieval scope unchanged (hard fail on leak) |
| CHAT-10 | integration | LLM raises mid-stream | `error` event; stream closed; message stored as failed/partial |
| CHAT-11 | unit + integration | Model emits a citation to an unretrieved id and to a forbidden doc | both dropped/rejected; only valid ones in `done` |
| CHAT-12 | integration | Client aborts mid-stream | upstream call cancelled (fake records it); message marked aborted |
| CHAT-13 | integration | Revoke during the stream | affected citations not emitted; stream stops or ends cleanly |
| CHAT-14 | integration | Conversations in dept A and B; rename / search / delete | each department sees only its own; operations work; another user's id returns 404 |
| CHAT-15 | integration | History citing a revoked document | citation hidden/redacted |
| CHAT-16 | unit + review | LLM client configuration | chat calls go to the OpenRouter base URL with the configured model; no request parameter selects the model; no fallback provider configured |
| CHAT-17 | integration | Kill switch on | no LLM call; clear message; library still 200 |
| CHAT-18 | integration | Two visitors | no cross-visitor conversations |
| CHAT-19 | integration | Over quota / budget exhausted | refused before any LLM call |

## Current implementation (LEGACY, not migrated)
- `routers/chat.py` exposes `POST /chat/stream`. The client sends the whole recent history (`pydantic_schemas/chat_schema.py`).
- `services/chat_service.py` passes the last 10 messages as history and yields `token` and `tool` SSE events. There are no `searching`/`generating`/`done`/`error` events, and an exception is raised after the headers are sent.
- `agent/llama_agent.py` is a global singleton FunctionAgent with `gpt-4o-mini` via `llama_index.llms.openai` (direct, not OpenRouter). Its shared Chroma vector memory can mix users' contexts.
- `agent/llama_tools.py` filters by allowed `db_doc_id` in **Chroma** with `similarity_top_k=6`. Titles are missing from the metadata, so citations show "Unknown Document". `fetch_document_tool` always fails, because it reads `user["departments"]`.
- Conversations are not persisted. The `chat_history` table is unused.
- There is no citation validation, stop/abort handling, quotas or kill switch.

## Known gaps
Every CHAT requirement is unimplemented on the target. The legacy code contradicts CHAT-11 (no validation), CHAT-16 (direct OpenAI, agent tools) and the per-user isolation in CHAT-14 (shared agent memory).

## Related docs
`documents.md`, `ingestion.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/evaluation.md`, `../architecture/infrastructure.md`, `../frontend/chat.md`
