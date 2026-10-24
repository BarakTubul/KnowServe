# Frontend chat

## Purpose
`/chat` page: send questions to the backend, show the streamed answer as markdown.

## Requirements
| ID | Requirement |
|---|---|
| FE-CHAT-01 | The conversation starts with a welcome system message and lives in `ChatContext` so it survives navigation between pages. |
| FE-CHAT-02 | Enter sends, Shift+Enter inserts a newline; empty/whitespace input cannot be sent; input and send button are disabled while a response is streaming. |
| FE-CHAT-03 | Sending adds the user message and an empty assistant message, then appends each streamed `token` to that assistant message. |
| FE-CHAT-04 | At most the last 20 messages (excluding the welcome message) are sent as `{role, content}`, mapping `user` -> `user`, anything else -> `assistant`. |
| FE-CHAT-05 | Assistant messages render as markdown; user messages as plain text with whitespace preserved. |
| FE-CHAT-06 | On a stream error the assistant message shows "Error: Could not reach the AI service." and input re-enables. |
| FE-CHAT-07 | The view scrolls to the newest message and shows a loading indicator while waiting. |
| FE-CHAT-08 | A 401 during the stream logs the user out (`auth:unauthorized`). |
| FE-CHAT-09 | Chat state is cleared on logout so the next user doesn't see it (see gap). |

## Behavior / API
`fetchChatStreamResponse(messages, onChunk, onError, onComplete)` POSTs to `/api/chat/stream`, reads SSE `data:` lines, calls `onChunk` for `type: "token"`, logs `tool` events, and calls `onComplete` when the stream ends.

## Files
`src/pages/Chat.jsx`, `src/pages/Chat.css`, `src/context/ChatContext.jsx`, `src/services/api.js` (`fetchChatStreamResponse`)

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-CHAT-02 | component | Type text, press Enter / Shift+Enter / blank | sent / newline / not sent; disabled while loading |
| FE-CHAT-03 | component | Mock stream of 3 tokens | assistant bubble shows concatenated text |
| FE-CHAT-04 | unit | 30 prior messages | request body has 20 messages, welcome excluded, roles mapped |
| FE-CHAT-05 | component | Assistant text with `**bold**` | rendered `<strong>` |
| FE-CHAT-06 | component | Fetch rejects | error text shown, input enabled |
| FE-CHAT-08 | unit | Stream responds 401 | `auth:unauthorized` dispatched |
| FE-CHAT-09 | component | Logout then login as other user | conversation reset |
| stream parser | unit | Chunk split mid-line / two events in one chunk / non-JSON data | tokens extracted correctly |

## Known gaps
- FE-CHAT-09 not met: `ChatProvider` sits outside auth state and `clearChat` is never called on logout.
- Stream parser splits each network chunk on `\n` without buffering partial lines, so an SSE event cut across chunks is dropped or printed raw.
- Non-JSON `data:` lines are appended to the answer verbatim.
- Errors from the server mid-stream (see `backend/chat.md` CHAT-10) have no UI handling; no way to stop/cancel a response or clear the conversation.

## Related docs
`architecture.md`, `../backend/chat.md`
