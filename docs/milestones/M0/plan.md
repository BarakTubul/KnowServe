# M0 — Foundation, CI, infrastructure and deployment spike

**Status:** Planned, **not started**. Nothing below is implemented or migrated. Implementation starts only after the user approves the docs PR, approves this plan (including OPEN-20) and grants the authorizations in "Approvals required" below. Repository organization: a single modular monorepo + worktrees with a narrowly shared domain core whose interfaces the Owner coordinates (OPEN-01, OPEN-18).

Companion files:
- `tasks.md`: task board, dependency graph, workstreams, worktree/branch boundaries, integration order.
- `test-plan.md`: acceptance criteria M0-AC01..14, verification, requirement traceability.

## Goal / exit criteria
| ID | Exit criterion |
|---|---|
| M0-EX1 | Repository foundation: repeatable `uv`/`pnpm` installs from lockfiles, tooling, `.env.example`, and a docs/contract index. |
| M0-EX2 | React+Vite on Cloudflare Pages reaches FastAPI on Cloud Run with a minimal successful API response. |
| M0-EX3 | Separate Cloud Run images for the API and the Worker. The API connects to Neon PostgreSQL, the initial Alembic migration runs, and pgvector feasibility is shown. |
| M0-EX4 | A signed QStash call reaches the Worker. The Worker refuses bad signatures and handles a duplicate minimal job safely. Outbox fast-path and recovery feasibility are proven. This is **not** full ingestion (that is M3). |
| M0-EX5 | Terraform, IAM, Secrets and CI are connected with no committed secrets. GitHub Actions has protected merge and a post-deploy smoke test. |
| M0-EX6 | Budget, free-tier, timeout and quota checks are documented, along with risks, blocked assumptions and requirement-to-test mapping. Reviewer and human approval come before merge. |

**Explicitly not in M0:** login, sessions, CSRF enforcement, Email OTP (M1, `../M1/plan.md`); documents, R2 usage, ingestion (M2/M3); chat and AI providers (M4). M0 only proves the foundations and the hosting topology those depend on.

## Readiness assessment
| Area | State | Note |
|---|---|---|
| Scope and exit criteria | Ready | M0-EX1..6 unchanged. |
| Acceptance criteria | Ready after approval | Reviewed and refined in `test-plan.md`: AC08 split into pre-merge and post-merge evidence, AC11 adapted to "no login in M0", AC12–14 added to cover M0 requirements that had no criterion (OPEN-20). |
| Task plan, dependencies, ownership | Ready | `tasks.md`. |
| Contracts | Defined as M0-01 deliverables | List below; nothing is frozen before M0-01. |
| Local implementation work (M0-01..04, M0-09, M0-10) | Can start on authorization | Needs no cloud credentials: local Compose, CI service containers and faked providers (TEST-09). |
| Cloud work (M0-05 apply, M0-06, M0-08) | **Blocked on user prerequisites** | Accounts, a bootstrap identity, spike deploy authorization and a domain (A3–A5 below). |

## Approvals required from the user
| # | Approval / action | Needed for | Recommendation |
|---|---|---|---|
| A1 | Approve the docs-only PR and explicitly authorize M0 implementation | everything | — |
| A2 | Approve OPEN-20 (the reconciliation-added M0 IDs and this plan's refinements) | M0 start | Approve with the refinements in `test-plan.md` (see "OPEN-20 recommendation" there). |
| A3 | **Spike deployment authorization.** AC02, AC04 (real delivery), AC08 (pre-merge), AC10 (deployed run), AC11 and AC12 need real cloud resources and deploys **before** the M0 PR merges. This conflicts with INFRA-04 (deploy only after an approved milestone PR) and with the AGENTS.md hard limits (no deploy, no infra apply) unless explicitly authorized. Options: **(a)** authorize `terraform apply` and hello-path deploys from the M0 branch to the single Production project during M0, as a recorded one-time bootstrap exception (ADR); **(b)** use a temporary spike project, destroyed after M0; **(c)** no deploy before merge, in which case the deploy-dependent ACs become post-merge evidence and M0 cannot prove feasibility before review. | M0-05 apply, M0-06, M0-08 | **(a)**: one environment (INFRA-01), only non-sensitive hello-path code, and every apply is recorded in the spike report. |
| A4 | **User-provisioned accounts and bootstrap.** Agents never create or hold cloud credentials (hard limit). The user provides: a GCP project with billing, a Cloudflare account (Pages), a Neon project, an Upstash QStash account, admin rights on the GitHub repo (branch protection, environments), and runs or approves the one-time bootstrap (Terraform state bucket, Workload Identity Federation for GitHub OIDC). The user enters secret **values** into Secret Manager / provider consoles; Terraform creates only secret containers and IAM. | M0-05 apply onward | Do this before M0 starts so the infrastructure critical path is not idle. |
| A5 | **Domain for the same-site topology** (OPEN-04): use an existing domain or register one, and accept its cost against OPEN-10. | M0-08 / AC11 only | Decide before M0-08; if declined, AC11 records the blocker and the alternatives for a user decision. |

## Repository structure (OPEN-18)
### Current structure (legacy, unchanged until M0-01)
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

### Planned M0 transition steps (M0-01)
1. Create the target skeleton and workspace/lockfiles (`uv`, `pnpm`) alongside the legacy folders.
2. For each legacy part, the Owner decides in an M0-01 ADR whether it is moved into the target layout (with `git mv`, preserving history) or rebuilt from the specs. Legacy behavior that conflicts with STACK-X (JWT, Celery/Redis, Chroma, gdown, WebSocket) is never carried into the target.
3. Until that ADR is executed, `backend/` and `frontend/` remain as LEGACY; their removal is an explicit, reviewed commit inside the M0 milestone branch.
4. Do not carry over committed binaries (`backend/app/chroma_data/`, `backend/app/static/docs/*.pdf`); their removal from the tree is an explicit, reviewed M0 change that preserves history.
5. Update `AGENTS.md` commands and the doc index when the new layout lands.

## Shared contracts (fixed in M0-01, before parallel work)
Owned by the Owner (approval and coordination, OPEN-01); implementation may be delegated. Each lives under `docs/contracts/`:
- API/OpenAPI baseline and the error envelope (ARCH-04, ARCH-05).
- Config/environment keys and the typed settings object (ARCH-12, `.env.example`).
- M0 DB schema (job, outbox, and pgvector feasibility table) and migration ownership (ARCH-11).
- Job envelope `{schema_version, job_id}` (ING-21) and the Worker/recovery-dispatcher endpoints, including which service hosts the dispatcher and how its invocation is authenticated.
- Structured logging fields and correlation-id propagation (MON-03).
- Health/readiness endpoints (ARCH-13).
- Deployment interface: image names, service names, required env/secret keys, smoke-test entry points.

The OpenAPI schema is generated from FastAPI and diffed against the approved contract in CI; TS types are generated with `openapi-typescript`. Contract changes after M0-01 need Owner approval and coordination with dependent workstreams (WF-03).

## Ownership and allocation
- **Owner**: plan, dependency graph, shared contracts, integration branch, quality gates, review package (WF-02).
- **Workstreams are allocated dynamically** from the dependency graph in `tasks.md` (WF-16): no fixed agent count. There is no permanent Shared Core Agent; the shared-core implementation is delegated to the backend workstream under Owner-approved interfaces.
- **Independent Review Agents** for security-critical and cross-cutting changes (`tasks.md` "Quality gates").

## M0-dependent open decisions
| Item | Investigate | Verified by | Evidence | Task | Blocks |
|---|---|---|---|---|---|
| OPEN-06 Terraform/provider feasibility | State backend and locking; GCP region for Cloud Run, Scheduler and Secret Manager; which resources the available Terraform providers can manage (GCP, Cloudflare, Neon, Upstash) and which need documented manual steps | `terraform validate` and `plan`, then an authorized apply (A3) | Spike report section listing each resource as managed or a manual gap, with plan/apply logs | M0-09 (research), M0-05 | Production deploy only; local implementation is not blocked |
| OPEN-09 Backup/restore | Backup/restore capability of the selected Neon plan; that R2 is not a versioned backup | Provider documentation (dated citations); a restore attempt only if the plan supports one | Spike report section without guarantees (INFRA-08) | M0-09 | Neither; production-readiness documentation only |
| OPEN-10 Cost | Current free tiers, pricing and quotas per service, plus the domain (A5); billing alerts | Dated provider pricing pages, then billing data from the spike period | Cost table separating **measured** from **estimated** values, with sources and assumptions (AC09) | M0-09, M0-07 | Not implementation; if over target, the user decides before go-live |
| OPEN-04 feasibility (decision resolved) | Custom-domain mapping for Pages and Cloud Run, TLS, cookie and CORS behavior | Deployed spike checks | AC11 evidence, or a documented blocker with alternatives | M0-08 | Blocks M1 production auth deploy, not M0 implementation |
| ING-22 Worker timeout | Cloud Run request timeout and limits vs expected job duration | Provider documentation + a measured run of the minimal job | Spike report entry and a decision note for M3 | M0-09, M0-04 | Neither in M0; informs M3 |
| OPEN-20 | — | User approval | — | — | M0 start |
| Owner-level details | Ephemeral CI DB, environment/bootstrap ADR, scheduler cadence, recovery-test shape | ADRs in M0-01/M0-05 | `docs/adr/` | M0-01, M0-05 | No |

No pricing, quota or capability figures are recorded in this plan; they are evidence produced by M0-09 and M0-07.

## Related docs
`tasks.md`, `test-plan.md`, `../../architecture/infrastructure.md`, `../../architecture/tech-stack.md`, `../../workflow/agent-workflow.md`, `../../workflow/testing.md`, `../../open-decisions.md`, `../M1/plan.md`
