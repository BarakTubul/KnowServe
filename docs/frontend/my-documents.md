# Frontend document library and PDF viewer

**Status:** Target spec (M2). Not implemented: the legacy `/my-docs` page lists department documents and links to a raw PDF download. There is no viewer.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-DOC-01 | The library is fetched with TanStack Query, keyed by identity + active department (FE-ARCH-04), and refetched after a switch or invalidation. It never reuses another department's data. | M2 |
| FE-DOC-02 | The library shows loading, empty ("no documents available in this department") and error states. Errors are actually rendered. | M2 |
| FE-DOC-03 | Filename search and an **owner department** filter. Filter options come from the API, not from hard-coded ids. | M2 |
| FE-DOC-04 | Each item shows filename/title and owner department. The UI does not imply that ownership grants access (PROD-06). | M2 |
| FE-DOC-05 | Each listed document (all of them are ready and authorized) opens in the protected viewer at `/documents/:id`. | M2 |
| FE-DOC-06 | When the filters match nothing, show a "no documents match" message. | M2 |
| FE-DOC-07 | The **PDF viewer** uses React-PDF and loads bytes only from the API bytes endpoint (DOC-04) with credentials. It never uses a storage or public URL. | M2 |
| FE-DOC-08 | The viewer has a custom toolbar with page navigation and zoom. The `?page=N` query parameter opens that page and stays in sync with navigation. The header shows the filename + page. | M2 |
| FE-DOC-09 | A 404 from the metadata or bytes endpoint shows a neutral "not found or not available" view that does not reveal whether the document exists (SEC-02). A revoked document that is already open stops loading new pages on the next request. | M2 |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| FE-DOC-01 | component | Department switch | the old list is never rendered; a new query key is fetched |
| FE-DOC-02 | component | Empty / error | empty message / error message |
| FE-DOC-03 | component | Search + owner filter | intersection shown |
| FE-DOC-04 | component | Item render | filename and owner department; no "access" wording derived from the owner |
| FE-DOC-05 | component | Click an item | navigates to `/documents/:id` |
| FE-DOC-06 | component | Search with no hits | "no documents match" message |
| FE-DOC-07 | component | Viewer load | requests only the API bytes URL, with credentials |
| FE-DOC-08 | component + e2e | Open `?page=3`; click next | page 3 shown; URL becomes `?page=4` |
| FE-DOC-09 | component | Bytes 404 | neutral not-found view |

### Retired IDs (do not reuse)
None. FE-DOC-01..06 are kept with updated meaning.

## Current implementation (LEGACY, not migrated)
- `src/pages/MyDocuments.jsx` and `src/context/DocsContext.jsx` cache the list forever, with no invalidation and no clearing on logout.
- The page filters by *allowed* departments (not the owner) and shows a red badge for any non-`ingested` status.
- The `error` state is never rendered.
- "View PDF" opens `/api/documents/my/{id}/download` in a new tab. There is no viewer, page deep links or zoom.

## Known gaps
Every FE-DOC requirement is unimplemented on the target stack.

## Related docs
`architecture.md`, `chat.md`, `../backend/documents.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/product-and-ux.md`
