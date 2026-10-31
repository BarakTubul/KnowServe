# Document storage, admin operations and ingestion

## Storage / publication
- Private Cloudflare R2 S3-compatible object storage behind a small storage interface. No public document URLs or committed static PDFs.
- Document DB records carry owning department; explicit `document_department_access` controls read permission. `ready` and active revision required for user search/list/view.
- Single logical document may be replaced by a new revision: process replacement privately while prior ready revision remains served; atomically promote after successful complete index publication. On failure keep old revision. No end-user revision-history UI.
- Soft delete immediately blocks all user paths; durable asynchronous cleanup removes orphaned objects/chunks/index data eventually.
- Permission changes are immediate DB updates and **do not require new embeddings**.

## Admin submission
- Admin alone can upload individual PDF plus metadata and allowed departments.
- ZIP import contains PDFs and `manifest.json`: safe archive validation, references, metadata, allowed departments, sizes, count and paths checked. Preview is read-only; explicit confirm, idempotent confirmation, partial success per file with retry facilities.
- Remove previous Google Drive / `gdown` ingestion mechanism from target requirements.

## Worker lifecycle
- Real queue delivery through Upstash QStash, Cloud Run HTTPS Worker Service verifies QStash signature and checks valid eligible DB job. Worker processing remains independent from HTTP/runtime and can later move to Jobs if necessary.
- Durable **Transactional Outbox**: document/job/outbox saved in one PostgreSQL transaction; after commit attempt immediate publish, with Cloud Scheduler-triggered Recovery Dispatcher. Both paths coordinate claims/leases; no single-process fire-and-forget guarantee.
- Delivery is at-least-once; duplicated QStash delivery is possible. Atomic DB claim, leases, idempotency, checkpoints and bounded retry/backoff/cap ensure safe eventual progress. Avoid misleading exactly-once claims.
- Single `ProcessDocument(job_id)` orchestrates stages: secure PDF read, extraction (PyMuPDF4LLM), page-aware chunks (LlamaIndex SentenceSplitter), Embeddings via OpenAI, vector write to PostgreSQL/pgvector, atomic publish. Split into additional jobs only for demonstrated necessity.
- Base chunk config **512 tokens, overlap 64**, tuned by evaluation. Chunks do not span pages in MVP; retain document ID, revision and page number.
- DB is source of truth for `queued`, `processing` plus explicit phase, `ready`/`failed`; communicate meaningful stages through SSE, without invented progress percentages.
- Retries cannot accidentally publish partial index or duplicate final chunks; recover from crashes; exhausted failures allow manual retry.

## Scope sequencing
- M0 proves signed minimal QStash Worker request + one idempotency path and recovery feasibility. Do **not** overbuild M3 full ingestion in M0.
- M3 implements full upload, async processing and strong failure/recovery cases; M5 implements mature replacement/delete/lifecycle/hardening aspects per milestone plan.

## Required tests
- Invalid signature rejected; duplicate job delivery safe; outbox pending is recovered after publisher crash.
- ZIP unsafe filenames/symlinks/oversize/bad manifest rejected; partial success and retry are stable.
- Failed replacement preserves old readable revision; new revision visible only after complete publication; deleted/revoked docs fail closed.
