# Validation checklist for Claude's repository doc reconciliation

## Documentation acceptance
- [ ] All old Markdown docs mapped to new target topics; no orphan spec or broken relative link.
- [ ] `AGENTS.md`, `CLAUDE.md`, `docs/README.md` and doc index updated for agreed agent workflow, including **no blanket wait for approval for every fix/edit**; human approval at milestone PR and material scope/contract changes.
- [ ] Every normative statement has stable requirement ID in repo spec where suitable, and at least one positive/negative/error test where applicable; `Known gaps` separate target requirements from legacy code.
- [ ] Cross-references correct; no contradictory status codes, document visibility rules or auth schemes.
- [ ] Product: public fictional Demo Mode, registered/anonymous identities, seeded departments, no public Admin signup.
- [ ] Backend: opaque DB-backed session hash and CSRF/Argon2id; no JWT as target auth scheme.
- [ ] ACL: owner_department does not imply access; explicit join records; 401/403/404 semantics and department isolation.
- [ ] PDF: private R2, React-PDF authorized Viewer, page deep links, no public Google Drive/gdown target upload.
- [ ] Ingestion: ZIP manifest/preview/confirm/partial retry, R2, QStash signed worker, outbox fast path+scheduled recovery, at-least-once/idempotency/leases, revision atomic publish/soft-delete.
- [ ] Streaming: SSE via Fetch POST + AbortController for chat; job status SSE/DB truth; no Redis pubsub/WebSocket target.
- [ ] AI: LlamaIndex, OpenRouter for chat, direct OpenAI embeddings, PyMuPDF4LLM, SentenceSplitter bounded to page, custom SQL authorized retrieval **before** Top-K, threshold, citation backend checks.
- [ ] Evaluation: Golden human verified, security hard failures, progressive gates and reproducible reports.
- [ ] Frontend: React TypeScript Vite, Tailwind shadcn, React Router, TanStack Query, RHF/Zod, React-PDF, no Redux default.
- [ ] Infrastructure: Cloudflare Pages/R2, Cloud Run API+Worker, Neon PostgreSQL pgvector, Terraform, Google Secret Manager, GitHub Actions OIDC, Dockerfiles/Compose, Cloud Logging.
- [ ] Tooling: uv/pnpm, Pyright/Ruff, ESLint/Prettier/strict TS, pytest/Vitest/Playwright.
- [ ] Milestones, Worktrees, integration Owner, controlled scope, risk-based tech debt, Test Plan in planning, traceability and concise handoffs reflected.
- [ ] Open questions (Shared Core ownership, thresholds, pricing, final LLM) are not converted into binding choices.
- [ ] Deferred fictional-document corpus topic is preserved but not designed prematurely.
- [ ] No code/deploy/schema updates carried out during the documentation-only phase.

## Required report table
| Requirement/topic | Original repo docs | Updated repo docs | State (aligned/updated/open) | Evidence/link | Remaining gap/code mismatch |
|---|---|---|---|---|---|

## Minimum static checks
1. Inventory original/new `.md` files; ensure major doc references and links resolve.
2. Search updated spec docs for contradictory **target** prescriptions: `JWT`, `Celery`, `Redis`, `Chroma`, `gdown`, `WebSocket`, `JSX/JS only`, `npm`, `OpenAI direct LLM`. Historical current-state/gap mentions are allowed if clearly labeled as LEGACY.
3. Requirement ID uniqueness and test coverage mapping.
4. Compare agreed source-package file by file with updated repo docs, produce discrepancy/coverage matrix.
5. Explicitly inspect `AGENTS.md` for old workflow mandate to await approval before each code edit.
6. `git diff --check` and any suitable docs/link linters; docs-only diff.
7. Flag impossible/unsafe requirements, cost assumptions and plan contradictions for human review; do not silently resolve them.

## Human validation before implementation
- User reviews diff, changed doc inventory, unresolved choices, milestone M0 acceptance plan, mismatch report.
- User approves a **documentation-only** PR first. Only then plan/run code implementation; changes to cloud credentials or deployment require separate explicit action.
