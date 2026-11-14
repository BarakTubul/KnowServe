# M3 handoff (WF-12)

Status on 2026-11-14: M3 (Admin Upload and Ingestion) is merged to `main` (PR #38) and deployed to production. The Owner created the OpenAI key and the Worker's read-only R2 token, the Terraform change was applied, and the `deploy` workflow ran migration `0004` and rolled out the images. The four seeded documents were reindexed through the Worker pipeline (`ingested=4`). The real upload check (M3-AC22) passed on the second attempt. The first attempt found a defect in the Pages proxy, which dropped the `Idempotency-Key` header, so every Admin upload answered 422. PR #39 fixed it and was deployed. M3-AC23 passed with a 300-page text PDF. M3-AC25 is still open. The plan is `plan.md`, the decisions are OPEN-31 (D1 to D15) and the task record is `tasks.md`.

## What the milestone adds

| Area | State |
|---|---|
| Schema | Migration `0004_m3_ingestion` adds `document_chunks` (with `vector(1536)` embeddings and no vector index), `admin_idempotency_keys`, `import_batch_entries` and a nullable, unique `document_revisions.job_id`. It only adds tables and a column, so the M2 revisions keep working against it. |
| Admin API | Eleven routes under `/v1/admin`: list, detail, access update, soft delete, retry, status stream, single upload, ZIP preview and confirm, replace of a failed document. Contract: `docs/contracts/admin-api.md`. Upload and replace answer 202. A partial ZIP import answers 200 with a result per file. A malformed, unknown or deleted document id is 404 `DOCUMENT_NOT_FOUND`, after the 401 and 403 checks. |
| Upload safety | Server-generated storage keys, in-memory ZIP reading, limits from D1 enforced while reading, a size and cookie guard on `/v1/admin/*` bodies (`body_limit.py`), `KS_UPLOADS_ENABLED=false` as a stop switch for every upload-producing route. |
| Idempotency | `Idempotency-Key` is required on create, replace and import confirmation and is scoped to the Admin and the operation. A replay returns the stored result, the same key with different content is 409, and a half-finished ZIP confirmation resumes through `import_batch_entries`. |
| Worker | Claim-time attempt cap, lease heartbeat, fencing on every pipeline write, terminal-failure and requeue hooks that keep the revision status equal to the job status, and the `ingest_revision` handler: extraction in a child process, chunks of 512 tokens with 64 overlap that never cross a page, OpenAI embeddings (the fake provider outside production), one publication transaction that checks `deleted_at`, and a reindex mode for ready revisions that have no chunks. |
| Seed ingestion | `knowserve_worker.seed_ingest` ingests the four seeded M2 documents through the same handler. It is safe to rerun and refuses production settings without `--allow-production`. |
| Frontend | `/admin/documents` for Admins: list with status badges, live status stream, access editor, delete, retry, single upload, ZIP preview and confirm, replace for failed documents. Error text comes from English and Hebrew catalogs typed on the generated error codes. |
| Infrastructure code | Terraform for a separate read-only R2 secret set for the Worker, the OpenAI key container, the new environment values, Worker concurrency 1, and an alert policy behind a flag that is off by default. It is validated and was never planned against state or applied. |

## Decisions taken during implementation

- Worker sizing comes from `measurements.md`. The Owner approved these as initial values: concurrency 1, memory 512 MiB, Cloud Run request timeout 300 s, `KS_PDF_EXTRACTION_TIMEOUT_SECONDS` 120 and `KS_JOB_HANDLER_TIMEOUT_SECONDS` 240. They rest on local measurements, so they are a starting point and not a production performance result. M3-AC23 stays open until the deployed Worker has processed a large, representative PDF (see the next section). The values are not to be changed or re-measured before then. The rule that the handler timeout stays below the lease is gone because the heartbeat keeps the job claimed.
- The Owner split two retriever clauses between M3 and M4 (see the next section). M3 does not contain a temporary retriever.
- The ZIP panel has no "retry the files that were not imported" button. Retrying the same ZIP under a new key would create the finished entries again, so the Admin imports a new ZIP that holds only the failed files.
- A missing source object fails the job as `INVALID_PDF` without retries. Embedding errors stay retryable.
- A missing OpenAI key or R2 setting in the Worker fails the attempt (`INTERNAL_ERROR`, retryable) and does not stop the Worker from starting, so the current deployment still boots before the secrets exist.
- Encrypted, over-page and image-only PDFs are accepted at upload and fail in the Worker, where the Admin can replace the file.

## Evidence

- Backend: 998 tests pass with no skips, on PostgreSQL 18 with pgvector and fake providers. Ruff, pyright and the OpenAPI drift check are clean.
- Frontend: lint, format, typecheck, build and 235 unit tests pass, the generated types match the OpenAPI snapshot, and the mocked Playwright admin spec passes.
- Local real-API trial (CP6): `tests/trial/` starts a queue stand-in next to the real API and Worker, and `tests/e2e/trial.admin.spec.ts` drives a browser through sign-in with the Firebase Auth Emulator, upload to ready over the live status stream, a failed upload and its replacement, ZIP preview and confirm, an access change and a delete. It passed twice, the second time on the final code. See `tests/trial/README.md`.
- Docker builds of the API and Worker images, `terraform fmt`, `init -backend=false`, `validate`, the Terraform secret check and gitleaks over the working tree pass.
- Independent reviews with their fixes applied: worker reliability, the ingest handler and seed command, upload and ZIP import, the Terraform changes, and a final cross-cutting review of authorization, log hygiene and spec consistency.

## Acceptance criteria that stay open

One production acceptance criterion is not met:

- M3-AC25: the D15 failure and recovery experiment, approved as designed in plan section 12.2 and kept as it is, except that its scenario 1 is dropped by the Owner (the `fail_then_ok` hook cannot succeed on an automatic redelivery, and the first retry of the cycle run shows the same redelivery). The runner is `tests/d15/run_d15.py` and the steps, the tagged revision and the restore are in `d15-runbook.md`. Neither has run against production. It needs its own approval for the exact steps.

Two criteria are split between M3 and M4 by the Owner's decision. The whole criteria are not deferred.

M3-AC07 ("a document that is `queued`, `processing` or `failed` never appears in the library, metadata, bytes or a retriever query over its chunks"):
- Done in M3: visibility, authorization and non-ready isolation in the library, metadata and bytes routes. Evidence: `test_m2_documents.py` and the Admin tests in `apps/api/tests`, the Worker publication tests in `test_m3_ingest.py`, all within the 998 backend tests, and the local trial.
- Moved to M4: the retriever query clause. M4 must show that the real retriever cannot return chunks from a non-ready, deleted or unauthorized revision. The M4 test is acceptance criterion 11 in the M4 section of `docs/milestones/ROADMAP.md`.

M3-AC09 ("a query across a different index identity is refused", with atomic publication, page-bound chunks, revision metadata and index identity storage):
- Done in M3: atomic publication in one transaction that checks `deleted_at`, page-bound chunks of 512 tokens with 64 overlap, and the embedding model and index identity stored per revision. Evidence: the chunking and publication tests, including `test_m3_ingest.py`.
- Moved to M4: the refusal clause. M4 must show that retrieval refuses to compare vectors across incompatible index identities. The M4 test is acceptance criterion 12 in the same ROADMAP section.

Other notes:

- M3-AC01 is covered in pieces (upload, Worker pipeline, visibility) and by the local trial. There is no single automated test that runs upload, Worker and a second department's library view in one flow.
- The completed M3 parts are supported by the evidence section above: 998 backend tests with no skips, 235 frontend unit tests, the mocked Playwright Admin spec, two local real-API trials (the second on the final code), the OpenAPI and generated type drift checks, the Docker builds, Terraform format and validate, the secret scans, and the independent reviews.

## Production acceptance record (2026-11-14)

M3-AC22 is met. The Owner ran these steps, each with its own approval.

- Setup: an OpenAI project with a 5 USD monthly budget and a key stored as a Secret Manager version (the service-account key form has no permission restriction, so the project budget is the cap). A read-only Worker R2 token scoped to the `knowserve-documents` bucket. The QStash free plan (1,000 messages a day, each delivery attempt counts) is far above the expected volume.
- Terraform: the targeted apply of the three secret containers and their bindings (6 added), then the full apply (2 changed, 0 added, 0 destroyed): the API got `KS_UPLOADS_ENABLED=true`, and the Worker got the R2 and OpenAI settings and concurrency 1. The plans matched the runbook before each apply.
- D6 check: with the repository's own R2 client, the API token wrote, read and deleted a probe object, and the Worker token read it but was refused a write and a delete (HTTP 403). The existing API token needed no replacement.
- Deploy: the `auth-check` run (43628831657) and the `deploy` run (43629003879) on `main` commit `75d483f`. The migration job ran `0004` and the images were rolled out.
- Seed reindex: a temporary Cloud Run job from the Worker image ran `knowserve_worker.seed_ingest --allow-production` once and reported `ingested=4`. The job was deleted afterwards and was never part of Terraform.
- First upload attempt: Admin uploads answered 422 because the Pages Function forwards an allowlist of request headers and `Idempotency-Key` was not on it. The local trial missed this because it used the Vite proxy. PR #39 added the header, and the `deploy` run 43631945442 on `3361588` rolled it out.
- Second upload attempt: the API accepted the sample PDF with 202 at 19:33:21 UTC, QStash delivered the job to the Worker, which claimed it on attempt 1 at 19:33:23, published 2 chunks at 19:33:33 and finished the job. The status stream connected for the duration. No errors or retries appeared in either service.
- M3-AC23 measurement (the Worker values stay as they are): a generated 300-page text PDF (3.6 MB, about 500 words a page, fictional) uploaded at 20:12:45 UTC was claimed on attempt 1 at 20:12:47 and finished at 20:14:17, so 90 s end to end against the 240 s handler timeout, and it produced 600 chunks. Peak Worker memory was about 292 MiB of 512 MiB (Cloud Run reports memory in coarse buckets, so this is approximate). A 19 MiB, image-heavy PDF with almost no text (1 chunk) took 12 s at about 205 MiB. The small two-page sample took about 10 s and 2 chunks. Embedding cost for the large file is estimated at under one US cent (at most about 307,000 tokens at the published `text-embedding-3-small` price; the exact count was not logged). Database growth is about 5 MB for 600 chunks, against the 1 GB Neon limit. No retry, timeout or error appeared. These are two documents on a warm instance, not a load test. The Owner required at least one large, representative document, and the result leaves about 2.7 times headroom on time and 1.75 times on memory.
- Owner-reported checks: the permitted department saw the document and opened its PDF, a department without access did not see it, a file over 20 MiB was refused with the friendly message in the form, a direct 21 MiB upload through the proxy was refused, and the test document was deleted.

## Steps only the Owner can approve

These are listed in plan section 12.3. Each needs its own approval. Steps 1 to 7 are done (see the record above). Step 8 is not.

1. Create the OpenAI project with the monthly budget and store the key as a Secret Manager version.
2. Create the two R2 tokens (API read, write and delete; Worker read only), check with a test object that the API token can delete, and store the values.
3. Check the QStash plan limits against the expected number of ingestion messages.
4. Review and apply the Terraform for M3-09 using `infra-apply-runbook.md`, which holds the order, the expected plan, the rollback and the cost.
5. Run the `auth-check` and then the `deploy` workflow. The migration job runs `0004` before the API and Worker roll out. Both ran on 2026-11-14 and passed.
6. Reindex the four seeded documents with the seed command.
7. Sign in as Admin on production, upload one small PDF, check the permitted and a non-permitted department, and check the upload limit once through Cloudflare and Cloud Run.
8. Approve the D15 experiment and its separate steps.

## Limits and known gaps

- A limit refusal in the middle of a ZIP confirmation is recorded as that entry's final result. A ZIP with more than 10 valid entries meets the default in-flight cap of 10.
- The local trial goes through the Vite dev proxy, so it cannot see header filtering in the Pages Function. The first production upload failed for that reason. A request header that a new route needs must also be added to the allowlist in `apps/frontend/functions/api/[[path]].ts` and to `docs/contracts/proxy.md`.
- A forged session cookie passes the cheap cookie check in `body_limit.py`. The size cap still bounds the body, and the real authorization check follows.
- The status stream checks the session when it connects. After a logout it can stay open until `KS_SSE_MAX_SECONDS` (120 s).
- The Worker answers 500 for a terminal failure, so QStash redelivers up to three more times. Each redelivery finds the job `failed`, gets 200 and uses no attempt. D15 checks this on the real path.
- PyMuPDF4LLM is AGPL licensed and the tokenizer vocabulary is bundled in the repository (F16 and F17 in the plan).
- `docker compose up -d firebase-auth` exits with "Unable to obtain permissions for firebase-debug.log" because the configuration is mounted read-only. `tests/trial/README.md` describes the workaround. The compose file was not changed.
- The MON-06 alert filter matches any error log entry, so a retried transient failure can alert. Stuck outbox rows have no alert.
- Replacing a ready document and hard delete are M5. Retrieval and chat are M4.
