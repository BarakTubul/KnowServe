# M2 task board

**Status:** Plan approved on 2026-11-07 (OPEN-28, Q1 to Q12). Authorized now: local documentation and M2-PG. M2-01 and the other workstreams wait for the next checkpoint. Cloud, Cloudflare, Secret Manager, Terraform, production database, QStash, billing, deployment and merge actions need separate Owner authorization. The Owner keeps this board current at meaningful changes, not every commit (WF-10). Acceptance criteria M2-AC01..AC20 and the Definition of Done (M2-EX1..6) are in `plan.md`. Task ids follow the roadmap (A2); suffixes (`a`, `b`, `c`) and `M2-RB` are added by this plan.

## Board
| ID | Task | Depends on | Workstream | Size | Status |
|---|---|---|---|---|---|
| M2-00a | Demo Cleanup 401 fix. Cause found (QStash schedule destination host differed from the Worker's `KS_WORKER_PUBLIC_URL`); fixed in production. Handoff update is PR #31 (other session). Remaining: read-only verification of the 2026-11-08 03:00 UTC run (05:00 Israel time) | none | Owner | small | Pending Verification |
| M2-00b | M0-AC09 cost evidence: billing report for the idle project and Neon compute hours | none | Owner (user) | small | not started |
| M2-00c | R2 bucket (created manually, Q10), scoped access token, Secret Manager container, Terraform wiring of Cloud Run environment and secrets (existing Terraform) | none | Owner (user) | small to medium | not started; gates the deployed smoke and the production seed |
| M2-00d | Owner decisions Q1 to Q12 | none | Owner (user) | small | done 2026-11-07 (OPEN-28); Q13 and Q14 remain |
| M2-PG | CI and Compose to a PostgreSQL 18 pgvector image; run `0001`, `0002`; affected tests; ADR | none (first task, Q11) | Infra-PG | small to medium | done locally: PostgreSQL 18.6 + pgvector 0.8.6, migrations `0001`/`0002` and 434 tests pass; merged into `m2/integration`; CI run on GitHub pending a push |
| M2-CI | OPEN-22 decision, OPEN-27 proposal, E2E placement (docs only) | none | Owner | small | not started |
| M2-RB | Cloud Run rollback note including the `0003` compatibility check | M2-01 (schema known) | Owner | small | not started |
| M2-PRIV | No client IP in the application database or logs (SEC-18): stop writing `ip` to audit events, replace the `demo:ip:<address>` limiter key with a keyed hash and expire rows, remove IP logging paths, tests; read-only production count and a proposed scrub for approval | M2-PG (not M2-01) | Backend-Identity | small to medium | proposed, not started; needs the owner's go-ahead |
| M2-01 | Contracts and schema: migration `0003`, models, visibility predicate and tests, `ObjectStore` interface with `FakeObjectStore` and `FilesystemObjectStore`, OpenAPI for list (cursor pagination), metadata and bytes (Range), uniform 404 builder, error-code catalog contract, config keys, route stubs, frontend route stubs and generated types, ADRs | M2-PG merged; Q13 only for the localized catalog | Owner | medium | implemented locally on `m2/01-contracts` (not pushed, independent review pending): migration `0003`, models, `visible_documents`, `DOCUMENT_NOT_FOUND`, `ObjectStore` (fake, filesystem; R2 is M2-03), config keys, 501 route stubs, `openapi.json` and types, frontend route stubs, ADR 0007. Review CP1 accepted with follow-ups applied (ADR 0007 wording, `ByteRange` invariants, `0003` downgrade test, `Range`/`If-Range` in OpenAPI). Handed to later tasks: M2-02 controlled 422 for malformed owner filter and cursor; M2-03 startup guard for the object store after R2 wiring (fail clearly in production if missing or `fake`/`filesystem`; keep deployed M1 revisions starting), page validation after the visibility lookup, uniform 404 comparison excluding `request_id`, byte-range bounds against object size; M3 maintains `updated_at`. Open: error-code catalog contract, states-matrix fixture for the frontend, spec WF-15 updates |
| M2-02 | Library API: list with the predicate, search, owner filter, cursor pagination, 409, uniform 404 | M2-01 | Backend-Library | medium | not started |
| M2-03 | Bytes and metadata endpoints, `R2ObjectStore`, single-range 206/416, headers, proxy forwarding of `Range` and `If-Range`, production guard for store selection | M2-01 | Backend-Content | medium | not started |
| M2-04a | Frontend library page: list, search, owner filter, "Load more" cursor paging, states with friendly localized messages, department-keyed cache | M2-01 (mocks); M2-02 for e2e; Q13 | Frontend-Library | medium | not started |
| M2-04b | Frontend viewer: React-PDF, toolbar, `?page=`, neutral 404 view, friendly localized messages | M2-01 (mocks); M2-03 for e2e; Q13 | Frontend-Viewer | medium | not started |
| M2-05 | Deterministic PDF generator, committed small fictional PDFs, idempotent seed command, and the Cloud Run Job configuration (prepared for review, not applied) | M2-01 | Backend-Seed | small to medium | implemented locally on `claude/m2-05-seed-221b39`, awaiting integration; the production job is a proposal only |
| M2-06 | Integration, SEC hard gates, route walk, Playwright flow, independent review, traceability table, then deployed smoke and production seed | M2-02..05, M2-PG; smoke needs M2-00c and the migration approval | Owner + Review Agent | medium | not started |
| M2-07 | Handoff and the milestone PR | M2-06, M2-CI, M2-RB, M2-00a | Owner | small | not started |

## Dependency graph
See the Mermaid graph in `plan.md` section 10.

Critical path: Q answers, M2-01, M2-03, M2-06 (including the deployed smoke), M2-07. The cloud path (M2-00c, migration approval, production seed) can finish after the code; those answers and approvals are the biggest schedule lever.

## Parallel work and order
1. First: M2-PG (approved as the first task). M2-CI and M2-PRIV (once approved) can run beside it; the owner's cloud actions run beside everything. M2-00b and M2-00c are owner actions that run beside everything.
2. M2-01 starts after M2-PG merges into `m2/integration`. It is the only task on the critical path before the fork.
3. After M2-01 merges (CP1), these run in parallel in separate worktrees: M2-02, M2-03, M2-04a, M2-04b, M2-05. They share only the contracts fixed in M2-01. The M3 ingestion core may also fork here (roadmap section 2).
4. M2-RB can be written once the schema is known (after M2-01), beside the slices.
5. M2-06 waits for the five slices and M2-PG. The local half (integration, SEC gates, e2e) needs no cloud. The deployed smoke waits for M2-00c and the owner's migration approval.
6. M2-07 waits for M2-06, M2-CI, M2-RB and the confirmation of M2-00a.

Blocked until an answer arrives:

| Task | Blocked on |
|---|---|
| M2-01 | M2-PG merged |
| M2-04a, M2-04b (localized messages) | Q13 (languages) |
| M2-PRIV | the owner's go-ahead; production count and scrub need separate approval |
| M2-05 production run | IAM approval for the seed job, R2 token, migration `0003` approval |
| Deployed smoke and production seed | M2-00c (Q10), production migration approval |
| M2-00a closure | 2026-11-08 03:00 UTC run |

## Workstreams, file ownership and branches
The milestone branch is `m2/integration` in `worktrees/m2`. Each task gets `m2/<id>-<slug>` in `worktrees/m2-<slug>` (root rules; never elsewhere). The Owner uses a trial-integration worktree `worktrees/m2-trial` (WF-07). Branch names below are proposals.

| Workstream | Branch | Worktree | Owns (writes) |
|---|---|---|---|
| Owner (M2-01, M2-CI, M2-RB, integration) | `m2/integration` | `worktrees/m2` | `docs/contracts/`, `docs/adr/`, `docs/milestones/M2/`, migration `0003`, `knowserve_core` models, the visibility predicate and `ObjectStore` interface, `FakeObjectStore`, `app.py` registration, frontend route stubs, `openapi.json` and generated types, lockfiles at integration |
| Backend-Library (M2-02) | `m2/02-library` | `worktrees/m2-library` | `knowserve_api/documents/` list routes and their tests |
| Backend-Content (M2-03) | `m2/03-content` | `worktrees/m2-content` | `knowserve_api/documents/` bytes and metadata routes, the R2 adapter and development store, `functions/api/[[path]].ts` and `proxy.test.ts`, `docs/contracts/proxy.md` after Owner approval |
| Backend-Seed (M2-05) | `m2/05-seed` | `worktrees/m2-seed` | seed generator, seed data, the seed command |
| Frontend-Library (M2-04a) | `m2/04a-library-ui` | `worktrees/m2-library-ui` | `apps/frontend/src/features/documents/library/` and tests |
| Frontend-Viewer (M2-04b) | `m2/04b-viewer` | `worktrees/m2-viewer` | `apps/frontend/src/features/documents/viewer/` and tests; adds `react-pdf` (lockfile merged by the Owner) |
| Infra-PG (M2-PG) | `m2/pg18` | `worktrees/m2-pg` | `compose.yaml`, the CI database service in `ci.yml`, ADR 0002 update |
| Backend-Identity (M2-PRIV) | `m2/priv-no-ip` | `worktrees/m2-priv` | `audit.py` and its callers in `knowserve_api/auth/` and `demo/`, the rate-limit key code, log redaction, tests; no migration (a column drop is a separate contract change by the Owner) |
| Independent review | read-only | none | none |

Conflict rules: lockfiles and `openapi.json` are never hand-merged (rebase and regenerate); only the Owner writes migrations; contracts and config keys change only with Owner approval and notice to dependent agents first (WF-03). `ci.yml` is touched by M2-PG only, and any change to branch protection or `ci-required` needs the user's approval.

## Tasks

### M2-00a Demo Cleanup 401 fix
- **Objective:** close the M1-AC16 defect.
- **State:** Pending Verification. Diagnosed and fixed in production by the owner's session. The handoff text is in PR #31, which this milestone does not touch.
- **Verification (read-only), after the run on 2026-11-08 03:00 UTC (05:00 Israel time):** (1) QStash delivery or the Worker log shows a 2xx for `POST /internal/maintenance/demo-cleanup`; (2) the `demo.cleanup.run` audit event exists (owner read); (3) logs contain only operational counts and no unnecessary personal data.
- **Rules:** do not trigger another run, change QStash or change production. M2-AC19 is marked complete only with this evidence. If the run fails, the task stays open and the actual failure evidence is reported.
- **Acceptance:** M2-AC19.
- **Blocking risks:** none for code work.

### M2-00b Cost evidence
- **Objective:** M0-AC09: billing report for the idle project and Neon compute hours (OPEN-10).
- **Owner action:** Claude Code cannot read billing. The owner pastes the figures into the handoff.
- **Acceptance:** figures recorded in the M2 handoff or the M0 handoff update; user decision if over target.

### M2-00c R2 bucket and wiring
- **Objective:** a private R2 bucket the API and Worker can read, and the seed can write.
- **Owner actions:** create the bucket by hand in Cloudflare and a token scoped to that bucket (Q10; the bucket is not managed by Terraform), store the token in Secret Manager, approve the Terraform change for Cloud Run environment and secret wiring (existing Terraform), approve the production migration. Claude Code writes the exact bucket configuration (private, no public access, no custom domain, CORS not needed because bytes pass through the API) and the token permission list as an owner checklist, and performs any step it can safely do through its tools only after approval. Nothing in Git, Terraform state, logs or docs holds a credential value.
- **Deliverables from Claude Code:** the config key names and Terraform diff for review (M2-01 and an Infra pass); no apply.
- **Acceptance:** an object put by the seed is readable by the API in the deployed smoke.
- **Blocking risks:** token scope; Terraform coverage of R2 is unverified (spike finding F7), so a manual gap is recorded instead of a workaround.

### M2-00d Owner answers
- **Objective:** answer Q1 to Q12.
- **State:** done 2026-11-07, recorded as OPEN-28 in `open-decisions.md`. Q13 (languages, OPEN-29) and Q14 (production IP count) remain.

### M2-PG PostgreSQL 18 for CI and Compose
- **Objective:** match production's major version (D5, Q11).
- **Deliverables:** a PostgreSQL 18 pgvector image in `compose.yaml` and the CI service container, with the tag verified to exist before editing; migrations `0001` and `0002` run on it (and `0003` once it exists); the affected integration tests rerun; ADR 0002 updated with the compatibility notes. No local volume is deleted; if the PostgreSQL 18 image cannot use an existing PostgreSQL 16 data directory, the ADR says how to create a fresh database and the owner decides.
- **Acceptance:** M2-AC17.
- **Verification:** `docker compose up -d db`, `uv run alembic -c packages/backend_core/alembic.ini upgrade head`, `uv run pytest`, then `ci-required` green on the draft PR. Production Neon is not touched and earlier production probes are not repeated.
- **Integration point:** CP1b. Owner review.
- **Blocking risks:** a changed pgvector image tag; data directory layout changes in the PostgreSQL 18 image (existing local volumes may need recreation, which is stated in the ADR).

### M2-CI OPEN-22, OPEN-27 and E2E placement
- **Objective:** D2.
- **Deliverables:** a short decision note for OPEN-22 with the recommended option; a concrete OPEN-27 proposal (trigger, ordinary versus approval-gated jobs, WIF conditions unchanged, `needs` chain for dependent deploys); the E2E placement decision for the library flow (TEST-13). Docs only.
- **Acceptance:** M2-AC18. No workflow change, no branch protection change.
- **Blocking risks:** the user's approval for anything that changes `ci-required`.

### M2-RB Rollback note
- **Objective:** a controlled Cloud Run revision-rollback procedure written before the first production migration of M2.
- **Deliverables:** a short note under `docs/` (location chosen by the Owner, linked from `infrastructure.md`), covering revision rollback, the check that the previous revision works with `0003`, and that dropping `0003` is a separate decision.
- **Acceptance:** M2-AC20.

### M2-PRIV No client IP persistence (SEC-18)
- **Objective:** apply Q9 across the code that exists today.
- **Findings (read from the code, not run):** `audit_events.ip` is written by `audit.record(..., ip=...)` in the auth and Demo routes; `rate_limit_counters.key` holds `demo:ip:<address>`; the Pages Function forwards `CF-Connecting-IP` as `X-KS-Client-IP`; the audit logger does not log the address; a spike-only echo route can return it (off by default).
- **Proposed minimal remediation (code):** stop passing and storing `ip` in audit events (the column stays until a later contract migration drops it, because dropping it is a schema change and the running revision still reads the model); derive the limiter key from a keyed hash of the address (secret pepper from configuration) and expire counter rows after their window; never log the forwarded header; keep the proxy header because rate limiting needs it per request; remove the echo field or keep the route off in production.
- **Proposed remediation (existing production data), for the owner's approval:** (1) read-only count of `audit_events` rows with a non-null `ip` and of `rate_limit_counters` keys starting `demo:ip:`; (2) if any exist, a one-off scrub (`UPDATE audit_events SET ip = NULL`, delete or rehash the old counter rows) run through the migration job. No data is deleted and no production logging is changed without separate approval.
- **Acceptance:** M2-AC21; SEC-18, MON-04, MON-05, AUTH-15.
- **Verification:** audit rows written by each M1 path contain no address; a Demo start still returns 429 after the configured count; a log-capture test finds no address or forwarded-header value; no counter key contains an address.
- **Boundary:** Cloudflare and Google Cloud may process or retain IPs under their own policies; the docs do not claim otherwise.
- **Blocking risks:** the keyed-hash design (assumption 15) needs the owner's agreement.

### M2-01 Contracts, schema and shared interfaces
- **Objective:** freeze the minimal contracts so the slices run in parallel.
- **Deliverables:** migration `0003` (`documents`, `document_revisions`, `document_department_access`); models; the visibility predicate with its positive and negative tests; `ObjectStore` interface, `FakeObjectStore` and `FilesystemObjectStore` with the production guard; draft routes returning 501 (the list route with `limit`, `cursor`, `items`, `next_cursor`, `has_more`) and regenerated `openapi.json` and TS types; config keys in `docs/contracts/config-and-deploy.md`; the `DOCUMENT_NOT_FOUND` response builder; frontend route stubs; fixtures (document factory, access factory, states matrix); ADRs (schema and read path; object store); spec updates (WF-15).
- **Acceptance:** M2-AC14, the predicate half of AC01 to AC05; contract set approved by the Owner.
- **Verification:** `uv run alembic upgrade head` on an empty database and on `0002`; `uv run pytest`; `pnpm -r typecheck`; `check:api` shows no drift.
- **Integration point:** CP1; independent review required (schema, predicate, 404 policy).
- **Blocking risks:** M2-PG must be merged first; the cursor design (sort key, tiebreaker, validation) is decided here.

### M2-02 Library API
- **Objective:** the authorized list.
- **Deliverables:** `GET /v1/documents` using the predicate, `q` and `owner_department_id` filters, cursor pagination (`limit`, opaque `cursor`, `items`, `next_cursor`, `has_more`; filters and predicate before paging; stable order), 401 and 409 behavior.
- **Acceptance:** M2-AC01, AC02, AC04, AC05 (list), AC07, AC11 (list); DOC-01, 03, 05, 07, 08, 10.
- **Verification:** `uv run pytest -m "m2 and documents"`: states matrix (ready, queued, processing, failed, deleted, no current revision), owner-A allowed-B, org-wide with one row removed, search and filter intersection across pages (each document once, stable order), a tampered cursor, Admin without department, revoke between two pages.
- **Integration point:** CP2.

### M2-03 Bytes, metadata and delivery path
- **Objective:** protected PDF delivery, and the A7 verification.
- **Deliverables:** `GET /v1/documents/{id}/content` and `GET /v1/documents/{id}`; `R2ObjectStore` over the S3 API; the store-selection production guard; single Range with 206 and 416 and authorization on every request (Q2); response headers; `page` validation; proxy forwarding of `range` and `if-range` with a proxy test; a log-hygiene test.
- **Acceptance:** M2-AC03, AC05 (bytes and metadata), AC06 (with the Owner's route walk), AC08, AC09, AC11 (bytes); DOC-04, 05, 09, 10; SEC-02, 06.
- **Verification:** integration with `FakeObjectStore`: allowed, forbidden, unknown, deleted, not ready and malformed ids with identical 404 bodies; no storage host in any body or header; revoke then fetch; range matrix; proxy unit tests; `pnpm -r test`.
- **Integration point:** CP2; independent review required.
- **Blocking risks:** no R2 end-to-end evidence until M2-00c; Cloud Run and Pages Function streaming limits are unmeasured.

### M2-04a Frontend library
- **Objective:** the library page on the generated client.
- **Deliverables:** `/documents` with TanStack Query keyed by identity and active department, loading, empty, error and no-match states with friendly localized messages (FE-ARCH-14), search, owner filter from `GET /v1/departments`, a "Load more" button over the cursor API (cursor reset on filter, identity or department change), items linking to `/documents/:id`, cache clearing on switch and logout, a dashboard entry link. Existing flows with technical error text are listed as gaps, not rewritten.
- **Acceptance:** M2-AC07 (UI), AC10, AC13, AC22; FE-DOC-01 to 06, FE-DOC-10, PROD-06, PROD-13.
- **Verification:** `pnpm -r lint|format:check|typecheck|test|build`; component tests per the FE-DOC table; Playwright flow in the trial worktree.
- **Integration point:** CP3.

### M2-04b Frontend viewer
- **Objective:** the protected PDF viewer.
- **Deliverables:** `/documents/:id` with React-PDF loading bytes from the API URL with credentials, custom toolbar (page navigation, zoom), `?page=N` sync, header with filename and page, neutral not-available view on 404, inline notice for an out-of-range page (assumption 10).
- **Acceptance:** M2-AC12; FE-DOC-07 to 09, PROD-07.
- **Verification:** the same `pnpm -r` set; component tests (only the API bytes URL is requested; `?page=3` then next gives `?page=4`; 404 view); Playwright.
- **Integration point:** CP3.
- **Blocking risks:** the pdf.js worker asset under the Pages build and its `Content-Security-Policy` if one is set; `react-pdf` version choice.

### M2-05 Seed
- **Objective:** 3 to 5 fictional PDFs with explicit, varied access, for local use, tests, e2e and the deployed smoke (D1).
- **Deliverables:** a small deterministic PDF generator and the committed small generated PDFs; the idempotent seed command (deterministic ids, `ready` revisions with page counts, access rows, objects written through `ObjectStore`, no duplicates and no overwrite on rerun); the Cloud Run Job configuration for production seeding, built on the existing migration-job infrastructure with the smallest extension and only the permissions it needs, prepared for review and not applied; a note that DEF-01 is not expanded; owner steps for IAM, R2 credentials, Terraform apply and the single execution.
- **Acceptance:** M2-AC15.
- **Verification:** run twice locally with no change on the second run; integration test asserting the expected visibility per department; no chunks and no jobs created.
- **Integration point:** CP2.
- **Blocking risks:** R2 write credential and IAM approvals for the production run.

### M2-06 Integration, security gates and smoke
- **Objective:** evidence for the milestone PR.
- **Deliverables:** full CI in the trial worktree; the route-walk test (AC06); the identical-404 comparison across all causes; the Playwright flow (login with the emulator, switch department, list, open, `?page=`, forbidden view); the independent review summary; the TEST-03 traceability table for every M2-AC and M2-tagged requirement; after the owner's steps, the deployed smoke (AC16) and the production seed record.
- **Acceptance:** every M2-AC has evidence or an explicit gap; M2-EX1 to EX5.
- **Verification:** the Owner re-runs full CI in the trial worktree (WF-08).
- **Integration point:** CP4.
- **Blocking risks:** the deployed smoke needs M2-00c and the migration approval.

### M2-07 Handoff and milestone PR
- **Objective:** WF-12 handoff and the user's approval of the PR.
- **Deliverables:** `handoff.md` (implemented state, contracts, evidence, merged SHA, ADRs, limitations, notes for M3 including the Q8 dependency (seed documents go through the real ingestion pipeline with their document and revision ids preserved; no separate fake ingestion), the open M1 items that M4 still owns: CHAT-18 and CHAT-19); `open-decisions.md` updated; specs' "Current implementation / Known gaps" updated (WF-15); the M2 draft milestone PR opened by the Owner on the owner's say-so, carrying this plan, the planning docs and the two `m1/production-evidence` commits only if the owner decides so.
- **Acceptance:** M2-EX6.

## Requirement to task map
| Requirement | Task |
|---|---|
| DOC-01 (with cursor paging), DOC-07, DOC-08, FE-DOC-10 | M2-02, M2-04a |
| DOC-03, DOC-05, DOC-10 | M2-02, M2-03 |
| DOC-04, DOC-09 | M2-03 |
| SEC-02, SEC-06 | M2-01 (builder, predicate), M2-03, M2-06 (route walk) |
| SEC-04, SEC-05, SEC-07, LIFE-02 | M2-01, M2-02, M2-05 |
| SEC-09 (documents), SEC-10 (documents), SEC-17 (documents) | M2-02, M2-03, M2-04a, M2-06 |
| ARCH-11, ARCH-14, STACK-21 | M2-01, M2-03 |
| FE-DOC-01..06, PROD-05 (entry), PROD-06 | M2-04a |
| FE-DOC-07..09, PROD-07 | M2-04b |
| D1 | M2-05, M2-06 |
| D2 | M2-CI |
| D5, Q11 | M2-PG |
| SEC-18, MON-04, MON-05 (Q9) | M2-PRIV |
| PROD-13, FE-ARCH-14 (Q7) | M2-04a, M2-04b, M2-06 (gap list) |
| DOC-11 (Q2) | M2-03 |
| A7 | M2-03, M2-06 |

## Related docs
`plan.md`, `../ROADMAP.md`, `../M1/tasks.md`, `../M1/handoff.md`, `../../workflow/agent-workflow.md`, `../../workflow/testing.md`, `../../open-decisions.md`
