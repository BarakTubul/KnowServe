# Frontend My Documents

## Purpose
`/my-docs` page: list the documents the signed-in user's department can access, with search, department filter and PDF viewing.

## Requirements
| ID | Requirement |
|---|---|
| FE-DOC-01 | On first visit the page fetches `GET /documents/my/access` and caches the result in `DocsContext`; later visits reuse it without refetching. |
| FE-DOC-02 | While loading it shows a spinner; with no documents it shows "You don't have access to any documents yet."; on fetch failure it must show the error (see gap). |
| FE-DOC-03 | Search filters by title (case-insensitive); the department select lists "All" plus every department present in the results and filters by it. Both filters combine. |
| FE-DOC-04 | Each item shows title, "Visible to" departments and status. |
| FE-DOC-05 | The "View PDF" link (to `/api/documents/my/{id}/download`, new tab) shows only when status is `ingested`. |
| FE-DOC-06 | If the filters match nothing, show "No documents match your filter criteria." |

## Files
`src/pages/MyDocuments.jsx`, `src/pages/MyDocuments.css`, `src/context/DocsContext.jsx`, `src/services/api.js` (`fetchAccessibleDocsApi`)

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-DOC-01 | component | Mount twice with provider kept | API called once |
| FE-DOC-02 | component | Empty array / API rejects | empty state / error message visible |
| FE-DOC-03 | component | Search "hand" + dept "HR" | only docs matching both |
| FE-DOC-04 | component | One doc | title, departments and status rendered |
| FE-DOC-05 | component | Doc `pending`, `failed`, `ingested` | link only for `ingested` |
| FE-DOC-06 | component | Search with no hits | empty-filter message |

## Known gaps
- FE-DOC-02: `error` state is set but never rendered; a failed load shows the empty state.
- The cache in `DocsContext` is never invalidated: new/removed documents or changed access don't appear until a full reload; it also isn't cleared on logout (another user on the same tab sees the previous list).
- Status badge shows red `status-error` for any non-`ingested` value, including `pending`.
- The page uses `/documents/my/access`; `/documents/my/owned` is unused (and broken on the backend).

## Related docs
`architecture.md`, `../backend/documents.md`
