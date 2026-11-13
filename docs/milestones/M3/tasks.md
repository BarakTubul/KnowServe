# M3 tasks

Live status. Plan: `plan.md`. Decisions: OPEN-31. Integration branch: `m3/integration`.

## CP1: shared contracts (closed 2026-11-13)

The Owner approved the M3-01 contracts with these corrections, all applied:

- Upload and replace answer 202.
- A malformed, unknown or deleted document id is 404 `DOCUMENT_NOT_FOUND` on the Admin routes, after the 401 and 403 checks (`admin_document_id` dependency, tested).
- Idempotency, the status stream and the `can_retry` and `can_replace` rules are written out in `docs/contracts/admin-api.md`.
- Migration `0004` was checked: the same-document composite foreign key on chunks, unique `(revision_id, ordinal)`, nullable unique `document_revisions.job_id`, cascade from `users` (demo-cleanup rule), no vector index, and unchanged M2 rows after upgrade (test `test_m3_0004_upgrade_keeps_existing_m2_document_data`). Not run against production.

## Workstreams

| ID | Task | Branch | Status |
|---|---|---|---|
| M3-01 | Shared contracts, migration `0004`, stubs, fixtures, ADRs 0008 to 0010 | `m3/integration` | Done, CP1 closed |
| M3-00a, M3-02b, M3-02c | Worker reliability, ingestion handler, seed ingestion | `m3/w1-worker` | Started |
| M3-02a, M3-00b | Extraction, chunking, measurements | `m3/w2-extract` | Started |
| M3-03, M3-04 | Upload API, ZIP import | `m3/w3-upload` | Started |
| M3-05a, M3-05b | Admin management, SSE, replace | `m3/w4-manage` | Started |
| M3-06a, M3-06b | Admin frontend | `m3/w5-frontend` | Started |
| M3-09 | Terraform preparation (no apply) | `m3/w6-infra` | Started |
| M3-07, M3-08 | Integration, local trial, reviews, handoff | `m3/integration` | Not started |
