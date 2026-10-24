# Frontend chat

**Status:** Target spec (M4). Not implemented: the legacy `/chat` page keeps the conversation in React Context and has no persistence, Stop or citations.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-CHAT-01 | A conversation list for the active department with title search, rename and delete. Opening a conversation loads its persisted history (CHAT-14). | M4 |
| FE-CHAT-02 | Enter sends and Shift+Enter inserts a newline. Empty or whitespace input cannot be sent. Input is disabled while streaming, except for the Stop button. | M4 |
| FE-CHAT-03 | Streaming renders the `searching` and `generating` phases and appends token deltas to the assistant message (CHAT-03). | M4 |
| FE-CHAT-05 | Assistant messages render as markdown **without raw HTML**. User messages render as plain text with whitespace preserved. | M4 |
| FE-CHAT-06 | An `error` event or a network failure marks the assistant message as failed with a clear message and re-enables input. | M4 |
| FE-CHAT-07 | The view scrolls to the newest message and shows the phase indicator while waiting. | M4 |
| FE-CHAT-08 | A 401 during a stream follows FE-AUTH-05. | M4 |
| FE-CHAT-09 | Chat state (open conversation, drafts, multi-turn context) resets on logout and on department switch (SEC-10). | M4 |
| FE-CHAT-10 | **Stop** aborts the fetch with AbortController. The partial answer stays visible, marked "stopped" (CHAT-12). | M4 |
| FE-CHAT-11 | Citations render only from the validated `done` payload (CHAT-11), show filename + page, and link to `/documents/:id?page=N`. In history, saved answer text stays visible, while citations to revoked documents show as "source no longer available" with no link or content (CHAT-15, OPEN-11). | M4 |
| FE-CHAT-12 | When AI is unavailable or the budget is exhausted (CHAT-17), the input shows a disabled state with an explanation. History and documents stay usable, and sample conversations, if shown, are labeled. | M4 |
| FE-CHAT-13 | The SSE parser buffers partial lines across network chunks and handles several events per chunk. Malformed events are reported as errors and are never rendered as answer text. | M4 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| FE-CHAT-04 | Client sends the last 20 messages as history | Conversations are now persisted server-side and context is built by the backend (CHAT-02, CHAT-14). |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-CHAT-01 | component | List, search, rename, delete with a mocked API | list updates; delete removes; the search filter works |
| FE-CHAT-02 | component | Enter / Shift+Enter / blank; while streaming | send / newline / no send; input disabled, Stop enabled |
| FE-CHAT-03 | component | Mock stream: searching → generating → 3 tokens → done | phase indicators, then concatenated text |
| FE-CHAT-05 | component | Assistant text with `<script>` and `**bold**` | no script element; bold rendered |
| FE-CHAT-06 | component | `error` event / fetch reject | failed state; input enabled |
| FE-CHAT-07 | component | New message while scrolled up; waiting state | scrolled to the newest; phase indicator visible |
| FE-CHAT-08 | unit | Stream response 401 | FE-AUTH-05 flow triggered |
| FE-CHAT-09 | component | Switch department mid-conversation | conversation closed; list reloaded for the new department |
| FE-CHAT-10 | component | Click Stop | abort signal fired; partial text kept and labeled |
| FE-CHAT-11 | component | `done` with 2 citations; history with a revoked citation | 2 links to `?page=N`; answer text shown, the revoked citation shown as unavailable with no link |
| FE-CHAT-12 | component | Budget-exhausted response | disabled input with an explanation |
| FE-CHAT-13 | unit | Event split across chunks; two events in one chunk; malformed data | correct events; error on malformed; nothing raw in the answer |

## Current implementation (LEGACY, not migrated)
- `src/pages/Chat.jsx` with `ChatContext`. It sends the last 20 messages each turn through `fetchChatStreamResponse` in `src/services/api.js`.
- The parser splits each chunk on `\n` without buffering and appends non-JSON data to the answer.
- There is no Stop, citations, conversation list, persistence, department scoping or reset on logout.

## Known gaps
Every FE-CHAT requirement is unimplemented on the target stack.

## Related docs
`architecture.md`, `my-documents.md`, `../backend/chat.md`, `../cross-cutting/security-and-permissions.md`
