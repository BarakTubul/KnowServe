# M0 — Foundation and Deployment Spike (planning draft)

**Status:** Provisional plan; docs-only until user approves implementation start. Selected Monorepo + Worktrees and narrowly shared Domain Core.

## Deliverable / exit criteria
- Repository foundation, repeatable `uv` / `pnpm` installs from Lockfiles, tooling, `.env.example`, docs/contract index.
- React+Vite on Cloudflare Pages reaches FastAPI on Cloud Run; minimal successful API response.
- Separate Cloud Run API and Worker images; API connects to Neon PostgreSQL; Alembic initial migration, pgvector feasibility.
- Signed QStash call reaches Worker; Worker refuses bad signatures and handles duplicate minimal job safely; outbox fast path/recovery feasibility proven, not full ingestion implementation.
- Terraform/IAM/Secrets/CI connected with no committed secrets; GitHub Actions protected merge and post-deploy smoke.
- Budget/free-tier/timeout/quotas check documented. Risk, blocked assumptions, requirement-to-tests mapping, reviewer and human approval before merge.

## Proposed repository shape (adapt existing repository, don't blindly rename/move)
```text
apps/frontend/src/{app,features,components,lib}/
apps/api/src/knowserve_api/
apps/worker/src/knowserve_worker/
packages/backend_core/src/knowserve_core/  # create only required shared code
infra/terraform/
docs/{architecture,contracts,adr,milestones/M0}/
tests/{integration,e2e}/
.github/workflows/
compose.yaml
pyproject.toml; uv.lock; pnpm-workspace.yaml
```
Existing snapshot uses `backend/` and `frontend/`: **a future migration proposal**, not instructions for this documentation-only phase to move the source tree.

## Agreed ownership model
- Planning & Integration Owner: plan/contracts/shared core ownership/integration; can delegate implementation; shared domain only when more than one actual consumer or strong explicit necessity.
- Agent A: FastAPI+DB+Alembic foundation. Agent B: React shell, router, generated API types/client. Agent C: signed Worker endpoint and minimal queue spike. Agent D: Terraform/IAM/hosting. Independent Review Agent: high-risk and final integration review.
- Contracts before parallel implementation: API/OpenAPI+errors, config/environment, database migration ownership/engine session, minimal job envelope `{schema_version, job_id}`, structured logging IDs, readiness/health, deployment interface.
- Backend can generate OpenAPI schema from Pydantic/FastAPI; compare to approved contract in CI and generate TS types via openapi-typescript. Changes require Owner coordination.

## Task graph (draft)
| ID | Deliverable | Depends on | Ownership |
|---|---|---|---|
| M0-01 | Repo/dev tooling/core contracts | none | Owner |
| M0-02 | API/database/Alembic/health | 01 | Backend Agent |
| M0-03 | Frontend/router/API client | 01 | Frontend Agent |
| M0-04 | Worker/QStash auth and minimal job | 01 | Worker Agent |
| M0-05 | Terraform/Cloud Run/Pages/Secrets | 01 | Infrastructure Agent |
| M0-06 | Integration CI and deployment | 02–05 | Owner |
| M0-07 | Smoke/security/cost/PR review package | 06 | Owner + Reviewer |

## M0 Test Plan (draft)
| ID | Acceptance criterion | Evidence |
|---|---|---|
| M0-AC01 | clean locked dependencies | CI installation logs |
| M0-AC02 | frontend talks to real deployed backend | Playwright deployment smoke |
| M0-AC03 | API connects and migration runs with PostgreSQL+pgvector | integration/migration tests |
| M0-AC04 | signed worker delivery works; invalid signature blocked | security integration tests |
| M0-AC05 | duplicate minimal delivery doesn't execute twice | worker integration test |
| M0-AC06 | OpenAPI schema and generated TS types in sync | schema diff + compile |
| M0-AC07 | code quality/test failures block PR | required CI checks |
| M0-AC08 | deployment smoke works after approved merge | deploy logs + checks |
| M0-AC09 | prices/free tiers/limits documented | deployment spike report |

## Remaining M0 planning decisions
- **OPEN:** Whether Shared Domain Core is Owner-owned (recommended) vs delegated dedicated/shared governance. User has not yet selected among these options. Do not silently mark as decided.
- Detailed ephemeral CI DB, environment split, scheduler cadence, proof-of-recovery test, and actual provider/resource limits left for M0 planning/spike.
- Be explicit about Cloud Run worker request timeout vs processing job size. Record compatibility uncertainties rather than inventing guarantees.
