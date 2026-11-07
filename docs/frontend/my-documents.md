# Frontend document library and PDF viewer

**Status:** Target spec (M2). The library page (FE-DOC-01..06, 10) is implemented on the target stack (M2-04a, local branch, tested against mocks; not yet run against the real API). The viewer (FE-DOC-07..09) is not.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| FE-DOC-01 | The library is fetched with TanStack Query, keyed by identity + active department (FE-ARCH-04), and refetched after a switch or invalidation. It never reuses another department's data. | M2 |
| FE-DOC-02 | The library shows loading, empty ("no documents available in this department") and error states. Errors are actually rendered as friendly localized messages (PROD-13, FE-ARCH-14). | M2 |
| FE-DOC-03 | Filename search and an **owner department** filter. Filter options come from the API, not from hard-coded ids. | M2 |
| FE-DOC-04 | Each item shows filename/title and owner department. The UI does not imply that ownership grants access (PROD-06). | M2 |
| FE-DOC-05 | Each listed document (all of them are ready and authorized) opens in the protected viewer at `/documents/:id`. | M2 |
| FE-DOC-06 | When the filters match nothing, show a "no documents match" message. | M2 |
| FE-DOC-07 | The **PDF viewer** uses React-PDF and loads bytes only from the API bytes endpoint (DOC-04) with credentials. It never uses a storage or public URL. | M2 |
| FE-DOC-08 | The viewer has a custom toolbar with page navigation and zoom. The `?page=N` query parameter opens that page and stays in sync with navigation. The header shows the filename + page. | M2 |
| FE-DOC-09 | A 404 from the metadata or bytes endpoint shows a neutral "not found or not available" view that does not reveal whether the document exists (SEC-02). A revoked document that is already open stops loading new pages on the next request. | M2 |
| FE-DOC-10 | The library loads one page of results and offers a "Load more" button while the API reports `has_more`. It follows the opaque `next_cursor`, appends items, and resets the cursor when the search, owner filter, identity or active department changes (OPEN-28 Q3). | M2 |

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
| FE-DOC-10 | component | 3 items with a page size of 2; click "Load more"; change the filter afterwards | second click appends the third item and the button disappears; a filter change restarts from the first page |

### Retired IDs (do not reuse)
None. FE-DOC-01..06 are kept with updated meaning.

## Current implementation (target, M2-04a)
- `apps/frontend/src/features/documents/library-page.tsx` (`LibraryPage`, route `/documents`): `useInfiniteQuery` keyed `['dept', userId, departmentId, 'documents', {q, owner}]`, so identity, department and filter changes each get their own entry and start at the first page (no cursor). The auth provider already removes `['dept']` queries on a department switch and clears the cache on logout/identity change.
- `library-api.ts`: `GET /v1/documents` through the generated client; errors become `ApiError` and go to the global handler (409 opens the department selector).
- Filename/title search is debounced (250 ms); the owner filter options come from `GET /v1/departments`; "Load more" follows `next_cursor` while `has_more`.
- States: loading, empty, error (with retry) and no match. The dashboard links to the library.
- Localization (Q13/OPEN-29, M2-AC22): `library-messages.ts` holds one catalog per language (`en`, `he`) with every screen string and the error messages keyed by API code (`UNAVAILABLE`, `RATE_LIMITED`, `VALIDATION_ERROR` by status, plus `NETWORK_ERROR`, `UNAUTHENTICATED`, `ACTIVE_DEPARTMENT_REQUIRED`) and a generic fallback; a code missing in the selected language falls back to English, then to the generic message. The language comes from `useLanguage()` (`src/lib/i18n/`), and the library header has the `LanguageSelector`. Item titles use `dir="auto"` and file names `<bdi>`, so mixed text stays readable in RTL.
- Tests: `library.test.tsx` (FE-DOC-01..06, 10, FE-ARCH-14 mapping); `src/lib/i18n/i18n.test.tsx` (Q13: default, persistence, selector, `dir`, catalog parity, no technical or English text in Hebrew, fallbacks).

## Legacy behaviour (not migrated)
- `src/pages/MyDocuments.jsx` and `src/context/DocsContext.jsx` cache the list forever, with no invalidation and no clearing on logout.
- The page filters by *allowed* departments (not the owner) and shows a red badge for any non-`ingested` status.
- The `error` state is never rendered.
- "View PDF" opens `/api/documents/my/{id}/download` in a new tab. There is no viewer, page deep links or zoom.

## Current implementation (target, M2-04b)
- `apps/frontend/src/features/documents/viewer-page.tsx` (`ViewerPage`, route `/documents/:id`) plus `viewer/` (`api.ts`, `messages.ts`, `pdf-surface.tsx`). Covers FE-DOC-07, 08 and 09; evidence in `viewer/viewer.test.tsx` (component level, `react-pdf` mocked). The e2e half of FE-DOC-08 is open.
- Metadata comes from `GET /v1/documents/{id}`; bytes load through React-PDF 11.0.0 (`pdfjs-dist` 6.3.289) from `/api/v1/documents/{id}/content` with `withCredentials`. pdf.js is lazy-loaded and its worker is a same-origin build asset.
- Toolbar: previous/next, zoom 50% to 200%. `?page=N` is the source of truth (next pushes `?page=N+1`). An out-of-range or non-numeric page shows an inline notice and the nearest page.
- A 404 from metadata or bytes renders one identical neutral view. Other errors map from the error code to a catalog message (`viewer/messages.ts`, English and Hebrew, generic fallback, English for a code missing in Hebrew); `error.message` is never rendered. Toolbar labels, page text, loading and not-available texts come from the same catalog, and the toolbar has the `LanguageSelector`. The PDF canvas container is `dir="ltr"` and the zoom percentage stays LTR.
- Range requests: pdf.js asks for ranges; until the Pages proxy forwards `Range` (M2-03/Owner, Q2) the API answers 200 with the full body, which pdf.js accepts.

## Known gaps
- FE-DOC-07..09 (viewer) are unimplemented (M2-04b).
- Existing flows (auth, department selector, dashboard text, `describeApiError`) still use hard-coded English and some technical text (e.g. a "reference <request id>" fallback); they are not on the catalog yet (PROD-13/FE-ARCH-14 gap, migrate by risk).
- Only the library and the viewer are bilingual (English default, Hebrew, selector, choice kept in `localStorage['knowserve.locale']`, not the account). Auth, the department selector dialog and the dashboard stay English-only and keep `<html dir>` flipping RTL without translated text, so they can look half-localized in Hebrew; they are the next localization gap, migrated by risk (PROD-13/FE-ARCH-14).
- Hebrew copy has had no native-speaker review yet.
- No e2e/Playwright run against the real M2-02 API yet.
FE-DOC-01 to 06 and 10 (the library, M2-04a) are unimplemented. FE-DOC-07 to 09 are implemented locally; no Playwright run and no check against a real PDF yet.

## Related docs
`architecture.md`, `chat.md`, `../backend/documents.md`, `../cross-cutting/security-and-permissions.md`, `../cross-cutting/product-and-ux.md`
