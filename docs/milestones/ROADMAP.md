# KnowServe roadmap, M0 to M6

Status: proposed on 2026-11-06 and updated on 2026-11-07 with the owner's roadmap decisions D1 to D5 and approved assumptions A1 to A8 (sections 9 and 10). It is a planning aid, not an approval of any milestone. Each milestone still gets its own plan, task board and user approval before work starts (WF-10, WF-13, WF-16), and this file does not change any requirement, contract or decision.

Sources: `../workflow/agent-workflow.md` (WF-14 for the milestone names), `../workflow/testing.md`, `../open-decisions.md`, the specs under `../backend`, `../frontend` and `../cross-cutting` (each requirement carries its milestone tag), and the M0 and M1 plans, boards and handoffs. Anything I inferred and did not find in those documents is marked "Assumption" and listed again in the last section, so the Owner can confirm or strike it. Requirement ids are cited as they appear in the specs.

## 1. Where we are

| Milestone | State | Reference |
|---|---|---|
| M0 Foundation, CI, IaC, deployment spike | Merged to `main`. The spike ran live and was cleaned up. Formal completion is not claimed: M0-AC09 (measured cost) is still open. | `M0/handoff.md`, `M0/test-plan.md` |
| M1 Authentication and Demo | Merged to `main` (PR #28). The production deploy, the migration job run and the Admin provisioning are recorded in the handoff on the unpushed `m1/production-evidence` branch and partly confirmed by the review in section 3. One accepted gap: conversion was not run on real Firebase. The first scheduled Demo cleanup was rejected on 2026-11-07 and is an open defect. The chat part of the quota evidence belongs to M4. | `M1/handoff.md`, OPEN-24 to OPEN-26 |

M0 delivered the monorepo, CI with the `ci-required` aggregate, Terraform, Cloud Run (API and Worker), the Pages `/api` proxy, Neon with pgvector, QStash and the transactional outbox with a manual-retry recovery path. The initial migration `0001` has only `jobs`, `outbox` and a spike probe table.

M1 delivered Firebase sign-in with opaque 24 h database sessions, CSRF and Origin checks, Try Demo through anonymous accounts, Demo to Registered conversion, departments with a stored active department, the single Admin guard, per-user quotas with a global AI guard and kill switch (mechanism only), the daily Demo cleanup, and the migration Cloud Run job. Migration `0002` added users, sessions, departments and counters. There are no document, chunk or conversation tables yet.

## 2. Dependency overview

| Milestone | Needs from earlier milestones | Can start before the previous one ends | Must wait for |
|---|---|---|---|
| M2 Documents Library and Access | M1 (identity, active department, Admin guard, errors, CSRF) | Yes, now, as soon as the roadmap is merged | M2-01 contracts frozen before its own slices fork |
| M3 Admin Upload and Ingestion | M2 schema and storage interface; M0 worker, outbox, QStash | Ingestion core and Admin API, after M2-01 merges | End to end "uploaded document shows in the library" needs M2 merged |
| M4 RAG Chat and Citations | M3 chunks and embeddings; M1 quotas; M2 visibility rules | Frontend against mocks, retriever SQL against fixture chunks, evaluation seed, after M3-01 merges | Real retrieval over ingested documents needs M3 merged |
| M5 Admin Lifecycle and Hardening | M3 ingestion; M4 for the chat halves of CHAT-13 and CHAT-15 | Delete cleanup and replace-version, after M3, in parallel with M4 when the work is independent (D3) | M5 merges after M4. Revocation during a live stream and citation history need M4 |
| M6 Evaluation and Production hardening | M4 (baselines), M5 | Evaluation dataset and hardening tasks that do not touch chat, from the middle of M4 | Approved baseline and final thresholds need the M4 pipeline stable |

```mermaid
graph LR
  M1[M1 done] --> M2[M2 library + access]
  M2 --> M3[M3 upload + ingestion]
  M2 -. schema contract M2-01 .-> M3core[M3 ingestion core]
  M3core --> M3
  M3 --> M4[M4 chat + citations]
  M3 -. chunk contract M3-01 .-> M4pre[M4 FE on mocks, retriever on fixtures, eval seed]
  M4pre --> M4
  M3 --> M5[M5 lifecycle]
  M4 --> M5chat[M5 chat revocation parts]
  M4 --> M6[M6 evaluation + hardening]
  M5 --> M6
```

Recommended order: M2, then M3, then M4, then M5, then M6, with early work started only where the table and the rules below allow.

Where milestones may overlap, stated plainly (approved as a flexible principle, A1):
1. Overlap follows dependencies, not the calendar. Each milestone plan names the stable contracts, the independent slices, the integration risks and the critical path, and starts early work only when it brings a real benefit. Parallel work is an opportunity, not a requirement.
2. M2 and M3 may overlap after the M2 document schema and storage interface merge (M2-01). The M3 Worker pipeline and Admin API can be built while the M2 library and viewer are finished. The M3 milestone PR waits until M2 is on `main`.
3. M3 and M4 may overlap on work that needs no real ingested data (frontend on mocks, retriever SQL on fixture chunks, evaluation seed). Real retrieval and the first usable demo wait for M3.
4. M4 and M5 may run in parallel where interfaces are stable and the work is independent (D3). M5 lifecycle work (ING-20 cleanup, ADM-15 replace) touches ingestion and storage, not chat. M4 merges before M5, and any M5 acceptance criterion that depends on chat (the M5 parts of CHAT-13 and CHAT-15, the hardening part of SEC-09) waits for the relevant M4 functionality.
5. M6 evaluation and operations work may start in the second half of M4, since EVAL-01, EVAL-06 and EVAL-10 already put a seed and deterministic checks in M4.
6. Milestone PRs merge in the order M2, M3, M4, M5, M6. Nothing overlaps at the PR level.

The cut lines above are planning aids (A1, A2). Each milestone's detailed plan is the authority (WF-16) and needs the owner's approval before work starts.

## 3. Carry-overs from M0 and M1

### M1 production evidence review (2026-11-07)
Method: the handoffs on `main`, the two unpushed commits on `m1/production-evidence` (`cf949dc`, `8be21c9`, handoff edits only), the GitHub run records, and a few read-only checks (a `gh run view` of the deploy run, a Cloud Run service description, and Cloud Logging reads of the Worker). I did not read secrets or the database, rerun a migration, trigger cleanup or change any resource. States are kept separate: configured, deployed, applied, exercised.

| Question | State | Evidence and limit |
|---|---|---|
| 1. Migration `0002` applied to production Neon | Recorded as applied, not re-queried | The branch handoff records `alembic_version` = `0002`, tables present and departments seeded, read during the cutover. The GitHub deploy run 42257551803 on `045f463` shows the migration step succeeded. I did not query the production database again, because that needs the secret and the evidence already exists. |
| 2. Cloud Run migration job executed successfully | Confirmed | Run 42257551803 (`workflow_dispatch`, conclusion success): the step "Database migration (Cloud Run job...)" succeeded and "Note skipped migration" was skipped. |
| 3. Signed QStash Demo cleanup schedule exists, 03:00 UTC | Recorded as created, not re-read | The branch handoff records schedule `knowserve-demo-cleanup`, `CRON_TZ=UTC 0 3 * * *`, read back on 2026-11-06. Reading it again needs the QStash token, an owner secret. The Worker logs show deliveries at 03:00 UTC on 2026-11-07, which is consistent with it. |
| 4. First scheduled cleanup completed successfully | Not successful: rejected | Cloud Logging for `knowserve-worker` shows four `POST /internal/maintenance/demo-cleanup` requests on 2026-11-07 (03:00:00, 03:00:22, 03:02:54 and 03:30:14 UTC), each answered 401 with the log line "rejected maintenance delivery with invalid signature". That matches one delivery plus three retries. Two earlier 401s on 2026-11-06 at 17:43 are the owner's unsigned tests. There was no successful run, so there are no cleanup counts to report. |

So the schedule fires and reaches the Worker, but the Worker rejects QStash's signature. M1-AC16 and the handoff's "still to observe" item are therefore a defect, not a wait. Unconverted Demo data is not being deleted. Retention is 48 hours (OPEN-25), so nothing harmful builds up quickly, but the daily cleanup does not work yet.

The cause is not established. Two candidates, both Assumptions to check. First, the schedule's destination URL may differ from the Worker's `KS_WORKER_PUBLIC_URL` (currently `https://knowserve-worker-866929656529.europe-west1.run.app`, while the service URL form is `https://knowserve-worker-ql7pu53csa-ew.a.run.app`), since QStash signs for the destination and the Worker verifies that URL. Second, the signing key versions in Secret Manager may not match the keys QStash uses. I could not tell which without the QStash token or the secrets.

Minimum next action (the first M2-00 task):
1. Owner: run `infra/qstash/demo-cleanup-schedule.sh show` and `check` with the token in the environment (both read only) and report the destination URL and schedule id. Claude Code cannot do this, because the token is an owner secret.
2. Claude Code: once the destination is known, compare it with `KS_WORKER_PUBLIC_URL` and the verifier in `apps/worker/src/knowserve_worker/app.py` and `packages/backend_core/src/knowserve_core/qstash.py`, and prepare a fix with a regression test.
3. Owner: approve and perform any schedule change (delete and create) or secret change. Both are cloud actions.
4. Observe the next 03:00 UTC delivery. Claude Code can read the Worker log. Reading the `demo.cleanup.run` audit row needs the owner, or a database read the owner approves.

### Carry-over placement

| Item | Placement | Source |
|---|---|---|
| M0 cost evidence (M0-AC09): billing report for the idle project and Neon compute hours | Owner action in M2-00, re-checked at M4 (OPEN-10). Claude Code cannot read billing. | `M0/handoff.md`, OPEN-10, COST-01 |
| Demo cleanup signature rejection (review above) | M2-00, first task. Fix, then observe one successful scheduled run | `M1/handoff.md`, SEC-14, AUTH-35 |
| CHAT-18 and CHAT-19, plus real chat-history preservation on conversion | M4 acceptance. They close M1-AC17 and the chat half of M1-AC15 | `M1/handoff.md` section 3, `backend/chat.md` |
| Conversion on real Firebase (accepted gap) | Stays accepted. The owner may run it when convenient. If conversion fails on production the endpoint fails closed (401) and the Demo session stays valid | `m1/production-evidence` handoff |
| OPEN-22 (CI/CD efficiency, docs-only PRs) | Addressed in M2 (D2, task M2-CI). Changes to branch protection or `ci-required` need the owner's approval, and `ci-required` must still fail on failed or cancelled jobs | `open-decisions.md` |
| OPEN-27 (automatic deploy after merge) | M2 prepares a concrete proposal (D2). Implementation is not a blocker and needs separate owner approval. The manually approved deploy path stays available | `open-decisions.md`, TEST-14 |
| Rollback note (Cloud Run revision rollback and schema compatibility check) | Written in M2, before the first production migration of that milestone | `testing.md` gap 4, INFRA-05, TEST-16 |
| PostgreSQL test environment (CI and Compose on 16, Neon on 18.6) | Moved to 18 during M2 (D5, task M2-PG). Approved as scope, not yet authorized to implement | `testing.md`, TEST-11 |
| M0 job-reliability gaps: attempts bound and dead state, stuck-job recovery, lease heartbeat | Bounded work at the start of M3 (A6, task M3-00a) | `M0/handoff.md` item 4 |
| Pin third-party GitHub Actions by digest, remaining review items | M6, unless a milestone needs one earlier (A5) | `M0/handoff.md` item 4 |
| Audit rows store client IPs, retention unconfirmed. FE-ARCH-09 (React Hook Form and Zod unused) | Retention in M2 planning. FE-ARCH-09 in M3, where the upload form needs RHF + Zod (FE-ADM-03) | `M1/handoff.md` section 4 |
| E2E placement: the auth Playwright flows are not in `ci.yml` | Decide in M2 (TEST-13). The library and viewer flow joins the smoke suite in M2 | `testing.md` gap 2 |
| Two unpushed commits on `m1/production-evidence` (`cf949dc`, `8be21c9`) | Not on `main` and not in PR #30. They change only `M1/handoff.md` and hold the production evidence used above. Intended to ride in the M2 PR. Neither pushed nor discarded here | `WORKTREES_STATUS.md` |

## 4. M2 Documents Library and Access

Goal: an authenticated user, or Demo visitor, sees only the ready documents their active department may read, and can open them in a protected PDF viewer. Authorization for documents is enforced and tested before any content arrives through ingestion.

In scope (requirements): DOC-01, 03, 04, 05, 07, 08, 09 (M2 part), 10; SEC-02, 04, 05, 06, 07, SEC-09 (documents part), SEC-10 and SEC-17 (document halves); LIFE-02 (library side); PROD-05 (library entry), PROD-06, PROD-07; FE-DOC-01 to FE-DOC-09. This includes the schema for documents, revisions and `document_department_access`, a private storage interface (R2) with a fake for tests, and the viewer with page deep links.

Also in scope (decisions D1, D2, D5 and assumption A7): a minimal seed of 3 to 5 fictional PDFs with explicit department access, used for the library, permissions, department switching, viewer and deployed smoke; the OPEN-22 decision and an OPEN-27 proposal; moving the CI and Compose test databases from PostgreSQL 16 to 18; verification of the private R2, Cloud Run API and Pages proxy delivery path.

Out of scope: uploading, ZIP import and ingestion (M3), chunks and vectors (M3), chat and citation deep links beyond the metadata endpoint (M4), delete and replace (M5). DEF-01 (a varied fictional corpus) stays deferred. The seed may supply initial M4 evaluation samples, but it is not the final Golden Dataset and is not corpus design.

Main tasks (sized like the M1 board)

| ID | Objective | Depends on | Workstream | Size |
|---|---|---|---|---|
| M2-00 | Owner actions and carry-overs: Demo cleanup signature defect (section 3), cost evidence, R2 bucket and token, rollback note, the schedule `show` check | M1 | Owner + user | small, but gates the deployed smoke |
| M2-CI | Decide OPEN-22 (D2). Write a concrete OPEN-27 proposal (trigger, ordinary versus approval-gated jobs, WIF conditions unchanged, `needs` chain for dependent deploys). No implementation without separate owner approval. E2E placement decision | M1 | Owner | small |
| M2-PG | Move CI and Compose PostgreSQL from 16 to 18 to match production, check pgvector compatibility, rerun migrations `0001` and `0002` and the affected integration tests, record the result in an ADR. Production Neon is not touched and earlier production probes are not repeated | M1 | Owner + Backend | small to medium |
| M2-01 | Contracts and schema: the next migration in sequence (documents, revisions, access rows), storage interface, OpenAPI for library, bytes and metadata, ADR for the read path | M2-00 not required | Owner | medium |
| M2-02 | Authorized read path: library query with SEC-07 visibility, search and filter, 404 policy, 409 without a department | M2-01 | Backend-Docs | medium |
| M2-03 | PDF bytes and metadata endpoints streaming from private R2 through the API and the Pages proxy: authorization, Range Requests and streaming as the viewer needs, headers, no existence leak. Fix only gaps that a test or smoke shows (A7) | M2-01 | Backend-Docs | medium |
| M2-04 | Frontend: library page, filters, empty and error states, viewer with toolbar, deep link `?page=`, neutral 404 | M2-01 (mocks) | Frontend | medium |
| M2-05 | Seed of 3 to 5 fictional PDFs with explicit, varied department access (one document visible to several departments, one to a single department), loadable locally and by a one-off owner-run command in production (D1) | M2-01 | Backend-Docs | small |
| M2-06 | Integration, SEC hard gates, Playwright smoke for the library flow, deployed smoke, independent review, traceability table | M2-02..05 | Owner + Review Agent | medium |
| M2-07 | Handoff and the milestone PR | M2-06 | Owner | small |

Parallel and waiting: M2-02, 03, 04 and 05 run in parallel after M2-01. M2-00 and M2-CI run beside everything. The deployed smoke waits for M2-00 (R2 and the seed). M3 ingestion core may fork after M2-01.

Acceptance criteria and evidence (to be numbered M2-AC01.. in the M2 plan)
1. A user sees only ready, non-deleted documents with a current revision for the active department: integration tests on real PostgreSQL (SEC-05, SEC-07, DOC-01).
2. Ownership never grants access: integration test with a document owned by A and allowed only to B (SEC-04).
3. Forbidden, unknown and not-ready documents return identical 404 (SEC-02, DOC-05): integration.
4. No active department gives 409 `ACTIVE_DEPARTMENT_REQUIRED` (DOC-03): integration.
5. Access revocation shows on the next request for list, bytes and metadata (DOC-10, SEC-09): integration.
6. Switching departments never shows the other department's documents (SEC-10): e2e.
7. The Admin sees the same library as any user in the regular library (SEC-17, OPEN-13): integration.
8. Viewer loads bytes only from the API, page navigation and zoom work (FE-DOC-07, 08): component plus e2e.
9. Deployed smoke through the Pages proxy reads a seeded document, including a Range request if the viewer uses one: smoke (TEST-15), no destructive writes.
10. CI and Compose run PostgreSQL 18 with pgvector, and migrations `0001` and `0002` and the affected integration tests pass: CI plus an ADR (D5).
11. OPEN-22 is decided and an OPEN-27 proposal is written: review.
12. One scheduled Demo cleanup run is accepted and logged with counts only: Worker log and audit event.

Security tests that start here: the SEC-02, 04, 05, 06, 07 matrix as hard gates; document half of SEC-10, 17; a route-walk test that every bytes or metadata route applies the visibility query (SEC-06); the 404 non-leak comparison.

Open decisions to resolve first: none block the start. OPEN-22 and OPEN-27 belong to M2-CI. OPEN-10 evidence (M0-AC09) is an M2-00 task. The seed question is settled by D1.

Owner actions by hand: run the QStash schedule `show` check and approve any schedule or secret change for the cleanup fix; create the R2 bucket and an access token and store it in Secret Manager (Cloudflare, Secret Manager); apply Terraform changes for storage wiring (separate approval); apply the migration through the migration job under the `production` approval; run the seed once; review the billing report. Migrations are numbered from the actual history (A4): the next one is whatever follows `0002` when M2-01 is written.

Risks: no R2 usage has been tested end to end (M0 excluded it), so range requests, streaming through the Pages Function and Cloud Run response size limits are unverified until M2-03; the PostgreSQL 18 move may expose pgvector or migration differences; the cleanup defect has an unknown cause until the schedule is read; the seed could be mistaken for the corpus work that DEF-01 defers.

## 5. M3 Admin Upload and Ingestion

Goal: the Admin uploads a PDF or ZIP, the Worker extracts, chunks, embeds and publishes it, the Admin watches progress, and a ready document appears in the library of exactly the departments chosen.

In scope: ADM-01 to 05, 07, 09 to 14, 16 to 18, ADM-08 (basic); ING-02, 05, 07, 09 to 13, 15 to 19, 22, 23; LIFE-01, 02, 03, 04, 05, 07, 09, 10, LIFE-06 (basic); SEC-11; MON-04 (admin audit) and MON-06 (job failure alerts); PROD-09 (upload part); FE-ADM-01 to 11 and 13, FE-ADM-08 (basic delete confirmation). Decisions in force: OPEN-16 (explicit access on upload and ZIP), OPEN-17 (`NO_EXTRACTABLE_TEXT`, replace of a failed document), ING-18 (OpenAI `text-embedding-3-small`).

Out of scope: replacing a ready document and full delete cleanup (M5, ADM-15, ING-20), OCR (DEF-02), Drive/gdown ingestion (removed, ADM-06).

Main tasks

| ID | Objective | Depends on | Workstream | Size |
|---|---|---|---|---|
| M3-00 | Owner actions and decisions: OPEN-05 (upload limits), embedding cost estimate, OpenAI key, R2 write access, QStash signing keys check | M2-01 | Owner + user | small |
| M3-00a | Bounded closure of the M0 job-reliability gaps at the start of M3 (A6): maximum attempts and dead state, stuck-job recovery, lease heartbeat where required. Reuse the proven outbox, lease and retry mechanisms. Admin-initiated manual Retry stays the default recovery. No new scheduler without separate owner approval | M3-01 | Backend-Worker | small to medium |
| M3-01 | Contracts: migration for chunks and vectors, job and stage model, SSE event schema, ZIP manifest schema, ADR for the vector index | M2-01 | Owner | medium |
| M3-02 | Worker pipeline `ProcessDocument`: R2 fetch, PyMuPDF4LLM extraction, LlamaIndex chunking, embeddings, atomic revision promotion, leases and bounded retries (the M0 leftovers are M3-00a) | M3-01 | Backend-Worker | large |
| M3-03 | Admin upload API: single PDF, validation (SEC-11), one-transaction document/job/outbox write, access rows, orphan cleanup | M3-01 | Backend-Admin | medium |
| M3-04 | ZIP import: manifest validation, read-only preview, idempotent confirmation, partial success | M3-03 | Backend-Admin | large |
| M3-05 | Admin list, access update, status SSE (Admin only), manual retry, failed-document replacement, audit events | M3-01 | Backend-Admin | medium |
| M3-06 | Frontend admin: list and status badges, upload form (RHF + Zod), ZIP preview and confirm, access editor, retry, failed replace | M3-01 (mocks) | Frontend | large |
| M3-07 | Integration, crash and duplicate-delivery tests, real QStash and OpenAI smoke, independent review, traceability | M3-02..06, M2 merged | Owner + Review Agent | medium |
| M3-08 | Handoff and the milestone PR | M3-07 | Owner | small |

Parallel and waiting: M3-02, 03, 05 and 06 run in parallel after M3-01. M3-04 follows M3-03. M3-07 needs M2 on `main` to prove "ready appears in the library".

Acceptance criteria and evidence
1. Upload to `ready` to visible in the library for the allowed departments only: e2e plus integration (LIFE-01, LIFE-05, ADM-03).
2. Non-Admin gets 403 and anonymous gets 401 on every admin route (ADM-01, SEC-03): integration.
3. Atomicity: a crash after commit and before publish loses nothing; duplicate delivery creates no duplicate chunks (ING-12, 15, LIFE-07, LIFE-09): integration with the QStash simulator, plus one live smoke (TEST-12).
4. Every job ends `ready` or `failed` with a reason within the attempt bound (ING-09, ING-16): integration.
5. Failed documents never reach library, viewer or retrieval and can be replaced (OPEN-17, ADM-18, LIFE-10): integration plus e2e.
6. ZIP rules: invalid entries flagged and never imported, valid ones confirmed once (ADM-11 to 14): integration.
7. Hostile files are rejected (SEC-11): integration.
8. Cost and time per document measured against COST-01 and OPEN-05: spike-style report.

Security tests that start here: SEC-11 upload validation (signature, size, ZIP bomb and path traversal, filename sanitization); SEC-14 signature check on the ingestion delivery path (already M0) re-run for new job types; ADM-01 and SEC-03 on every admin route; ADM-05 and OPEN-16 (no inferred access); no PDF content or secrets in logs (MON-05).

Open decisions to resolve first: OPEN-05 (M3 limits: file size, ZIP size and count, concurrency), the M0 job-reliability gaps, handled by M3-00a (A6). The PostgreSQL version is settled in M2 (D5).

Owner actions by hand: OpenAI API key into Secret Manager; spending limits on the OpenAI project; R2 write access for the Admin path; confirm QStash plan quotas against ingestion volume; Terraform apply and migration approval; first production upload with a real PDF.

Risks: Cloud Run request timeout against large uploads and long ingestion (ING-22); QStash retry behaviour against `KS_JOB_MAX_ATTEMPTS=4` is documented as unverified until a live test; pgvector index build on Neon free tier limits; PyMuPDF4LLM memory on a small Cloud Run instance (Assumption, no measurement exists); the largest milestone so far, so allocation by dependency graph matters (WF-16).

## 6. M4 RAG Chat and Citations (first usable MVP)

Goal: a user asks a question in the active department and gets a streamed, grounded answer with validated citations that link to the viewer. This is the first milestone a visitor can use end to end.

In scope: CHAT-01 to 05, 08 to 12, 14, 16 to 19, CHAT-13 and CHAT-15 (M4 part); SEC-08, SEC-09 (chat part), SEC-12, SEC-10 and SEC-17 (chat halves); COST-02 to 05, INFRA-10, MON-02; PROD-08, PROD-10; FE-CHAT-01 to 03 and 05 to 13; DOC-09 (citation deep links); EVAL-01 (seed), EVAL-02 (initial), EVAL-04, EVAL-05, EVAL-06 (deterministic and security gates), EVAL-10 (report). Decisions in force: OPEN-11 (history stays visible after revocation), OPEN-12, OPEN-13, OPEN-26 N1 (100 AI questions per UTC day plus kill switch).

Out of scope: final model and threshold choices (OPEN-02 final confirmation and OPEN-03 final are M6), hybrid retrieval or reranker (DEF-02), tracing platforms.

Main tasks

| ID | Objective | Depends on | Workstream | Size |
|---|---|---|---|---|
| M4-00 | Owner actions and decisions: OpenRouter key, provider spend limits, OPEN-02 benchmark plan and ADR, OPEN-03 starting values, OPEN-05 AI limits, global budget size | M3-01 | Owner + user | small |
| M4-01 | Contracts: conversations and messages schema (per identity and department), SSE chat events, citation payload, usage record, ADR; the dependents rule for Demo cleanup of chat tables | M3-01 | Owner | medium |
| M4-02 | Authorized Retriever: SQL applying SEC-07 before similarity, top_k, threshold, tested on fixture chunks first | M4-01 | Backend-Chat | large |
| M4-03 | Chat endpoint: LlamaIndex components, prompt rules (SEC-12), SSE streaming, stop, error events, citation validation, quota and budget reservation before any LLM call, kill switch behaviour | M4-02 | Backend-Chat | large |
| M4-04 | Conversations API and persistence, citation re-check on history (CHAT-15), revocation during a stream (CHAT-13) | M4-01 | Backend-Chat | medium |
| M4-05 | Frontend chat: list, composer, streaming parser, markdown without raw HTML, citations to the viewer, stop, unavailable state | M4-01 (mocks) | Frontend | large |
| M4-06 | Evaluation seed: initial samples that may use the M2 seeded PDFs (D1) but are not the final Golden Dataset, deterministic citation checks, security checks, report files | M3-01 | Evaluation | medium |
| M4-07 | Integration, real-model smoke, cost measurement, evidence for CHAT-18 and CHAT-19, independent review, traceability | M4-02..06, M3 merged | Owner + Review Agent | large |
| M4-08 | Handoff and the milestone PR | M4-07 | Owner | small |

Parallel and waiting: M4-04, 05 and 06 and the fixture-based part of M4-02 run before M3 is merged. Real retrieval, M4-07 and the quality of M4-06 samples wait for M3.

Acceptance criteria and evidence
1. Authorized retrieval: forbidden, deleted and not-ready chunks never come back, with a real pgvector query (SEC-08, CHAT-04): integration.
2. Citations are validated by the backend and map only to authorized retrieved chunks (CHAT-11): unit plus integration.
3. SSE order and the error path behave as specified, stop cancels upstream (CHAT-03, 10, 12): integration.
4. No active department gives 409 (CHAT-05); Demo conversations are isolated per visitor and department (CHAT-18, closes M1 evidence): integration plus e2e with the emulator.
5. Quota and budget are checked before any LLM call (CHAT-19, COST-02, 03, closes M1-AC17): integration.
6. Kill switch or exhausted budget gives a clear message and the library still works (CHAT-17, PROD-10): integration plus e2e.
7. Revocation: viewer blocked, citation loses link and content, history text stays (OPEN-11, CHAT-13, 15, SEC-09): integration.
8. Prompt injection and cross-department leak cases hard-fail (SEC-12, EVAL-05): eval.
9. Cost per answer within COST-01 and recorded (OPEN-02, OPEN-10): measured report.
10. Chat joins the Playwright smoke suite (TEST-13). Answer quality is judged only by the evaluation harness.

Security tests that start here: SEC-08 pre-filtering in SQL; SEC-12 instruction hierarchy and injection cases; CHAT-09 authorization only from the session; cross-conversation and cross-department isolation (CHAT-14, SEC-10); no prompt or answer text in logs beyond policy (MON-05); SSE through the proxy beyond 120 s is checked or the limit is documented.

Open decisions to resolve first: OPEN-02 (final chat model, by ADR from a benchmark), OPEN-03 (initial retrieval parameters; final in M6), OPEN-05 (AI limits and the global threshold), OPEN-10 re-check, and the Demo cleanup dependents rule for chat tables.

Owner actions by hand: OpenRouter key and credit limit; OpenAI key reuse check; Secret Manager entries; provider billing alerts (COST-04, manual by design); confirm the budget values; approve the first deploy.

Risks: model cost drift against $0 to 5 a month; streaming through the Pages Function beyond the verified 120 s; weak answers on a thin seeded corpus, since DEF-01 defers corpus design and the M2 seed is not the Golden Dataset; the conversion and cleanup race now touches chat history.

## 7. M5 Admin Lifecycle and Hardening

Goal: documents can be replaced, deleted and cleaned up safely, and the revocation story holds across library, viewer, retrieval and saved chats.

In scope: ADM-08 (full), ADM-15, ING-20, LIFE-06, LIFE-08, FE-ADM-08 (full), FE-ADM-12, PROD-09 (replace and delete), CHAT-13 and CHAT-15 (M5 part), SEC-09 (hardening part), and the security-review items the Owner chooses (Assumption: those from `M0/handoff.md` item 4 and `M1/handoff.md` section 4 that are not closed earlier).

Out of scope: user administration, versioned history beyond replace (PROD-11), OCR.

Main tasks

| ID | Objective | Depends on | Workstream | Size |
|---|---|---|---|---|
| M5-00 | Plan, decisions: retention of deleted objects and the cleanup cadence (touches OPEN-05) | M3 | Owner + user | small |
| M5-01 | Replace a ready document: candidate revision, atomic promotion, old revision served until then | M3 | Backend-Lifecycle | large |
| M5-02 | Soft delete plus durable asynchronous cleanup of objects, chunks and vectors, idempotent and bounded | M3 | Backend-Lifecycle | large |
| M5-03 | Frontend: replace dialog, full delete flow, status of cleanup | M5-01, 02 (mocks) | Frontend | medium |
| M5-04 | Revocation across chat: stream revalidation and history re-check on the full lifecycle | M4 | Backend-Chat | medium |
| M5-05 | Hardening review pass: independent review of upload, replace, delete and cleanup paths | M5-01..04 | Review Agent | medium |
| M5-06 | Integration, traceability, handoff and the milestone PR | all | Owner | medium |

Parallel and waiting: M5-01, 02 and 03 may start once M3 is on `main`, in parallel with M4 where interfaces are stable and the work is independent (D3). M4 merges before M5. M5-04 and every chat-dependent acceptance criterion wait for the relevant M4 functionality.

Acceptance criteria and evidence: old revision served until the new one is ready and a failed replacement changes nothing visible (LIFE-08, ADM-15): integration; delete blocks every path on the next request and cleanup later removes objects, chunks and vectors (LIFE-06, ING-20, ADM-08): integration; cleanup survives crashes and repeats: integration; revocation during a stream and in saved history behaves per OPEN-11 (CHAT-13, 15): integration; Admin actions are audited (ADM-17): integration.

Security tests that start here: cleanup never deletes a revision that is still current or a different document's object; replace cannot be used to widen access (ADM-05); race between delete and chat retrieval.

Open decisions: M5-00 items only (Assumption). M5 owns lifecycle-specific hardening and M6 owns cross-system hardening (A5). Owner actions by hand: approve the migration; check R2 deletion permissions and a lifecycle rule if used. Risks: asynchronous deletion that leaves orphaned vectors; replace racing with chat retrieval; this milestone changes the delete semantic that M3 shipped in basic form.

## 8. M6 Evaluation and Production hardening

Goal: quality and release readiness are measured and recorded, not assumed. Thresholds and the final retrieval settings are approved, and the production setup has rollback, backup limits and cost evidence written down.

In scope: EVAL-01 (full), EVAL-02, EVAL-03, EVAL-06, EVAL-07 to 10; OPEN-02 confirmation, OPEN-03 final, OPEN-08 (thresholds, sample counts, judge); PROD-10 (graceful AI degradation, final check); MON-06 and INFRA-08, 09 (alerts, backup limits, restore attempt, OPEN-09); OPEN-10 final cost report; the carry-overs OPEN-22 and OPEN-27 if they were deferred out of M2; action pinning by digest.

Out of scope: tracing, Sentry, antivirus, large admin system (DEF-02).

Main tasks

| ID | Objective | Depends on | Workstream | Size |
|---|---|---|---|---|
| M6-00 | Decisions: OPEN-08 thresholds proposal, judge model, final OPEN-03 values | M4 baselines | Owner + user | small |
| M6-01 | Golden dataset completion (human plus synthetic, verified samples) | M4-06 | Evaluation | medium |
| M6-02 | Retrieval and answer metrics, AI judge calibration, baseline report, immutable baseline file | M6-01 | Evaluation | large |
| M6-03 | Operations: rollback procedure exercised once, backup and restore attempt, alerts, cost report | M5 | Infrastructure | medium |
| M6-04 | Security and dependency pass: Actions pinning, remaining review items, a final independent review of the whole system | M5 | Review Agent | medium |
| M6-05 | Release smoke on production, final traceability for the whole project, handoff and the milestone PR | all | Owner | medium |

Parallel and waiting: M6-01 and M6-03 can start during M4 and M5. Baselines wait for stable chat. Acceptance and evidence: an approved baseline report with the thresholds applied (EVAL-07, 08); security cases still zero failures (EVAL-05); a recorded restore attempt or stated limitation (OPEN-09, INFRA-08); a measured monthly cost against COST-01 with a user decision if it is over; the rollback procedure exercised once and written down (INFRA-05, TEST-16). Real-model evaluation runs are opt-in and not part of PR gating (TEST-09, EVAL-06).

Security tests that start here: none new in principle; M6 re-runs every hard gate on the release candidate.

Owner actions: approve thresholds and baseline; run the opt-in evaluation with provider credit; approve the restore test and any production changes. Risks: evaluation spend; an AI judge that disagrees with humans (EVAL-03 needs human calibration); hardening scope grows without limit (WF-11 says debt is handled by risk).

The scope of "Production hardening" in the title is an Assumption. WF-14 names the milestone but no spec lists its tasks, so this section collects the items the docs already tag M6 or leave open for the end.

## 9. Approved decisions and assumptions (2026-11-07)

Decisions

| ID | Decision | Where it lands |
|---|---|---|
| D1 | M2 includes 3 to 5 fictional seeded PDFs with explicit department access, used to validate the library, permissions, department switching, viewer and deployed smoke. They may support initial M4 evaluation samples, are not the Golden Dataset, and do not expand DEF-01 | M2-05, M2 acceptance 9, M4-06 |
| D2 | OPEN-22 is addressed in M2. For OPEN-27 M2 prepares a concrete proposal, implementation is not a blocker and needs separate owner approval, the manual approved path stays, and the security and correctness gates are kept | M2-CI |
| D3 | Independent M4 and M5 work may run in parallel. M4 merges before M5. M5 chat-dependent criteria wait for M4. Parallel work is an opportunity, not a requirement | Sections 2 and 7 |
| D4 | Targeted read-only M1 production evidence review | Section 3 |
| D5 | CI and Compose PostgreSQL move from 16 to 18 in M2, validated against pgvector, existing migrations and affected tests. Production is unchanged. This is approved scope, not authorization to implement now | M2-PG |

Assumptions A1 to A8, all approved

| ID | Approved text, short form | Where it lands |
|---|---|---|
| A1 | Overlap is a flexible, dependency-based principle, decided in each milestone's detailed planning. Merge order stays M2, M3, M4, M5, M6 | Section 2 |
| A2 | Task ids, sizes and workstreams are preliminary planning aids. Each milestone plan owns the final allocation | All task tables |
| A3 | Approved as D1 | D1 |
| A4 | Migrations are numbered sequentially from the actual history. No fixed numbers are reserved for future milestones, and applied history is never rewritten | M2 owner actions |
| A5 | Security, integrity and reliability concerns are handled in the milestone where they arise. M5 owns lifecycle hardening, M6 owns cross-system hardening and release readiness. Essential protections are not deferred to M6 | Sections 7 and 8 |
| A6 | The M0 job-reliability gaps are closed in a bounded way at the start of M3. Manual Retry stays the default and no new scheduler is added without approval | M3-00a |
| A7 | M2 verifies the existing private R2, Cloud Run API and Pages proxy PDF delivery path (authorization, Range, streaming) and fixes only demonstrated gaps | M2-03 |
| A8 | Production migration and Demo cleanup state stay unverified until evidence supports them | Section 3 |

Items still unconfirmed:
1. M6 scope. No spec lists the tasks of "Production hardening", so section 8 collects items the docs tag M6 or leave open for the end.
2. R2 range requests and large PDF streaming through the Pages proxy are unverified until M2-03.
3. The cause of the Demo cleanup rejection (section 3) is unknown.

## 10. Owner questions

Answered: the seeded corpus (D1), OPEN-22 and OPEN-27 timing (D2), M4 and M5 ordering (D3), whether the migration job ran in production (confirmed, section 3), the PostgreSQL version question (D5).

Still open:
1. What is the destination URL of the QStash schedule `knowserve-demo-cleanup`, and do the Worker's signing key secrets match the keys QStash currently uses? Only the owner can check this, with the QStash token (section 3).
2. Should the two `m1/production-evidence` commits be pushed on their own now, or kept to ride in the M2 PR? The cleanup defect is not in that handoff yet, so the handoff needs one more edit before it is pushed.

## Related docs

`../workflow/agent-workflow.md`, `../workflow/testing.md`, `../open-decisions.md`, `M0/handoff.md`, `M1/handoff.md`, `M1/plan.md`, `M1/tasks.md`
