# Frontend admin document management

## Purpose
`/admin/upload` page: an admin adds documents (title, Google Drive link, permitted departments), watches ingestion status, edits access, and deletes documents.

## Requirements
| ID | Requirement |
|---|---|
| FE-ADM-01 | The page is reachable only by admins (nav link hidden for others; route guarded). |
| FE-ADM-02 | On load it fetches `GET /admin/docs/` and lists documents with title, status and "Visible to" departments, with a title search. |
| FE-ADM-03 | The form requires title, a URL, and at least one department; with none selected it shows "Please select at least one permitted department." and sends nothing. |
| FE-ADM-04 | Submit calls `POST /admin/docs/` with `{title, source_url, allowed_department_ids}`; button shows "Processing..." and is disabled while in flight. |
| FE-ADM-05 | On success it shows a "queued for ingestion" banner, resets the form, refreshes the list (new doc shown as `pending`), and opens a WebSocket to `/api/ws/documents/{id}`. |
| FE-ADM-06 | On a WS message with status `ingested` it shows a success banner and refreshes the list; with `failed` it shows an error banner (with the error text if provided) and refreshes; the socket is closed in both cases. |
| FE-ADM-07 | "Edit Access" opens a department checklist pre-filled from `allowed_department_ids`; saving needs at least one department, calls `PATCH /admin/docs/{id}/access`, closes the panel and refreshes. |
| FE-ADM-08 | "Delete" asks for confirmation; on confirm calls `DELETE /admin/docs/{id}`, shows a success banner and refreshes; cancel does nothing. |
| FE-ADM-09 | API errors show the server message in the banner/alert; the form stays filled on failure. |
| FE-ADM-10 | The status badge distinguishes `pending`, `ingested` and `failed`. |

## Files
`src/pages/AdminUpload.jsx`, `src/pages/AdminUpload.css`, `src/services/api.js` (`fetchAdminDocsApi`, `adminUploadApi`, `updateAdminDocAccessApi`, `deleteAdminDocApi`), `src/components/Navbar.jsx`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-ADM-01 | component | Render route as employee | blocked/redirected |
| FE-ADM-02 | component | API returns 3 docs; search "fin" | 3 listed; filtered to matches |
| FE-ADM-03 | component | Submit with no department | message shown, API not called |
| FE-ADM-04 | component | Submit valid form | API body matches; button disabled during request |
| FE-ADM-05 | component | Success response `{id: 7}` | banner, form cleared, list refetched, `WebSocket` constructed with `.../api/ws/documents/7` |
| FE-ADM-06 | component | Fake WS emits ingested / failed | banners as specified, `ws.close()` called, list refetched |
| FE-ADM-07 | component | Open edit on doc with ids [1,3]; save with none / with [1,2] | pre-checked 1,3; alert; PATCH `[1,2]` |
| FE-ADM-08 | component | Delete with confirm true / false | DELETE called / not called |
| FE-ADM-09 | component | POST returns 400 `{detail}` | detail shown; inputs unchanged |
| FE-ADM-10 | component | Statuses pending/ingested/failed | three distinct classes |

## Known gaps
- FE-ADM-01: route not role-guarded (see `architecture.md`).
- FE-ADM-10: `doc.status === 'error'` is checked, but the backend writes `failed`, so failed documents show as pending.
- FE-ADM-06: backend does not send the `error` text over WS (see `backend/ingestion.md` ING-07); if the page is closed or reloaded before the event, the status only updates on the next list fetch (no polling or reconnect); socket is not closed on unmount.
- Departments are hard-coded (ids 1-5, fixed names); the form accepts any URL while the backend only supports Google Drive file links (ADM-06).
- Page says "Upload files", but only a URL is supported.
- Uses a lot of inline styles; `window.confirm`/`alert` for dialogs.

## Related docs
`architecture.md`, `../backend/admin-docs.md`, `../backend/ingestion.md`, `../cross-cutting/document-lifecycle.md`
