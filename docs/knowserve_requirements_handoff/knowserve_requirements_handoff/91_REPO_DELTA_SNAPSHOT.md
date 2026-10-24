# Initial mismatch audit — uploaded KnowServe.zip (2026-10-24)

**Scope:** Brief inspection of uploaded ZIP snapshot, not a comprehensive repository-level validation. The code/docs have **not been changed** and no tests were run.

| Existing path | Observed prior spec | New agreed target | Required doc reconciliation |
|---|---|---|---|
| `AGENTS.md` | Describes Google Drive links; Redis/Celery/Chroma, JWT; mandates user approval before *every* edit | R2/QStash/Neon, opaque sessions, owner-led parallel work with approval at meaningful gates | Rewrite overview, index, workflow, preserve current-state caveats |
| `docs/backend/architecture.md` | Redis doc cache, Chroma and JWT environment, synchronous UoW specifics | FastAPI + SQLAlchemy Async, domain core, PG/pgvector, DB sessions | Update target design, call out legacy implementation |
| `docs/backend/ingestion.md` | `gdown` Google Drive, Celery, Redis pub/sub, WebSocket, Chroma vectors | PDF/ZIP upload + R2, QStash, outbox, signed Cloud Run worker, SSE status, pgvector | Major rewrite; legacy gaps explicitly enumerated |
| `docs/frontend/architecture.md` | React plain JS/JSX, npm, WebSocket upload status, raw CSS | React TypeScript/Vite, Tailwind/shadcn, Query, RHF/Zod, SSE, pnpm | Update conventions and migration gaps |
| `docs/README.md` | Specs indexed with required test table; TestClient/Redis/Celery/Chroma fakes described | Early acceptance criteria Test Plan, traceability, async DB integration, tiers, modern tools | Preserve useful spec format/IDs; update test methodology |

## Further existing docs to review in full
`docs/backend/{auth,chat,documents,admin-docs,monitoring}.md`, `docs/frontend/{auth,chat,my-documents,admin-upload}.md`, `docs/cross-cutting/document-lifecycle.md`, `frontend/README.md`, and `CLAUDE.md`.

## Specific warning
The uploaded ZIP includes **`.git`**, tracked Chroma data and possibly static PDFs. Do not copy archive `.git` metadata or generated/binary files into a new branch. Before doing any operation on the live repository inspect branch status and avoid destructive bulk changes. Source tree layout (`backend/`, `frontend/`) is legacy and must not be silently rewritten in this **docs-only** phase.
