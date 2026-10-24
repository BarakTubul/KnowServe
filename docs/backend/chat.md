# Backend chat

## Purpose
Authenticated users ask questions; a LlamaIndex FunctionAgent (gpt-4o-mini) answers by calling tools that search only the documents the user's department may access. Responses stream as server-sent events.

## Requirements
| ID | Requirement |
|---|---|
| CHAT-01 | `POST /chat/stream` with `{messages: [{role, content}]}` (>= 1 message, non-empty content) streams `text/event-stream`; invalid body returns 422, no token 401. |
| CHAT-02 | The last message is the user turn; up to the 10 messages before it are passed as history. |
| CHAT-03 | Tokens stream as `data: {"type":"token","content":...}`; tool calls as `data: {"type":"tool","tool":...}`. |
| CHAT-04 | `search_documents_tool` only retrieves chunks whose `db_doc_id` is in the set of documents the caller's department can access. |
| CHAT-05 | A user with no department gets "No departments are associated with your account." and no document content. |
| CHAT-06 | `list_accessible_documents_tool` returns only `{id, title}` of accessible documents. |
| CHAT-07 | `fetch_document_tool` returns full text only for a permitted document, otherwise a refusal message. |
| CHAT-08 | The agent must search before answering company questions and cite the document title; if nothing relevant is found it says it can only give general information. |
| CHAT-09 | Authorization is determined by the backend (JWT department), never by the model or user-supplied text. |
| CHAT-10 | An agent/tool failure during streaming surfaces to the client as an error, not a hung stream. |

## Behavior / API
- Context store per run: `user_dept_ids` (`[department_id]`) and `user_data` (JWT payload).
- Vector filter: `MetadataFilter(key="db_doc_id", operator=IN, value=allowed_ids)`, `similarity_top_k=6`.
- Agent singleton in `agent/llama_agent.py`; memory uses a Chroma `chat_history` collection plus a 3000-token buffer.

## Files
`routers/chat.py`, `services/chat_service.py`, `pydantic_schemas/chat_schema.py`, `agent/llama_agent.py`, `agent/llama_tools.py`, `core/vector_store.py`, `core/chroma_client.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| CHAT-01 | integration | Empty `messages`, empty content, no token | 422, 422, 401 |
| CHAT-02 | unit | 15 messages | history = messages[-11:-1], user_msg = last |
| CHAT-03 | unit | Fake agent events (AgentStream, ToolCallResult) | SSE lines with correct type/content shape |
| CHAT-04 | unit | Dept A allowed docs {1,2}; index mocked | filter value is exactly [1,2]; docs of other depts never queried |
| CHAT-05 | unit | `user_dept_ids=[]` | refusal string, no index call |
| CHAT-06 | unit | Docs with extra fields | only id and title returned, deduplicated |
| CHAT-07 | unit | Allowed / disallowed doc | content / refusal |
| CHAT-08 | system | Real-ish run with a fixture doc | answer cites title; no-hit question yields the general-info disclaimer (LLM mocked or marked slow) |
| CHAT-09 | unit | Prompt-injection text asking for another department's docs | tools still use JWT department only |
| CHAT-10 | integration | Agent raises mid-stream | client sees an error event or closed stream with error status |

## Known gaps
- CHAT-07 is broken today: `DocsService.get_document_text` reads `user["departments"]`, which the JWT never contains, so every fetch fails with "no permission".
- CHAT-03: the service yields no `error`/`done` events; on exception it re-raises inside the generator after headers are sent (CHAT-10 not met).
- Search results report `Unknown Document` titles because ingestion doesn't store a title (see `ingestion.md`).
- `ChatHistory` table exists but isn't written; `clear_chat_history` resets the single global agent memory (shared across all users), and long-term vector memory (`chat_history` collection) is shared across users, which can leak one user's conversation context to another.
- `get_agent()` singleton is shared across users; per-user memory isolation is missing.
- Debug `print` of tool outputs may log document content.
- `chat_service = ChatService()` instance in the router is unused.

## Related docs
`documents.md`, `ingestion.md`, `../frontend/chat.md`
