# KnowServe

A portfolio **demo** of a fictional organization's departmental knowledge assistant. Users browse permissioned PDFs and ask grounded, cited questions (RAG). Access is enforced per active department.

## Where the project is
- **Target system** (approved): React+TypeScript on Cloudflare Pages; FastAPI API + Worker on Cloud Run; Neon Postgres+pgvector; R2; QStash with a transactional outbox; opaque DB sessions; LlamaIndex with OpenRouter (chat) and OpenAI embeddings. Full list in `docs/architecture/tech-stack.md`.
- **Two code trees:** the new monorepo (`apps/`, `packages/`, `infra/`) is the target and is built milestone by milestone. `backend/` (FastAPI with JWT, Celery/Redis, Chroma, gdown) and `frontend/` (React JS) are **LEGACY** reference code, not migrated and not deployable. Never describe a target requirement as implemented without test evidence.
- **Phase:** **M0**: local implementation is done and a temporary isolated cloud spike was built, tested and cleaned up (`docs/milestones/M0/handoff.md`, `tasks.md` is the live status); M1+ has not started. Cloud actions (Terraform apply, deploys, accounts, domain, spend), `git push` and merges still need the user's separate explicit approval. Work proceeds milestone by milestone (M0–M6, WF-14).
- **GitHub:** the repository is `BarakTubul/KnowServe` (public). The active GitHub user for this project is **`BarakTubul`**, the owner. Use that account for `gh` and `git push`; the other logged-in account (`Barak-Horizon`) has no push rights here. Check with `gh api user --jq .login` before any GitHub write.

## How to work (summary of `docs/workflow/agent-workflow.md`)
1. **Read only what the task needs.** Find the task area in the index below, then read those specs plus their linked SEC/OPEN items. Specs hold the approved contracts and requirements.
2. **Owner-led parallel work.**
   - The Planning & Integration Owner plans the milestone, fixes the shared contracts (OpenAPI/errors, DB schema/migrations, config, job envelope, logging ids, Shared Domain Core interfaces), allocates agents dynamically from the dependency graph (no fixed count) and integrates (WF-02, WF-16).
   - Each agent works in its own git worktree and branch, and freely changes the internals of its own modules.
   - Shared-contract changes need Owner approval and coordination with dependent agents before implementation (WF-03).
3. **Act within scope without asking.** Implementation agents fix local defects and the edge cases implied by existing requirements on their own. There is **no approval gate per edit or commit**.
4. **Escalate** changes to architecture, interfaces/contracts, the security model, scope, cost or anything cross-cutting to the Owner. The Owner takes new features or major scope expansion to the **user** (WF-04, WF-05).
5. **Respect decisions.** "Resolved decisions" in `docs/open-decisions.md` are binding. Never turn an item under "Still open" into a binding choice; reference its OPEN-id and escalate.
6. **Test with traceability.** Write tests alongside the code, following the spec's "Required tests" table, and put requirement ids in test names (TEST-01, TEST-07). Security tests are hard gates from day one.
7. **Review gates are limited** to integration points, an independent review of risky changes, and the final milestone PR. **The user approves the milestone PR**, and deploy follows automatically (WF-06, WF-13).
8. **Hand off concisely.**
   - Agent → Owner: branch/commit, contracts touched, tests + evidence, risks, gaps (WF-08).
   - Milestone end: a handoff doc referencing the specs (WF-12).
   - The Owner keeps `docs/milestones/Mx/tasks.md` current and writes short ADRs in `docs/adr/` (WF-10).
9. **Keep specs true.** Update requirements, tests and "Current implementation / Known gaps" in the same change (WF-15). Handle debt by risk (WF-11).

Hard limits unless the user explicitly authorizes otherwise:
- no deployment
- no infra apply
- no secrets in the repo or Terraform state
- no changes to cloud credentials
- no merge to `main` without the user's approval of the milestone PR

## Commands
- **Target** (monorepo: `apps/`, `packages/`, `infra/`, `tests/`; contracts in `docs/contracts/`, decisions in `docs/adr/`):
  - local database: `docker compose up -d db` (pgvector, host port 5433; local-only credentials); copy `.env.example` to `.env`
  - Python (repo root): `uv sync`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pyright`, `uv run pytest` (integration tests need the database and fail, not skip, without it)
  - frontend (repo root): `pnpm install`, `pnpm -r lint|format:check|typecheck|test|build`
  - migrations: `uv run alembic -c packages/backend_core/alembic.ini upgrade head` with `KS_DATABASE_URL` set
  - **never run cloud-affecting commands** (`terraform apply`, deploys) without the user's explicit authorization
- **Legacy (current code):**
  - backend from `backend/`: `uvicorn app.main:app --reload` and `celery -A app.core.celery_app.celery_app worker` (needs Postgres and Redis)
  - frontend from `frontend/`: `npm run dev`, `npm run lint`
  - There are no tests. The legacy folders are excluded from the new workspaces, lint and CI (`docs/adr/0001-repo-layout-and-legacy.md`).

## Doc index
Start from `docs/README.md` for the spec template and rules.

| Task area | Read |
|---|---|
| Any change (scope, IDs, open items) | `docs/README.md`, `docs/open-decisions.md` |
| Backend change | `docs/backend/architecture.md`, `docs/cross-cutting/security-and-permissions.md` |
| Frontend change | `docs/frontend/architecture.md` |
| Stack / library choice | `docs/architecture/tech-stack.md` |
| Auth, sessions, CSRF, Email OTP, Try Demo, department switch | `docs/backend/auth.md`, `docs/frontend/auth.md`, `docs/cross-cutting/security-and-permissions.md`, `docs/milestones/M1/plan.md` |
| Document library, PDF viewer, access rules | `docs/backend/documents.md`, `docs/frontend/my-documents.md`, `docs/cross-cutting/security-and-permissions.md` |
| Document submission / upload / ZIP / replace / delete | `docs/cross-cutting/document-lifecycle.md`, then `docs/backend/admin-docs.md`, `docs/backend/ingestion.md`, `docs/frontend/admin-upload.md` |
| Worker, outbox, QStash, job status | `docs/backend/ingestion.md` |
| Chat, retrieval, citations, streaming | `docs/backend/chat.md`, `docs/frontend/chat.md`, `docs/cross-cutting/security-and-permissions.md` |
| Evaluation / golden dataset | `docs/cross-cutting/evaluation.md` |
| Logging, audit, usage | `docs/backend/monitoring.md` |
| Deployment, Terraform, secrets, cost/quotas | `docs/architecture/infrastructure.md` |
| Product scope, personas, Demo Mode | `docs/cross-cutting/product-and-ux.md` |
| Process, milestones, tests | `docs/workflow/agent-workflow.md`, `docs/workflow/testing.md`, `docs/milestones/M0/plan.md`, `docs/milestones/M0/tasks.md`, `docs/milestones/M0/test-plan.md`, `docs/milestones/M1/plan.md` |
| Repository layout / monorepo migration | `docs/milestones/M0/plan.md` ("Repository structure") |
| Why the docs look this way / legacy conflicts | `docs/reconciliation/` |
