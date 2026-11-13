# M3 tasks

Live status. Plan: `plan.md`. Decisions: OPEN-31. Integration branch: `m3/integration`.

## CP1: shared contracts (closed 2026-11-13)

The Owner approved the M3-01 contracts with these corrections, all applied:

- Upload and replace answer 202.
- A malformed, unknown or deleted document id is 404 `DOCUMENT_NOT_FOUND` on the Admin routes, after the 401 and 403 checks (`admin_document_id` dependency, tested).
- Idempotency, the status stream and the `can_retry` and `can_replace` rules are written out in `docs/contracts/admin-api.md`.
- Migration `0004` was checked: the same-document composite foreign key on chunks, unique `(revision_id, ordinal)`, nullable unique `document_revisions.job_id`, cascade from `users` (demo-cleanup rule), no vector index, and unchanged M2 rows after upgrade (test `test_m3_0004_upgrade_keeps_existing_m2_document_data`). Not run against production.

## Workstreams (local implementation done 2026-11-13)

All slices are merged into `m3/integration`. Each had its own worktree and branch (`m3-w1-worker` to `m3-w6-infra`, kept, not deleted).

| ID | Task | Status |
|---|---|---|
| M3-01 | Shared contracts, migration `0004`, stubs, fixtures, ADRs 0008 to 0010 | Done, CP1 closed |
| M3-00a | Worker reliability: lease heartbeat, claim-time cap, fencing, hooks | Done, independently reviewed, review fixes applied |
| M3-00b | Local measurements (`measurements.md`) | Done; sizing decisions recorded there |
| M3-02a | Extraction in a child process, page-bound chunking | Done |
| M3-02b, M3-02c | Ingest handler, OpenAI provider, reindex mode, seed command | Done, independently reviewed, review fixes applied |
| M3-03, M3-04 | Upload, creation service, ZIP import | Done, independently reviewed, review fixes applied |
| M3-05a, M3-05b | Management, status stream, replace | Done, covered by the final review |
| M3-06a, M3-06b | Admin frontend | Done; the ZIP retry button was removed after the final review |
| M3-09 | Terraform preparation | Done, independently reviewed, review fixes applied. Not planned or applied |
| M3-07 | Integration and review | Local trial passed (CP6). Final review done, fixes applied. Full CI run locally (below) and on GitHub |
| M3-08 | Handoff and milestone PR | Handoff doc and PR |

## Evidence (local, 2026-11-13)

- Backend: `uv run pytest` 991 passed, no skips (the later review fixes add tests); ruff, pyright and the OpenAPI drift check clean.
- Frontend: `pnpm -r lint|format:check|typecheck|test|build` and `check:api` clean; mocked Playwright admin spec passes.
- Local real-API trial (CP6): `tests/trial/` harness and `tests/e2e/trial.admin.spec.ts` passed against the real API and Worker with the Firebase Auth Emulator, a local queue stand-in, a filesystem object store and fake embeddings.
- Docker builds of `api` and `worker`, `terraform fmt`, `init -backend=false`, `validate`, the Terraform secret check and gitleaks over the working tree all passed.
- Not run and not authorized: production migration, deploy, `terraform apply`/plan against state, OpenAI/R2/QStash configuration, production reindex and upload checks, the D15 experiment.
