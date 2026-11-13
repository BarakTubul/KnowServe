# M3 handoff (WF-12)

Status on 2026-11-13: M3 (Admin Upload and Ingestion) is implemented and tested locally. It is not deployed. Nothing in this milestone has run against production, R2, OpenAI or QStash. The plan is `plan.md`, the decisions are OPEN-31 (D1 to D15) and the task record is `tasks.md`.

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

- Worker sizing comes from `measurements.md`: concurrency 1, memory 512 MiB and request timeout 300 s unchanged, `KS_PDF_EXTRACTION_TIMEOUT_SECONDS` 120 and `KS_JOB_HANDLER_TIMEOUT_SECONDS` 240. The rule that the handler timeout stays below the lease is gone because the heartbeat keeps the job claimed.
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

- M3-AC22 and M3-AC23 (a real upload on production, and a real large document on Cloud Run) need the cloud steps below.
- M3-AC25 (the D15 failure and recovery experiment) needs its own approval. The design is plan section 12.2. The runner is not written yet.
- Two clauses cannot be tested before M4 builds the retriever: no retriever query ever sees a non-ready revision (M3-AC07) and a query across a different index identity is refused (M3-AC09). The chunk tables, the visibility rules and the stored identity are in place.
- M3-AC01 is covered in pieces (upload, Worker pipeline, visibility) and by the local trial. There is no single automated test that runs upload, Worker and a second department's library view in one flow.

## Steps only the Owner can approve

These are listed in plan section 12.3. Each needs its own approval and none has been done.

1. Create the OpenAI project with the monthly budget and store the key as a Secret Manager version.
2. Create the two R2 tokens (API read, write and delete; Worker read only), check with a test object that the API token can delete, and store the values.
3. Check the QStash plan limits against the expected number of ingestion messages.
4. Review and apply the Terraform for M3-09 using `infra-apply-runbook.md`, which holds the order, the expected plan, the rollback and the cost.
5. Run the `auth-check` and then the `deploy` workflow. The migration job runs `0004` before the API and Worker roll out. The workflow has never run on GitHub, so expect to fix workflow problems.
6. Reindex the four seeded documents with the seed command.
7. Sign in as Admin on production, upload one small PDF, check the permitted and a non-permitted department, and check the upload limit once through Cloudflare and Cloud Run.
8. Approve the D15 experiment and its separate steps.

## Limits and known gaps

- A limit refusal in the middle of a ZIP confirmation is recorded as that entry's final result. A ZIP with more than 10 valid entries meets the default in-flight cap of 10.
- A forged session cookie passes the cheap cookie check in `body_limit.py`. The size cap still bounds the body, and the real authorization check follows.
- The status stream checks the session when it connects. After a logout it can stay open until `KS_SSE_MAX_SECONDS` (120 s).
- The Worker answers 500 for a terminal failure, so QStash redelivers up to three more times. Each redelivery finds the job `failed`, gets 200 and uses no attempt. D15 checks this on the real path.
- PyMuPDF4LLM is AGPL licensed and the tokenizer vocabulary is bundled in the repository (F16 and F17 in the plan).
- `docker compose up -d firebase-auth` exits with "Unable to obtain permissions for firebase-debug.log" because the configuration is mounted read-only. `tests/trial/README.md` describes the workaround. The compose file was not changed.
- The MON-06 alert filter matches any error log entry, so a retried transient failure can alert. Stuck outbox rows have no alert.
- Replacing a ready document and hard delete are M5. Retrieval and chat are M4.
