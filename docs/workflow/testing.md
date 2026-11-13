# Testing strategy and traceability

**Status:** Approved process and target tooling. The target monorepo has backend, frontend and Playwright tests and a CI workflow (see "Current implementation (target tree)"); the legacy trees have no tests. The Testing & Deployment Policy (TEST-10..TEST-18 below) was approved by the user on 2026-11-06 and is adopted **incrementally**: nothing in it requires new infrastructure before the milestone that needs it.

## Requirements
| ID | Requirement |
|---|---|
| TEST-01 | Acceptance criteria produce an **early Test Plan** during milestone planning. Tests are written in parallel with the code, and the plan is updated for the edge cases actually found. |
| TEST-02 | Tests run in tiers: targeted tests while coding; cross-module integration tests at merge points; full CI tests, security tests and the relevant evaluation at the milestone PR; production smoke tests after deployment. |
| TEST-03 | The milestone **Review Package** has a requirement-to-test traceability table: requirement id, acceptance criterion, test path/type, actual CI result/evidence, positive/negative/error scenarios, uncovered gaps and quality-gate state. Critical functional, security or auth gaps block merge; non-critical gaps are shown for human decision. |
| TEST-04 | A **test impact map** is maintained manually per module and risk. There is no automatic impact engine. |
| TEST-05 | AI evaluation is progressive, per EVAL-06. Security checks are hard gates from day one (EVAL-05). |
| TEST-06 | Tooling: backend uses pytest, pytest-asyncio and HTTPX, with integration tests against **real PostgreSQL + pgvector** (not SQLite or mocks for permission SQL). Frontend uses Vitest + React Testing Library. E2E uses Playwright, staged by milestone. |
| TEST-07 | Test names or docstrings reference the requirement id they cover (for example `test_sec_02_forbidden_pdf_returns_404`). |
| TEST-08 | Every testable requirement has at least one positive test, and a negative or error test where applicable, listed in its spec's "Required tests" table. |
| TEST-09 | External providers (QStash, R2, OpenRouter, OpenAI embeddings, Firebase token verification) are faked in unit and integration tests. Real-provider calls happen only in deployment smoke tests and opt-in real-model eval runs. |

## Test levels used in specs
| Level | Meaning |
|---|---|
| unit | one function or class; dependencies faked |
| component | one React component/page with mocked API (Vitest + RTL) |
| integration | API/Worker via HTTPX against a real Postgres+pgvector; external providers faked |
| e2e | Playwright against the local Compose stack or a deployment smoke |
| eval | evaluation harness case (`../cross-cutting/evaluation.md`) |
| review / spike report | documented evidence, not automated |

## Testing and deployment policy (approved 2026-11-06)
This section is the policy. It sits on top of TEST-01..09 and does not replace them. Each row is a rule for how we work, not a claim that the tooling already exists; the sections after it say what exists.

### Merge gate (risk-based)
| ID | Requirement |
|---|---|
| TEST-10 | Every relevant PR passes the basic CI checks (the `ci-required` aggregate, `../contracts/ci-and-branch-protection.md`). On top of that, the PR adds or runs the tests its actual risk calls for: a schema change needs a migration test, an API contract change needs the OpenAPI drift check and contract tests, a UI flow change needs component tests and, if it touches a core flow, the E2E smoke. Changes to authorization, sessions, CSRF, secrets handling or document access need targeted positive **and** negative tests (the SEC-xx hard gates) before merge. Evidence that is still valid is reused: do not re-run or re-prove a check when the code it covered has not changed (cite the earlier run in the handoff). |

### Unit and integration tests
| ID | Requirement |
|---|---|
| TEST-11 | Unit tests cover isolated logic with dependencies faked. Database integration tests run against PostgreSQL + pgvector in Docker (local Compose `db`, CI service container), never SQLite or mocks for permission SQL (TEST-06). The Docker image tracks the production major version where practical; a known difference is recorded, not hidden (see "Deployment today vs the policy"). Migrations run on the local Docker database (`alembic upgrade head`, plus downgrade or forward-fix reasoning for rollback-sensitive ones) before they are applied anywhere in the cloud. Neon is used for tests only when provider-specific behavior, configuration or compatibility must be validated (for example pooled vs direct URLs, extension versions), and each such run is recorded as spike or release evidence. |

### External services
| ID | Requirement |
|---|---|
| TEST-12 | External services (QStash, R2, OpenRouter, OpenAI embeddings, Resend, Neon) are mocked in fast unit tests. Local integration flows use controlled substitutes where useful (for example the simulated queue `QStashSim` and signed test deliveries). Real-service tests run only when a change affects that service's behavior. They are not required for every PR or deployment. When a change does require one, it is completed **before** the release or operation that depends on it, and its evidence goes in the handoff. This refines TEST-09: real-provider calls stay out of PR gating. |

### End-to-end
| ID | Requirement |
|---|---|
| TEST-13 | Keep a small, stable Playwright smoke suite and grow it by risk and by what is implemented. Target core flows: authentication, document authorization, the document library and RAG chat. A flow joins the smoke suite in the milestone that implements it. RAG answer quality is not an E2E concern: it is validated through the evaluation strategy (`../cross-cutting/evaluation.md`). A full E2E run is not required for a minor change. |

### Deployment
| ID | Requirement |
|---|---|
| TEST-14 | Ordinary changes deploy automatically after a successful merge to `main`. Sensitive production operations need explicit human approval first: production database migrations, and infrastructure or security configuration changes (Workload Identity, IAM, secrets wiring, proxy/CORS/CSRF settings, Terraform apply). The existing GitHub `production` Environment approval and the restricted Workload Identity Federation trust (one repository, `refs/heads/main`, `deploy.yml`, the named environment) stay as they are. A dependent deployment (for example an API or Worker roll that needs a new migration, or a frontend deploy that needs a new API) must not bypass an approval gate its prerequisite needs: it runs in the same approved run or `needs` the approved job. There is no dedicated staging environment at this stage (INFRA-01, ADR 0003). **Not yet in effect:** see "Deployment today vs the policy" and OPEN-27. |
| TEST-15 | After each deployment, run lightweight, non-destructive smoke checks: service health (Pages proxy status, Worker readiness, direct-API denial) plus the functionality the release changed. No destructive writes, no bulk data, and no expensive or unnecessary external calls (no LLM or embedding call just to check health). |

### Failure and recovery
| ID | Requirement |
|---|---|
| TEST-16 | Recovery is a controlled, human-driven rollback, not automatic rollback machinery. For Cloud Run, route traffic back to an existing healthy revision when it is compatible with the current database schema (INFRA-05). Database rollback is decided separately from application rollback. Prefer backward-compatible migrations (expand first, contract in a later release) so the previous revision keeps working against the new schema. Before any rollback, check data integrity and compatibility; a rollback-incompatible migration is called out explicitly in its PR (INFRA-05). |

### Responsibilities and adoption
| ID | Requirement |
|---|---|
| TEST-17 | **Claude Code:** implementation and authorized local testing. **GitHub Actions:** automated checks and the configured deployment gates. **Human owner:** authorizes sensitive production and cloud operations. No unauthorized cloud mutations, secret access or production changes (AGENTS.md hard limits). |
| TEST-18 | Incremental adoption. The full testing infrastructure is not built up front. Each milestone adds the tests and tooling it needs. A milestone's Definition of Done includes: its acceptance criteria have the evidence the policy asks for (TEST-03 table), the risk-based tests of TEST-10 ran, security hard gates passed, and any policy-required real-service test or migration check is recorded. Review is targeted at integration points and the milestone PR. No extra PRs, frameworks or validation layers are added for their own sake. |

## Current implementation (target tree), from repository evidence
Read from the repository on 2026-11-06. Nothing was re-run for this document; "Evidence" points to recorded results.

| Capability | State | Evidence |
|---|---|---|
| Backend tests | Implemented: tests in `apps/api/tests`, `apps/worker/tests` and `packages/backend_core/tests`, run with `uv run pytest` against a real pgvector database | `ci.yml` job `python`; `../milestones/M0/test-plan.md` evidence table |
| Frontend tests | Implemented: Vitest via `pnpm -r test` | `ci.yml` job `frontend` |
| E2E | Partial: `tests/e2e/smoke.spec.ts`, `smoke.mocked.spec.ts`, `proxy.spec.ts`, and the M1 auth flows `auth.flows.spec.ts` (`pnpm --filter @knowserve/frontend e2e:auth`, default fake API, optional real API plus Firebase Auth Emulator, see `tests/e2e/README.md`). The smoke runs in the deploy workflow against the deployed URL. `ci.yml` does not run Playwright on PRs | `deploy.yml` last step; `tests/e2e/README.md`; `apps/frontend/package.json` |
| CI | Implemented and run on GitHub: format, lint, pyright, pytest, OpenAPI drift, frontend, docker build, terraform validate, gitleaks, one `ci-required` check | `ci.yml`; test plan AC07 |
| Branch protection | Implemented: PR and `ci-required` (strict) required, applies to administrators | test plan AC07 (verified live 2026-11-06) |
| Deployment | Implemented as **manual** `workflow_dispatch` from `main`: gate (`ci-required` on the same commit), GitHub Environment approval, WIF login, image build and push by digest, Cloud Run roll, Pages deploy, smoke checks. The workflow targets `production` since PR #27; the recorded positive and negative runs (M0-AC08) used the earlier `spike` environment | `deploy.yml`; test plan AC08; `../contracts/ci-and-branch-protection.md` |
| Post-deploy smoke | Implemented: Pages proxy `/api/v1/status`, direct API 403, Worker `/health/ready`, Playwright smoke | `deploy.yml` |
| Migrations | Local and CI migration tests exist (`0001`, `0002_m1_identity`). `deploy.yml` on `main` now runs migrations through the dedicated Cloud Run job `knowserve-migrate` before rolling API and Worker (skipped only if `RUN_MIGRATIONS` is `false`); the deployer reads no database credential. The job, its secret and the Neon roles were **authored, not yet applied or exercised** (M1 handoff: owner actions still pending), so cloud migration from CI is not yet verified | `deploy.yml`; `infra/terraform/gcp_migration_job.tf`; `../milestones/M1/handoff.md`; OPEN-26 (D2) |
| Rollback | Documented only (INFRA-05). No procedure is written down or exercised | `../architecture/infrastructure.md` |
| RAG evaluation | Not implemented; first checks arrive with chat (M4) | `../cross-cutting/evaluation.md` |
| Real-service tests | Only the M0 spike runs (QStash, Neon), recorded in the test plan | test plan evidence table |

## Deployment today vs the policy
- **Automatic deploy.** The policy says ordinary changes deploy after merge. Today they do not: `deploy.yml` runs only by manual dispatch, and the `push: main` trigger was disabled on purpose (security review M2). Enabling it is a separate decision that needs the user's approval (OPEN-27). Until then the manual, approved dispatch is the only deploy path.
- **Approval model.** The `production` Environment has a required reviewer, so as configured every run waits for approval, including ordinary ones. The user decided on 2026-11-13 to keep one approved `deploy` job with one click, where each rollout, Pages and smoke step runs only if the migration (or the step before it) succeeded. Automatic `push: main` deploy stays out of scope.
- **PostgreSQL version.** CI and Compose use `pgvector/pgvector:0.8.6-pg18` since M2-PG (ADR 0002, OPEN-28 Q11), matching the Neon database verified in the M0 spike (PostgreSQL 18.6, pgvector 0.8.6, test plan AC03). Neon-only behavior stays release evidence (TEST-11). Before M2-PG the images were `pg16`.

## Gaps for the current and next milestone
Only what M1 (Authentication & Demo, `../milestones/M1/plan.md`, `tasks.md`, `handoff.md`) still has open. The M1 handoff reports its backend and frontend auth tests as written and passing locally; the milestone PR review decides whether the criteria are met.
1. **Auth security evidence.** The M1 hard-gate tests (token verification, CSRF/Origin, authorization, log hygiene) exist on `main`. Their results at the milestone PR are the evidence (TEST-03 table); this document does not restate them.
2. **E2E placement.** The auth Playwright flows exist but are not run by `ci.yml`. Decide whether they join the PR gate or stay a local and release-time check (TEST-13); do not add a larger suite. Real-Firebase smoke (Google, mail delivery, password policy) is a one-time pre-release real-service test (TEST-12, OPEN-25).
3. **Migration job verification.** Apply the migration job, secret and Neon roles (Owner approval, TEST-14), then record one verified run before the first production migration. Until then treat cloud migration as unproven.
4. **Rollback note.** Write a short Cloud Run revision-rollback procedure, including the check that the previous revision works with the current schema, before the first migration reaches production.
5. **Auto-deploy decision.** OPEN-27, together with OPEN-22, before the deploy trigger changes.

## Overlap with OPEN-22 (CI/CD efficiency and change policy)
OPEN-22 was decided by the user on 2026-11-13 (docs-only PRs skip the five heavy jobs, `m0/**` trigger dropped). See `contracts/ci-and-branch-protection.md`.
- TEST-10 (risk-based gate, reuse valid evidence) fits OPEN-22(b): a docs-only PR may need only the quick jobs. Any such narrowing must keep `ci-required` failing on failed or cancelled jobs, and the deploy gate must still see `success` on the deployed commit.
- OPEN-22(a) drops the `m0/**` push trigger. TEST-10 assumes a PR-run check, so the two are consistent.
- TEST-14 depends on the same CI triggers and on `ci-required` semantics. Any change to either goes to the user, as OPEN-22 already says for branch protection.
- Branch protection is unchanged: the required check stays `ci-required`.

## Current implementation (LEGACY)
- There are no backend or frontend tests. A `tests/` tree existed earlier in git history and was deleted.
- `pytest-asyncio` is configured in `pytest.ini` but is not in `requirements.txt`.
- The frontend has no test runner, only `npm run lint`.

## Related docs
`agent-workflow.md`, `../cross-cutting/evaluation.md`, `../architecture/infrastructure.md` (INFRA-04/05), `../contracts/ci-and-branch-protection.md`, `../milestones/M0/plan.md`, `../milestones/M1/plan.md`, `../open-decisions.md` (OPEN-22, OPEN-27), `../README.md`
