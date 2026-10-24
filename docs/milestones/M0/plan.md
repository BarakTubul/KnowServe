# M0 — Foundation and deployment spike (provisional plan)

**Status:** Provisional and **not started**. Documentation only until the user approves the docs-only PR and authorizes M0. Repository organization: a single modular monorepo + worktrees with a narrowly shared domain core whose interfaces the Owner coordinates (OPEN-01, OPEN-18). Nothing below has been implemented or migrated yet.

## Goal / exit criteria
| ID | Exit criterion |
|---|---|
| M0-EX1 | Repository foundation: repeatable `uv`/`pnpm` installs from lockfiles, tooling, `.env.example`, and a docs/contract index. |
| M0-EX2 | React+Vite on Cloudflare Pages reaches FastAPI on Cloud Run with a minimal successful API response. |
| M0-EX3 | Separate Cloud Run images for the API and the Worker. The API connects to Neon PostgreSQL, the initial Alembic migration runs, and pgvector feasibility is shown. |
| M0-EX4 | A signed QStash call reaches the Worker. The Worker refuses bad signatures and handles a duplicate minimal job safely. Outbox fast-path and recovery feasibility are proven. This is **not** full ingestion (that is M3). |
| M0-EX5 | Terraform, IAM, Secrets and CI are connected with no committed secrets. GitHub Actions has protected merge and a post-deploy smoke test. |
| M0-EX6 | Budget, free-tier, timeout and quota checks are documented, along with risks, blocked assumptions and requirement-to-test mapping. Reviewer and human approval come before merge. |

## Repository structure (OPEN-18)
### Current structure (legacy, unchanged in the docs phase)
```text
backend/app/            # legacy FastAPI + Celery + Chroma code, committed chroma_data/ and static PDFs
backend/scripts/, backend/requirements.txt, backend/pytest.ini
frontend/               # legacy React JS + npm (package-lock.json)
docs/                   # specs (this documentation)
AGENTS.md, CLAUDE.md
```

### Target structure (single modular monorepo)
```text
apps/frontend/src/{app,features,components,lib}/
apps/api/src/knowserve_api/
apps/worker/src/knowserve_worker/
packages/backend_core/src/knowserve_core/   # focused shared domain code, only with >1 real consumer
infra/terraform/
docs/{architecture,contracts,adr,milestones}/
tests/{integration,e2e}/
.github/workflows/
compose.yaml, pyproject.toml, uv.lock, pnpm-workspace.yaml
```
Exact names may be adjusted by the Owner in M0-01 with an ADR; the shape (frontend, API, Worker, focused shared core, Terraform, tests, docs) is approved.

### Planned M0 transition tasks (part of M0-01; nothing is moved before M0 is authorized)
1. Create the target skeleton and workspace/lockfiles (`uv`, `pnpm`) alongside the legacy folders.
2. For each legacy part, the Owner decides in an M0-01 ADR whether it is moved into the target layout (with `git mv`, preserving history) or rebuilt from the specs. Legacy behavior that conflicts with STACK-X (JWT, Celery/Redis, Chroma, gdown, WebSocket) is never carried into the target.
3. Until that ADR is executed, `backend/` and `frontend/` remain as LEGACY; their removal is an explicit, reviewed commit inside the M0 milestone branch.
4. Do not carry over committed binaries (`backend/app/chroma_data/`, `backend/app/static/docs/*.pdf`); their removal from the tree is an explicit, reviewed M0 change that preserves history.
5. Update `AGENTS.md` commands and the doc index when the new layout lands.

## Ownership, allocation and contracts
- **Owner**: plan, dependency graph, shared contracts and Shared Domain Core interfaces (approval and coordination), integration and quality gates. Implementation of shared code may be delegated (OPEN-01). No permanent Shared Core Agent.
- **Agent allocation is dynamic** (WF-16, OPEN-07): at M0 start the Owner derives the allocation from the task graph below. The four workstreams it suggests (backend/DB, frontend shell, Worker/queue spike, infrastructure) are an **indicative** split, not a fixed headcount; workstreams may be merged or split according to real independence and conflict risk.
- **Independent Review Agents**: selectively for security-critical (Worker signature, IAM/secrets, session/CSRF topology) and cross-cutting changes, plus the final integration review.

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
| M0-01 | Repo transition skeleton (see above), dev tooling, onboarding commands, core contracts | — | Owner |
| M0-02 | API, database, Alembic, health, error envelope (ARCH-05) | M0-01 | backend workstream |
| M0-03 | Frontend, router, API client | M0-01 | frontend workstream |
| M0-04 | Worker, QStash auth, minimal job | M0-01 | Worker workstream |
| M0-05 | Terraform, Cloud Run, Pages, Secrets, same-site domain feasibility (INFRA-11) | M0-01 | infrastructure workstream |
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
| M0-AC11 | Same-site topology feasibility: custom `app.`/`api.` hosts for Pages and Cloud Run, host-only `SameSite=Lax` cookie and CORS behavior verified, domain cost recorded; or a documented blocker with alternatives for the user | spike report + deploy smoke | M0-EX2, M0-EX6, INFRA-11, AUTH-19 |

M0-AC10 makes M0-EX4's "recovery feasibility proven" testable. M0-AC11 makes the approved OPEN-04 topology verifiable in the spike; it does not assume the domain is feasible. Both were added during reconciliation and are confirmed at M0 plan approval (OPEN-20).

Not in M0: login, sessions, CSRF enforcement and **Email OTP** are M1 (`../M1/plan.md`). M0 only proves the hosting topology they depend on.

## Open for M0 planning
- OPEN-06: Terraform backend, regions, provider feasibility.
- OPEN-09: provider backup/restore capability.
- OPEN-10: cost evidence, including the custom domain.
- Operational details decided by the Owner during M0: the ephemeral CI DB, the environment split, the scheduler cadence, and the shape of the proof-of-recovery test.
- Be explicit about the Cloud Run Worker request timeout vs processing-job size. Record compatibility uncertainties rather than guaranteeing them.

The Task Board `docs/milestones/M0/tasks.md` (WF-10) is created by the Owner when M0 starts.

## Related docs
`../../architecture/infrastructure.md`, `../../architecture/tech-stack.md`, `../../workflow/agent-workflow.md`, `../../workflow/testing.md`, `../../open-decisions.md`, `../M1/plan.md`
