# ADR 0008: M3 ingestion job model and chunk schema

Status: accepted by the Owner on 2026-11-13 (OPEN-31 D4, D5, D9, D13), contract implemented in M3-01.

## Context
M3 turns an uploaded PDF into searchable chunks. The job envelope carries only `job_id` (ING-21), the
Worker updates only `jobs`, and the claim ignores the attempt cap (plan findings F2 to F5, F7).

## Decisions
- **Revision to job link.** `document_revisions.job_id` (nullable, unique where set). The handler finds
  the revision from the job id. Seeded M2 revisions have no job until the reindex run.
- **Chunks.** `document_chunks` holds page-bound chunks with `embedding vector(1536)`. A composite
  foreign key ties a chunk to a revision of the same document. `(revision_id, ordinal)` is unique, so
  rewriting a revision's chunks is idempotent. There is no vector index in M3: retrieval uses an
  exact scan with the access filter applied first (SEC-08), and M4 chooses an index from measurements.
- **Retry from scratch.** No stage checkpoints. Writes are idempotent, the lease and attempt cap are
  enforced at claim time, every pipeline write is fenced on the job still being claimed by this
  worker, and publication is one transaction (D9).
- **Status consistency.** A terminal-failure hook marks the revision `failed` in the transaction that
  marks the job `failed`; a requeue hook sets it back to `queued`. Interfaces are in
  `knowserve_core/job_hooks.py`; M3-00a implements them.
- **Seed reindex.** For a revision that is already `ready` with no chunks, the handler writes chunks
  and the index identity and leaves status, pointer and ids alone. A failure never fails a ready
  revision (D4).
- **No stored outbox dead state.** `publish_failed` and `unpublished_stuck` stay derived (D13).

## Consequences
`0004` is additive, so application rollback needs no downgrade. Embedding is repeated on a retry, at
most three times per document. A vector index is a later migration.
