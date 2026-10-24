# Frontend admin document management

**Status:** Target spec (M3 upload, ZIP, status and failed-file replacement; M5 ready-document replacement/delete hardening). Not implemented: the legacy `/admin/upload` page posts Google Drive URLs and listens on a WebSocket.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-ADM-01 | Admin pages are shown only to the Admin (UX only, SEC-15). A non-Admin hitting the route sees a "not available" view, and the API also returns 403. | M3 |
| FE-ADM-02 | The admin list shows every document with status and phase, owner department, allowed departments and last failure reason, with a title search. | M3 |
| FE-ADM-03 | The single-upload form (RHF+Zod) takes a PDF file, title, owner department and allowed departments. Choosing the owner department **preselects** it as an allowed department; the Admin may deselect it or pick others before confirming. Submitting requires at least one allowed department (ADM-05, OPEN-16). This default applies to single upload only; ZIP import has none (FE-ADM-11). The form states that ownership alone does not grant access. Departments come from the API. | M3 |
| FE-ADM-04 | Submit sends multipart to the upload endpoint. The submit button is disabled while the upload is in flight. | M3 |
| FE-ADM-05 | On success the form resets, the document appears as `queued`, and the page subscribes to its SSE status stream (ING-07). | M3 |
| FE-ADM-06 | Status events update the stage display. `ready` shows success, and `failed` shows the server's reason (e.g. `NO_EXTRACTABLE_TEXT`: "no extractable text; OCR is not supported, replace the file") with a Retry action (ADM-16) and a **Replace file** action (FE-ADM-13). There are no invented progress percentages. Closing the page and reopening it recovers the state from the list (the DB is the truth). | M3 |
| FE-ADM-07 | Edit access opens a department checklist pre-filled from the document. Saving requires at least one department and refreshes the list. The UI notes that no reprocessing happens. | M3 |
| FE-ADM-08 | Delete asks for confirmation (an accessible dialog, not `window.confirm`), then soft-deletes and refreshes the list. Cancel does nothing. | M3/M5 |
| FE-ADM-09 | API errors show the server message, and the form keeps its values on failure. | M3 |
| FE-ADM-10 | The status badge distinguishes `queued`, `processing` (with its phase), `ready` and `failed`. | M3 |
| FE-ADM-11 | **ZIP import**: upload a ZIP to get a read-only **preview** with per-file validation. **Confirm** is an explicit action (double-click safe). Per-file results follow, with retry for failed files (ADM-11 to ADM-14). The preview shows each entry's explicit `allowed_departments`. Entries with a missing, empty or unknown `allowed_departments` are shown as invalid with the server's actionable message and are excluded from confirmation; there is **no owner-department default for ZIP** (unlike single upload, FE-ADM-03; ADM-05, ADM-11, ADM-12). Confirm imports only the valid entries. | M3 |
| FE-ADM-12 | **Replace version of a ready document**: upload a new PDF for an existing ready document. The UI shows that the current version stays live until the new one is ready, and the outcome on failure (ADM-15). Not offered before M5. | M5 |
| FE-ADM-13 | **Replace file of a failed document** (M3 recovery, ADM-18): shown only for documents in `failed` state with no current revision. The Admin picks a PDF; the dialog states that the document ID, owner and permissions are kept and that the document stays unavailable to users until processing succeeds. The action is disabled while the request is in flight; a 409 or 422 shows the server message and the row keeps its `failed` state. On success the row shows `queued` and follows the SSE status (FE-ADM-05/06). | M3 |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-ADM-01 | component | Render as a registered user | not-available view |
| FE-ADM-02 | component | Mocked list with 4 statuses; search | all rendered; the filter works |
| FE-ADM-03 | component | No file / no departments / non-PDF file | inline errors; no API call |
| FE-ADM-03 | component | Pick owner A; then deselect A and pick B; submit | A preselected; body sends allowed `[B]` only |
| FE-ADM-04 | component | Valid submit | multipart body correct; button disabled during the request |
| FE-ADM-05 | component | Success response | form reset; row `queued`; SSE subscription opened |
| FE-ADM-06 | component | Fake SSE emits phases, then failed (`NO_EXTRACTABLE_TEXT`) | stage text updates; reason + Retry shown |
| FE-ADM-07 | component | Edit [1,3] → [1,2] | PATCH body `[1,2]`; list refetched |
| FE-ADM-08 | component | Confirm / cancel | DELETE called / not called |
| FE-ADM-09 | component | 422 / 400 response | message shown; inputs kept |
| FE-ADM-10 | component | Each status | distinct badge |
| FE-ADM-11 | component + e2e | ZIP preview with 1 bad file; confirm; retry | preview lists the bad file; confirm creates the rest; retry creates 1 |
| FE-ADM-11 | component | Preview with an entry lacking `allowed_departments` and one with `[]` | both marked invalid with the server message and excluded from confirm; no owner default shown |
| FE-ADM-12 | component | Replace upload | "current version stays live" notice; result shown |
| FE-ADM-13 | component | Rows in `failed`, `ready` and `processing`; replace a failed one; server 409 / 422 | action only on the failed row; dialog notice shown; success → `queued`; error message shown and row stays `failed` |

### Retired IDs (do not reuse)
None. FE-ADM-01..10 are kept with updated meaning.

## Current implementation (LEGACY, not migrated)
- `src/pages/AdminUpload.jsx` has a form with title, a Google Drive URL and hard-coded departments 1–5.
- After creation it opens `WebSocket /api/ws/documents/{id}`. The socket is not closed on unmount.
- The status badge checks `'error'` while the backend writes `'failed'`, so failed documents look pending.
- Dialogs use `window.confirm`/`alert`. There is no file upload, ZIP import, replace or retry.

## Known gaps
Every FE-ADM requirement is unimplemented on the target stack.

## Related docs
`architecture.md`, `../backend/admin-docs.md`, `../backend/ingestion.md`, `../cross-cutting/document-lifecycle.md`
