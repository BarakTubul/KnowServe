# Jobs, outbox and Worker contract (M0)

Requirements: ING-10, ING-12..15, ING-21, SEC-14, LIFE-09. M0 proves the mechanism with a no-op job; real ingestion is M3.

## Tables (initial migration `0001`, `knowserve_core.models`)
- `jobs`: `id` uuid, `job_type`, `status` (`queued`, `processing`, `done`, `failed`), `attempts`, `lease_expires_at`, `claimed_by`, `correlation_id`, `last_error`, timestamps.
- `outbox`: `id` uuid, `job_id` (unique FK), `status` (`pending`, `published`), `attempts`, `lease_expires_at`, `next_attempt_at`, `published_at`, `correlation_id`, `last_error`, `created_at`.
- `spike_vector_probe`: pgvector feasibility only; replaced in M3.

Only the backend workstream writes migrations. Other workstreams ask the Owner for schema changes.

## Envelope
QStash delivers `POST <worker>/internal/jobs/run` with body `{"schema_version": 1, "job_id": "<uuid>"}`. Everything else is read from the database. Unknown `schema_version` is rejected with 422.

## Core functions (`knowserve_core`, Worker workstream)
- `jobs.enqueue_job(session, job_type, correlation_id=None) -> Job`: inserts the `jobs` row **and** its `outbox` row in the caller's transaction (ING-12). It never publishes.
- `outbox.publish_after_commit(session_factory, publisher, job_id)`: best-effort immediate publish for one row. It claims the row (lease), calls the publisher, marks `published`. Failure is swallowed and logged; the row stays `pending` for recovery.
- `outbox.dispatch_pending(session_factory, publisher, batch_size, lease_seconds) -> DispatchResult`: claims `pending` rows whose `next_attempt_at` has passed with `FOR UPDATE SKIP LOCKED` plus a lease, publishes each, marks `published` on success or backs off on failure.
- `qstash.Publisher` protocol with an HTTP implementation (QStash publish API) and a fake used by tests (TEST-09); `qstash.verify_signature(...)` for the Worker.

Publishing is at-least-once; the Worker is idempotent (ING-15). Nothing here claims exactly-once.

## Worker endpoints
| Endpoint | Authentication | Behavior |
|---|---|---|
| `POST /internal/jobs/run` | QStash signature (`Upstash-Signature` JWT, HS256, verified with the current key, then the next key; checks `iss`, `exp`/`nbf`, and the body hash). Missing or invalid: `401` before any other work. | Parse envelope, load job. Unknown job: `200 {"result":"unknown_job"}` and no work. Job `done`: `200 {"result":"already_done"}`. Job leased by another worker: `409` (retryable) and no execution. Otherwise claim atomically (set `processing`, lease, `attempts+1`), run the no-op, mark `done`. A crash leaves the lease to expire, and the next delivery reclaims. |
| `POST /internal/outbox/dispatch` | production: Google OIDC bearer token from Cloud Scheduler, verified for audience `KS_DISPATCHER_OIDC_AUDIENCE` and email `KS_DISPATCHER_OIDC_SERVICE_ACCOUNT`; local/ci only: `Authorization: Bearer <KS_DISPATCHER_LOCAL_TOKEN>`. Otherwise `401`. | Runs one `dispatch_pending` batch and returns `200 {"published": n, "failed": m}`. |
| `GET /health/live`, `GET /health/ready` | none | as in `api.md` |

The Worker allows unauthenticated network access to Cloud Run (QStash cannot present Google credentials), so every non-health route must authenticate itself as above; URL secrecy is not authentication (SEC-14).

## Correlation
`correlation_id` is copied from the request context into `jobs` and `outbox` at enqueue time and set again from the job row when the Worker processes it, so one id appears in API and Worker logs (MON-03).
