# M0 test plan

**Status:** Planned, **not started**. No test exists yet. This is the early test plan required by TEST-01, and it is updated during M0 as real edge cases appear. Tasks are listed in `tasks.md`, and approvals A1–A5 in `plan.md`.

## Test environments
| Environment | Used for | Providers |
|---|---|---|
| Local | Docker Compose: API, Worker, PostgreSQL+pgvector; Vite for the frontend | faked (TEST-09) |
| CI | Ephemeral Postgres+pgvector service container (strategy fixed by the M0-01 ADR) | faked |
| Deployed spike | The environment authorized under A3 | real Neon, QStash, Cloud Run, Pages (no Cloud Scheduler); no AI providers, R2 or Resend in M0 |

## Evidence stages
- **PR gate:** automated and blocking in CI on every merge into `m0/integration` and on the milestone PR.
- **Spike evidence:** produced once in the deployed environment and attached to the review package (logs, reports, screenshots of settings).
- **Post-merge:** can exist only after the user approves and merges the milestone PR. It is recorded in the M0 handoff, not the review package.

## Acceptance criteria
| ID | Acceptance criterion | Stage | Verification / evidence | Task | Covers |
|---|---|---|---|---|---|
| M0-AC01 | Dependencies install reproducibly from lockfiles | PR gate | CI logs of `uv sync --frozen` and `pnpm install --frozen-lockfile`; a drifted lock fails | M0-01, M0-10 | M0-EX1, STACK-35/36, ARCH-15, FE-ARCH-10 |
| M0-AC02 | The deployed frontend calls the deployed API and renders a successful health/status response | Spike evidence | Playwright smoke against the deployed URLs | M0-03, M0-06 | M0-EX2, INFRA-02, STACK-01 |
| M0-AC03 | The initial Alembic migration runs on an empty PostgreSQL+pgvector database, both in CI and on Neon; a vector column insert and a distance query succeed | PR gate + spike evidence | `alembic upgrade head` in CI; a pgvector round-trip test; the same migration in the deploy log for Neon | M0-02, M0-06 | M0-EX3, ARCH-11, STACK-11/12 |
| M0-AC04 | The Worker accepts a correctly signed delivery for an eligible job and rejects a missing or bad signature, or an unknown/ineligible job, before doing any work | PR gate + spike evidence | Integration tests with faked signing keys; one real QStash delivery in the deployed environment | M0-04, M0-06 | M0-EX4, SEC-14, ING-14, ING-21 |
| M0-AC05 | A duplicate or concurrent delivery of the same minimal job executes it at most once and acknowledges both | PR gate | Worker integration test with concurrent deliveries | M0-04 | M0-EX4, ING-10, ING-15 |
| M0-AC06 | The generated OpenAPI matches the approved contract, and the generated TS types compile | PR gate | CI contract diff + `tsc --noEmit` | M0-02, M0-03, M0-10 | ARCH-04, STACK-38, FE-ARCH-01 |
| M0-AC07 | Lint, format, type and test failures block merging to `main` | PR gate | Exported branch-protection settings; a throwaway PR showing each check type blocking | M0-10 | STACK-33/34, TEST-02, FE-ARCH-10/11 |
| M0-AC08 | The deploy workflow builds both images, deploys API, Worker and Pages, runs migrations and a post-deploy smoke; it does not run for unapproved or failing PRs | Spike evidence (manual authorized dispatch, A3) + post-merge (first deploy on merge of the M0 PR) | Workflow logs and smoke report; a negative run showing the gate | M0-06 | M0-EX5, INFRA-04, INFRA-05 (procedure) |
| M0-AC09 | Spike report: quotas, free-tier conditions, regions, cold starts, Cloud Run timeouts, QStash behavior, backup capability and monthly cost per service. Measured and estimated values are separated, with dated sources and assumptions, and billing alerts are configured manually by the user in the GCP console (Terraform manages no budget) | Spike evidence | `spike-report.md` reviewed; budget alert configuration exported by the user | M0-09, M0-05, M0-07 | M0-EX6, INFRA-03, INFRA-08, COST-01, COST-04 (alerts), ING-22, OPEN-06/09/10 |
| M0-AC10 | Outbox recovery by manual retry: a job + outbox row committed in one transaction whose immediate publish is lost (simulated API crash after commit) is discoverable as `unpublished_stuck`, and a manual retry publishes it exactly once; the job then runs once | PR gate + spike evidence | Integration test with crash injection; one deployed run using the operator surface with the test-only `skip_publish` hook | M0-04, M0-06 | M0-EX4, ING-12, ING-13, LIFE-09 |
| M0-AC11 | Same-origin API route feasibility (OPEN-21, no login in M0): through the Pages Function on the default `pages.dev` host, (a) SSE from `/api/v1/spike/stream` arrives incrementally for 30 to 300 s streams, (b) the spike test cookie is host-only, `Secure`, `HttpOnly`, `SameSite=Lax` and round-trips, (c) the API receives the real client IP in `X-KS-Client-IP`, (d) the Function request count fits the free quota; or a documented blocker with alternatives for the user | Spike evidence | Playwright `tests/e2e/proxy.spec.ts` against the deployed URL, response headers captured, quota dashboard screenshot | M0-08 | M0-EX2, M0-EX6, INFRA-11, AUTH-19, FE-ARCH-02 |
| M0-AC12 | No long-lived credentials or secret values in repo, CI or Terraform:<br>- CI deploys through GitHub OIDC / Workload Identity Federation<br>- each service reads its secrets from Secret Manager through its own least-privilege service account<br>- the secret scan passes, and the plan/state contains no secret values | PR gate (scan) + spike evidence | Secret-scan job; workflow auth logs showing no JSON key; IAM bindings export; review of plan/state for secret values | M0-05, M0-06, M0-10 | M0-EX5, INFRA-06, INFRA-07, ARCH-12 |
| M0-AC13 | The monorepo transition matches the approved plan:<br>- the target skeleton exists and builds<br>- an ADR records move vs rebuild per legacy part and the handling of committed binaries<br>- any legacy removal or move is a separate reviewed commit that preserves history<br>- `AGENTS.md` commands are updated | PR gate (review) | Review of the commits and ADR; `git log --follow` on any moved file | M0-01 | M0-EX1, OPEN-18, STACK-39, FE-ARCH-05 |
| M0-AC14 | Service baseline for API and Worker:<br>- liveness/readiness (readiness checks the DB)<br>- typed config with `.env.example`<br>- structured JSON logs with a correlation id propagated API → outbox → job → Worker<br>- no secrets in logs<br>- the error envelope on 404/422/500 without stack traces<br>- both services run locally with `docker compose up` | PR gate | Integration tests; log-capture test; Compose health check in CI or locally | M0-02, M0-04 | ARCH-05, ARCH-09, ARCH-12, ARCH-13, MON-03, MON-05, INFRA-01 |
| M0-AC15 | Direct-access protection (OPEN-21): the API returns 403 `DIRECT_ACCESS_DENIED` for any request without the proxy secret except `/health/*` (including unknown paths and preflights); the Function allow-lists `/api/v1/*`, drops spoofed `x-ks-*`, `x-forwarded-*`, `cf-*` and `host` headers, never leaks the secret, preserves all `Set-Cookie` attributes and passes SSE through unbuffered; the production API refuses to start without the secret | PR gate (API and Function tests) + local browser run; deployed run in the spike | M0-02, M0-03, M0-08 | AUTH-19, INFRA-11, SEC-13 |
| M0-AC16 | Terminal failure and retry: a handler that fails on every attempt (test-only `always_fail`) is released to `queued` with HTTP 500 for attempts 1-3 and is `failed` with a non-2xx at attempt 4 (`KS_JOB_MAX_ATTEMPTS`); a redelivery of a `failed` job returns `200 {"result":"failed"}`; a manual retry requeues it; a retry of a `done` job or one with an active lease is 409; of two concurrent retries one wins and the other gets 409; a stale outbox claim holder cannot overwrite a newer claim. QStash's real retry count and backoff vs 4 attempts is UNVERIFIED until a live test | PR gate + spike evidence | Integration tests (`test_ing_16_*`, `test_ing_13_*`); deployed run of the operator surface with failure hooks enabled in the isolated spike only | M0-04, M0-06 | M0-EX4, ING-13, ING-15, ING-16, ADM-16 |
| M0-AC17 | No unauthenticated job routes: with defaults the operator routes `/internal/spike/jobs` and `/internal/outbox/dispatch` return 404; when enabled they require a valid Google OIDC ID token (audience, `email_verified`, allow-listed email) plus the proxy secret; none is reachable through the Pages Function (`/api/v1/*` only); the routes are absent from the public OpenAPI | PR gate + spike evidence | Integration tests of mount flags and auth; a deployed negative check through the `pages.dev` host; ID tokens are minted by impersonating the role-less `ks-spike-operator` service account (a wrong-audience token and a token for a non-allow-listed identity, such as the personal account's own default token, must both give 401) | M0-02, M0-04, M0-06 | SEC-14, INFRA-11, ADM-16 |

## Evidence status (updated from actual runs; local only)
Legend: **PASS-LOCAL** = verified by the Owner on the local stack; this is not cloud evidence. **BLOCKED** = requires approved cloud access/deployment. Nothing here was run on GitHub or any cloud.

| AC | Status | Evidence / what is missing |
|---|---|---|
| M0-AC01 | PASS-LOCAL; CI run BLOCKED | `uv sync --frozen`, `pnpm install --frozen-lockfile` succeed locally. The workflow exists but has not run on GitHub. |
| M0-AC02 | BLOCKED | Needs deployed frontend + API. Local real Playwright spec passed against the local stack and a mocked spec exists; neither is AC02 evidence. |
| M0-AC03 | PASS-LOCAL; Neon BLOCKED | Migration + pgvector insert/distance tests on local pgvector/pg16. Not run on Neon. |
| M0-AC04 | PASS-LOCAL (simulated); live BLOCKED | Locally signed deliveries: valid/next key accepted; missing, bad, expired, wrong body/sub/iss, alg=none rejected. Real QStash signatures unverified. |
| M0-AC05 | PASS-LOCAL | 8 concurrent deliveries -> exactly one execution; redelivery is a no-op; expired lease reclaimed. |
| M0-AC06 | PASS-LOCAL | OpenAPI export equals baseline; `check:api` and `tsc` pass; drift proven to fail. |
| M0-AC07 | PARTIAL | Local gates fail on violations (lint/type/format/test; lint-failure proof). Required checks and branch protection are BLOCKED (user applies). |
| M0-AC08 | BLOCKED | Workflow authored, never run; needs A3/A4. |
| M0-AC09 | PARTIAL | `spike-report.md` has dated, sourced DOCUMENTED values and UNKNOWN items (spot-checked by the Owner, not every figure verified). Nothing is MEASURED: that needs the deployed spike. Billing alerts are config-only (not applied). |
| M0-AC10 | PASS-LOCAL (re-scoped); deployed BLOCKED | `test_m0_ac10_job_left_pending_after_api_crash_is_found_and_published_once` and `test_m0_ac10_api_crash_after_commit_then_manual_retry_completes` (crash after commit is listed as `unpublished_stuck`, a manual retry publishes it once, the job runs once); `test_call_paths.py` proves by AST analysis that only the flag-gated Worker route references the multi-row `dispatch_pending` and the immediate/manual paths use single-row claims; `test_m0_ac10_batch_dispatcher_is_not_mounted_by_default`. A simulated queue (`QStashSim`), not a live QStash. |
| M0-AC11 | BLOCKED (design approved provisionally) | Everything in the criterion is implemented and verified locally with workerd; Cloudflare's edge behavior, the real client IP and the free-quota fit need the deployed spike (A4). |
| M0-AC12 | PARTIAL | gitleaks over full history: no findings; no secret versions in Terraform (`check_no_secrets.py`); OIDC/Secret Manager behavior BLOCKED. |
| M0-AC13 | PASS-LOCAL (review) | Skeleton exists; ADR 0001 records rebuild-not-move; legacy folders untouched; history preserved. User confirmation pending on the committed legacy binaries. |
| M0-AC14 | PASS-LOCAL | Health/readiness (incl. 503), typed config, JSON logs with correlation id across API -> job -> Worker, error envelope without stack traces, compose stack healthy. |
| M0-AC15 | PASS-LOCAL; deployed BLOCKED | API: 15 guard tests (403 for missing, wrong or partial secret, unknown paths and preflights; health open; client IP trusted only after the check; production refuses to start without the secret; secret not logged). Function: 53 unit tests. Real browser run through the Workers runtime: direct access 403, health 200, SSE incremental, HttpOnly host-only Lax cookie hidden from JavaScript, secret absent from proxied responses. Not verified on Cloudflare's edge. |
| M0-AC16 | PASS-LOCAL; deployed BLOCKED | Core: `test_job_recovery.py` (18 tests: stale claim cannot mark or back off, timeout recorded as unconfirmed, every delivery state, republish vs requeue, simultaneous retries win once, done/active-lease/young rejected, requeue rolls back). Worker: transient failure answers 500 then succeeds, exhausted attempts become `failed` (500 `JOB_FAILED_PERMANENTLY` on the 4th, later redelivery 200 with no work), handler timeout counts as an attempt, zombie worker cannot complete a requeued job. E2E with the simulated queue: 4 deliveries with `always_fail`, manual requeue starts a fresh budget, a shorter queue retry count ends `queued_stuck` and is recoverable, duplicate and concurrent deliveries run once. QStash's real retry count vs `KS_JOB_MAX_ATTEMPTS=4`, and how an operator mints an ID token with the right audience, are UNVERIFIED spike items. `fail_then_ok` (B4, spike-only hook): `test_m0_ac16_fail_then_ok_exhausts_attempts_then_succeeds_after_manual_retry` (deliveries 500,500,500,500, then `failed`; manual retry; one 200; `done`; a further retry is 409), `test_adm16_manual_requeue_records_a_marker_and_keeps_the_previous_error`, and the hook-gating tests (403 without the flag, handler registered only with the flag). |
| M0-AC17 | PASS-LOCAL; deployed BLOCKED | `test_m0_ac17_*` (routes 404 unless enabled; enabling needs operators and audience; every route 401 without a verified allow-listed Google identity; proxy guard still applies and the proxy secret alone gives 401; hidden from OpenAPI; failure hooks refused unless enabled; open-job cap 429); Pages Function unit test `m0ac17_operator_job_routes_are_never_forwarded_by_the_public_proxy`; real processes (uvicorn + `wrangler pages dev`): direct without secret 403, with secret but no or garbage token 401 (real Google verifier), through the Pages Function `/api/internal/spike/jobs*`, `/api/v1/spike/jobs` and traversal variants 404, control `/api/v1/status` 200, no job rows created. Local workerd, not Cloudflare's edge; Google ID-token minting and live verification are UNVERIFIED. |

## Review of the earlier draft criteria (OPEN-20)
| Item | Finding | Change |
|---|---|---|
| M0-EX1..6 | Clear and consistent with the specs | Approve unchanged. |
| M0-AC01, 05, 06 | Clear and automatable | Unchanged (AC05 now also covers concurrent deliveries). |
| M0-AC02, 03, 04 | Valid but didn't say where the evidence comes from | Real-provider evidence is marked as spike evidence; AC03 states the pgvector round trip. |
| M0-AC07 | "Checks configured" can't be verified from code alone | Evidence is exported protection settings plus a blocking demonstration. |
| M0-AC08 | **Impossible as written for the review package**: "after an approved merge" can only happen after the PR is approved | Split into spike evidence (authorized manual dispatch, A3) and post-merge evidence recorded in the handoff. |
| M0-AC09 | "Prices documented" risked unsourced figures | Requires dated sources, measured vs estimated values, billing alerts and backups. |
| M0-AC10 | Superseded by the recovery decision (no Scheduler in M0) | Redefined to `unpublished_stuck` discovery plus manual retry; one deployed manual-retry run. |
| M0-AC11 | Assumed a login flow that M0 does not have; INFRA-11's test said "login from app." | Refined to a spike-only cookie-echo endpoint, off by default; INFRA-11's test aligned. A documented blocker is still an acceptable outcome. |
| Missing | No criterion covered OIDC/Secret Manager/no-secrets, the repo transition, or the service baseline (health, logging, error envelope, Compose), although those requirements are tagged M0 | Added M0-AC12, AC13, AC14. |
| Excessive for M0 | MON-06 error-rate and stuck-outbox alerts need real jobs; a rollback drill needs two real releases | M0 covers only billing alerts (AC09) and a documented rollback procedure (AC08). Operational alerts stay M3; a rollback drill is optional. |

**Recommendation:** approve OPEN-20 **with these refinements**, i.e. M0-EX1..6, M0-AC01..14 as above, and tasks M0-08..10. Reject nothing. The only criterion that would have been impossible (AC08) is fixed by its evidence split.

## Requirement traceability (M0-tagged requirements)
| Requirement | Acceptance |
|---|---|
| ARCH-01..03, ARCH-07 | Review in M0-02 handoff (structure is minimal in M0) |
| ARCH-04, STACK-38, FE-ARCH-01 | M0-AC06 |
| ARCH-05, ARCH-09, ARCH-12, ARCH-13, MON-03, MON-05 | M0-AC14 |
| ARCH-10 | M0-AC08 (two images), M0-AC13 (shared core has >1 consumer) |
| ARCH-11, STACK-11/12 | M0-AC03 |
| ARCH-15, STACK-33..36, FE-ARCH-10/11 | M0-AC01, M0-AC07 |
| FE-ARCH-02 (M0 part: credentials + base URL) | M0-AC11, M0-03 tests |
| FE-ARCH-04/06/08 (M0 part: setup only) | M0-03 component tests |
| FE-ARCH-05, STACK-39 | M0-AC13 |
| ING-10, ING-15 | M0-AC05 |
| ING-12, ING-13, LIFE-09 | M0-AC10 |
| ING-13, ING-15, ING-16, ADM-16 (M0 depth) | M0-AC16 |
| SEC-14 (job routes), INFRA-11 (operator routes not proxied) | M0-AC17 |
| ING-14, ING-21, SEC-14 | M0-AC04 |
| ING-22 | M0-AC09 |
| INFRA-01 | M0-AC14 |
| INFRA-02, INFRA-04, INFRA-05 | M0-AC02, M0-AC08 |
| INFRA-03, INFRA-08, COST-01, COST-04 (alerts) | M0-AC09 |
| INFRA-06, INFRA-07 | M0-AC12 |
| INFRA-09, MON-06 (M0 part) | M0-AC14 (logs), M0-AC09 (billing alerts) |
| INFRA-11, AUTH-19 (topology), FE-ARCH-02 (base URL) | M0-AC11, M0-AC15 |

Test names include the requirement or AC id (TEST-07), e.g. `test_ing_14_worker_rejects_bad_signature`.
