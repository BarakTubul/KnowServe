# M0 — Foundation and deployment spike (provisional plan)

**Status:** Provisional and **not started**. Documentation only until the user approves the docs-only PR and authorizes M0. Repository organization: monorepo + worktrees with a narrowly shared domain core. The core's ownership is **OPEN-01**.

## Goal / exit criteria
| ID | Exit criterion |
|---|---|
| M0-EX1 | Repository foundation: repeatable `uv`/`pnpm` installs from lockfiles, tooling, `.env.example`, and a docs/contract index. |
| M0-EX2 | React+Vite on Cloudflare Pages reaches FastAPI on Cloud Run with a minimal successful API response. |
| M0-EX3 | Separate Cloud Run images for the API and the Worker. The API connects to Neon PostgreSQL, the initial Alembic migration runs, and pgvector feasibility is shown. |
| M0-EX4 | A signed QStash call reaches the Worker. The Worker refuses bad signatures and handles a duplicate minimal job safely. Outbox fast-path and recovery feasibility are proven. This is **not** full ingestion (that is M3). |
| M0-EX5 | Terraform, IAM, Secrets and CI are connected with no committed secrets. GitHub Actions has protected merge and a post-deploy smoke test. |
| M0-EX6 | Budget, free-tier, timeout and quota checks are documented, along with risks, blocked assumptions and requirement-to-test mapping. Reviewer and human approval come before merge. |

## Repository shape
The proposed target layout is below. The existing `backend/` and `frontend/` folders are legacy, and moving them is a **future migration proposal** (OPEN-18). Nothing is moved in the docs phase.

```text
apps/frontend/src/{app,features,components,lib}/
apps/api/src/knowserve_api/
apps/worker/src/knowserve_worker/
packages/backend_core/src/knowserve_core/   # only code with >1 real consumer
infra/terraform/
docs/{architecture,contracts,adr,milestones/M0}/
tests/{integration,e2e}/
.github/workflows/
compose.yaml, pyproject.toml, uv.lock, pnpm-workspace.yaml
```

## Ownership and contracts
- Owner: plan, contracts, integration. Shared core ownership is OPEN-01; the recommendation is Owner-owned, but this is **not decided**.
- Agent A: FastAPI + DB + Alembic foundation.
- Agent B: React shell, router, generated API types and client.
- Agent C: signed Worker endpoint and minimal queue spike.
- Agent D: Terraform, IAM and hosting.
- Independent Review Agent: high-risk and final integration review.

Contracts must be fixed before parallel work starts:
- API/OpenAPI + error format
- config/environment keys
- DB migration ownership and engine/session
- minimal job envelope `{schema_version, job_id}` (ING-21)
- structured logging ids
- readiness/health
- the deployment interface

The OpenAPI schema is generated from FastAPI and diffed against the approved contract in CI, and TS types are generated with `openapi-typescript`. Contract changes need Owner coordination.

## Task graph (draft)
| ID | Deliverable | Depends on | Ownership |
|---|---|---|---|
| M0-01 | Repo, dev tooling, core contracts | — | Owner |
| M0-02 | API, database, Alembic, health | M0-01 | Backend Agent (A) |
| M0-03 | Frontend, router, API client | M0-01 | Frontend Agent (B) |
| M0-04 | Worker, QStash auth, minimal job | M0-01 | Worker Agent (C) |
| M0-05 | Terraform, Cloud Run, Pages, Secrets | M0-01 | Infrastructure Agent (D) |
| M0-06 | Integration CI and deployment | M0-02..05 | Owner |
| M0-07 | Smoke, security, cost, PR review package | M0-06 | Owner + Reviewer |

## Test plan (draft)
| ID | Acceptance criterion | Evidence | Covers |
|---|---|---|---|
| M0-AC01 | Clean locked dependency installs | CI install logs (`uv sync --frozen`, `pnpm install --frozen-lockfile`) | M0-EX1, STACK-35/36 |
| M0-AC02 | Frontend talks to the real deployed backend | Playwright deployment smoke | M0-EX2, INFRA-02 |
| M0-AC03 | API connects and the migration runs on PostgreSQL+pgvector | integration / migration tests | M0-EX3, ARCH-11 |
| M0-AC04 | Signed Worker delivery works; an invalid signature is blocked | security integration tests | M0-EX4, SEC-14, ING-14 |
| M0-AC05 | A duplicate minimal delivery does not execute twice | Worker integration test | M0-EX4, ING-15 |
| M0-AC06 | OpenAPI schema and generated TS types are in sync | schema diff + `tsc` compile | ARCH-04, STACK-38 |
| M0-AC07 | Code-quality and test failures block the PR | required CI checks configured | STACK-33/34, TEST-02 |
| M0-AC08 | Deployment smoke works after an approved merge | deploy logs + checks | INFRA-04 |
| M0-AC09 | Prices, free tiers and limits are documented | deployment spike report | INFRA-03, COST-01 |
| M0-AC10 | Outbox recovery: a pending row whose immediate publish "crashed" is later published by the recovery dispatcher | Worker/API integration test | M0-EX4, ING-13 |

M0-AC10 is added here to make M0-EX4's "recovery feasibility proven" testable. It derives from the source exit criterion and the ING-13 required test, and should be confirmed in M0 planning.

## Open for M0 planning
- OPEN-01: shared core ownership.
- OPEN-06: Terraform backend, regions, provider feasibility.
- OPEN-07: sequencing and onboarding scripts.
- Also open: the ephemeral CI DB, the environment split, the scheduler cadence, and the shape of the proof-of-recovery test.
- Be explicit about the Cloud Run Worker request timeout vs processing-job size. Record compatibility uncertainties rather than guaranteeing them.

The Task Board `docs/milestones/M0/tasks.md` (WF-10) is created by the Owner when M0 starts.

## Related docs
`../../architecture/infrastructure.md`, `../../architecture/tech-stack.md`, `../../workflow/agent-workflow.md`, `../../workflow/testing.md`, `../../open-decisions.md`
