# M2 handoff (WF-12)

Status on 2026-11-08: M2 (Documents Library and Access) is merged to `main` and running in production. The milestone PR is [#32](https://github.com/BarakTubul/KnowServe/pull/32), merged on 2026-11-07 at 13:08 UTC as `2163ea8` after CI passed 8 of 8 checks on its last commit (`bb667b2`). Migration `0003` ran in production on 2026-11-08, the four demo documents are seeded, and the deployed smoke passed. The acceptance table is `traceability.md`; the task board is `tasks.md`.

## What is in production

| Area | State |
|---|---|
| Schema | Migration `0003_m2_documents` adds `documents`, `document_revisions` and `document_department_access`. It only adds tables, so the M1 revisions kept working against it. A composite foreign key keeps a document's current revision inside that document. |
| Visibility | One predicate, `visible_documents(department_id)` in `knowserve_core.documents_access`: not soft-deleted, current revision `ready`, and an access row for the active department. List, metadata and bytes all start from it. The owner column is a label and grants nothing. |
| 404 policy | Forbidden, unknown, deleted, not ready, no revision and malformed ids all return the same `DOCUMENT_NOT_FOUND` 404. |
| Library API | `GET /v1/documents` with search, owner filter and cursor paging (`created_at DESC, id DESC`, opaque cursor, page size 20 by default and 50 at most, no total count). A bad cursor or owner id returns a controlled 422. |
| Bytes and metadata | `GET /v1/documents/{id}` and `/content`. Bytes stream through the API from R2 with `no-store` caching. A single `Range` gives 206 and an unsatisfiable one 416. The Pages Function forwards `range` and `if-range`. Authorization is rechecked on every request, range requests included. |
| Object store | `ObjectStore` with `FakeObjectStore`, `FilesystemObjectStore` and `R2ObjectStore` (SigV4 over httpx). In production only `r2` is accepted, and the API refuses to start without the R2 settings. |
| Privacy (SEC-18) | No client IP is written to audit events or logs. The Demo rate limit keys on `demo:client:<HMAC-SHA256 of the address>` with a secret pepper (`KS_IP_HASH_PEPPER`, required in production). |
| Frontend | `/documents` library and `/documents/:id` PDF viewer (React-PDF), English and Hebrew with a selector, the choice kept in the browser. Only the M2 screens are localized. |
| Seed | Four fictional PDFs with varied department access, written by an idempotent command (`python -m knowserve_api.seed.documents`). |

Decisions are recorded in `docs/open-decisions.md` (OPEN-28 for Q1 to Q12, OPEN-29 for Q13, OPEN-30 for Q14) and `docs/adr/0007-m2-documents-schema-and-read-path.md`.

## Evidence

- CI on the PR's last commit: `python`, `frontend`, `openapi-drift`, `terraform-validate`, `secret-scan`, both `docker-build` jobs and `ci-required`, all passing, on PostgreSQL 18.6 with pgvector 0.8.6.
- Local runs before the merge: 564 Python tests, 174 frontend tests, and a 4-test browser flow against a mocked API (`pnpm --filter @knowserve/frontend e2e:library`).
- Independent reviews: CP1 (schema, predicate, 404 policy) and CP2 (list, bytes, R2 store, proxy). Neither found a blocking issue; the follow-ups were applied.
- Production deploy: `deploy` workflow run 42458802695 on `2163ea8`, after an `auth-check` run. Migration job execution `knowserve-migrate-k27qh` succeeded at 07:28 UTC. Revisions `knowserve-api-00009-5zf` and `knowserve-worker-00007-hqw` serve all traffic, and `/health/live` and `/health/ready` return 200 on both.
- Privileges: a read-only catalog query with the runtime role showed default grants of SELECT, INSERT, UPDATE and DELETE for `ks_runtime` on tables created by `neondb_owner`. After the migration the three document tables carry those grants.
- Seed: job execution `knowserve-document-seed-pwh2j` exited 0 and reported `created=4`. The job and its service account were removed afterwards.
- Deployed smoke (M2-AC16), `tests/e2e/deployed.library.spec.ts` against `https://knowserve-m0-spike.pages.dev` with real R2: a Finance Demo visitor sees the two documents Finance may read and not the other two. A full read returns a PDF, a `bytes=0-99` request returns 206, and an out-of-range request returns 416. No R2 host appears in the response headers. The viewer draws a PDF canvas. The two hidden documents and an unknown id return the same `DOCUMENT_NOT_FOUND` body on both routes.
- Demo cleanup (M2-AC19): the scheduled run on 2026-11-08 at 03:00 UTC authenticated through QStash. The first attempt returned 500 from Cloud Run (no instance available during a cold start, so the app never ran). QStash retried and the second attempt returned 200. The audit row `demo.cleanup.run` at 03:00:28 UTC records `batches: 0`, `deleted_users: 0`, `failed_batches: 0`, `capped: false` and `purged_rate_limit_counters: 1`. No Demo account had reached its 48-hour limit yet.

## Cloud changes made for M2

Each was approved separately and recorded in `tasks.md`.

1. Cloudflare R2 bucket `knowserve-documents` and a bucket-scoped token, created by hand.
2. Terraform: secret containers `r2-access-key-id`, `r2-secret-access-key` and `ip-hash-pepper`. The owner entered the three secret versions by hand.
3. Terraform: `secretAccessor` bindings for the API service account on those three secrets, and an in-place Cloud Run API update adding `KS_OBJECT_STORE`, `KS_R2_ENDPOINT`, `KS_R2_BUCKET` and the three secret references.
4. The `deploy` workflow run above (migration `0003`, API and Worker rollout, Pages).
5. Terraform: the seed job, its service account and three bindings were created, run once, and destroyed. A plan with the flag off shows no changes.

## Limits and known gaps

- A stream that fails after the response headers are sent ends early, with no error envelope. The viewer shows its load-failure message. This is an accepted limitation.
- Rate-limit rows become eligible for deletion 15 minutes after their window ends (about 75 minutes with the default 60-minute window). Deletion is lazy, so this is not a retention guarantee.
- Historical client IPs in production (OPEN-30) were checked and scrubbed on 2026-11-13, with the owner's approval. No address value was read or recorded. The procedure is in `docs/runbooks/open-30-historical-ip-check.md`.
  - Stage 1, read-only count as `ks_runtime`: it ran between 13:16 and 13:19 UTC. The exact time was not captured.
  - Backup: Neon branch `backup-open30-pre-scrub-20261113` (ID `br-withered-bread-b9ntw8p6`), a copy of `production`, created at 14:09 UTC, with auto-delete set to Never. The owner approved deleting it and it was deleted at about 14:12 UTC after the scrub was verified, so only `production` remains.
  - Scrub: one transaction as `neondb_owner`, started at 14:10:02 UTC and committed at 14:10:04 UTC. It repeated the count, ran `UPDATE audit_events SET ip = NULL WHERE ip IS NOT NULL`, got `UPDATE 21`, checked that the counts were 0 and committed.
  - Only `audit_events.ip` was changed. The `demo:ip:` counter rows were already 0, so no `DELETE` ran.

  | Check | Stage 1 | Before the scrub (14:10:02 UTC) | After the commit (14:10:04 UTC) |
  |---|---|---|---|
  | `audit_events` with a non-null `ip` | 21 | 21 | 0 |
  | `rate_limit_counters` with a key starting `demo:ip:` | 0 | 0 | 0 |
  | `audit_events` with `ip` or `client_ip` in `details` | 0 | 0 | 0 |

  With the backup branch deleted, the old addresses no longer exist in the application database or a Neon branch. There is no restore path for the 21 old `ip` values, which is the intent. Neon's 6-hour history retention on `production` may still cover the pre-scrub state for a short time.
- Real Firebase sign-in is not part of the M2 browser tests. The mocked-API flow and the deployed smoke (which uses a Demo visitor) cover M2; sign-in is covered by the M1 evidence.
- Localization covers the M2 screens only. The login, dashboard and other screens stay English.
- OPEN-22 (CI for docs-only changes) and OPEN-27 (approval-gated deploy workflow with the migration before deployment) are decided or approved in principle but not implemented. `deploy.yml` is unchanged and still runs only by manual dispatch.
- The deployed smoke runs by hand and is not in the PR gate.
- The production database holds four seeded documents and no others. The cold-start 500 on the scheduled cleanup (above) can recur while the Worker scales to zero; QStash's retry covered it.

## Notes for M3

- Seed documents were written directly, without chunks or an ingestion job. Per Q8, M3 must put them through the real ingestion pipeline with their document and revision ids preserved, not a separate path.
- The predicate is the only check that the current revision is `ready`. The database allows a current pointer at a revision in another status. M3 moves revisions through `queued`, `processing`, `ready` and `failed`, so keep the predicate on every user-facing path and in retrieval.
- `documents.updated_at` has no trigger. M3 must set it whenever it changes a document.
- Storage keys follow `documents/{document_id}/{revision_id}.pdf` and are never sent to clients.
- The Worker has no R2 access today (`secret_readers` gives the R2 secrets to the API only). M3 needs to add it.
- Retrieval must apply the same predicate in SQL before similarity (SEC-08).
- The Demo cleanup deletes users, and no M2 table references `users.id`. A future table that does must follow the ADR 0005 dependents rule.

## Open items

- OPEN-30 (historical IP data): the scrub is done and the backup branch is deleted (see Limits and known gaps). Still to decide: whether to close OPEN-30 in `docs/open-decisions.md`.
- Decide whether to implement OPEN-22 and OPEN-27. Both need separate approval.
- PR #31 (the Demo cleanup signature fix) was open when last checked, and the 2026-11-08 run it was waiting on has now authenticated.
- Q13 covers English and Hebrew for M2 only. A wider rollout is a separate decision.
