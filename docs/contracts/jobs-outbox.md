# Jobs, outbox and Worker contract (M0)

Requirements: ING-10, ING-12..16, ING-21, SEC-14, LIFE-09, ADM-16. M0 proves the mechanism with a no-op job; real ingestion is M3. Recovery in M0 is an admin-initiated manual retry; scheduled recovery is optional and disabled by default (STACK-23).

## Tables (initial migration `0001`, `knowserve_core.models`)
- `jobs`: `id` uuid, `job_type`, `status` (`queued`, `processing`, `done`, `failed`), `attempts`, `lease_expires_at`, `claimed_by`, `correlation_id`, `last_error`, timestamps.
- `outbox`: `id` uuid, `job_id` (unique FK), `status` (`pending`, `published`), `attempts`, `lease_expires_at`, `next_attempt_at`, `published_at`, `correlation_id`, `last_error`, `created_at`.
- `spike_vector_probe`: pgvector feasibility only; replaced in M3.

Only the backend workstream writes migrations. Other workstreams ask the Owner for schema changes.

## Envelope
QStash delivers `POST <worker>/internal/jobs/run` with body `{"schema_version": 1, "job_id": "<uuid>"}`. Everything else is read from the database. Unknown `schema_version` is rejected with 422.

## Core functions (`knowserve_core`, Worker workstream)
- `jobs.enqueue_job(session, job_type, correlation_id=None) -> Job`: inserts the `jobs` row **and** its `outbox` row in the caller's transaction (ING-12). It never publishes.
- `outbox.publish_after_commit(session_factory, publisher, job_id)`: immediate publish for one row, awaited inside the API request with a bounded timeout (never unawaited background work). It claims the row (lease; the claim returns its attempt number), calls the publisher, marks `published`. Marking `published`/`failed` requires `attempts = claimed attempt AND lease still live` and checks the row count, so an expired claim holder never overwrites a newer claim. Failure is logged; the row stays `pending` with `last_error` for manual retry.
- `outbox.dispatch_pending(session_factory, publisher, batch_size, lease_seconds) -> DispatchResult`: claims `pending` rows whose `next_attempt_at` has passed with `FOR UPDATE SKIP LOCKED` plus a lease, publishes each, marks `published` on success or backs off on failure. Used **only** by the optional batch dispatcher (`KS_ENABLE_RECOVERY_DISPATCHER=true`). Known gap (deferred): a batch claimed with one lease and published sequentially can outlive its lease.
- Manual retry (shared core, ADM-16): `republish` (publish failure class) atomically claims the outbox row ignoring backoff and publishes; `requeue` (processing failure class) in one transaction sets the job `queued`, `attempts` 0, clears lease and `claimed_by`, sets the outbox row `pending` with `attempts` 0, then publishes. Both reject a `done` job or one with an active processing lease with 409; of two concurrent retries one wins and the other gets 409.
- `qstash.Publisher` protocol with an HTTP implementation (QStash publish API) and a fake used by tests (TEST-09); `qstash.verify_signature(...)` for the Worker.

Publishing is at-least-once; the Worker is idempotent (ING-15). Nothing here claims exactly-once.

## Derived job states (no schema change)
Computed from existing columns; the stored `jobs.status` and `outbox.status` values above are unchanged. Thresholds: `KS_PUBLISH_GRACE_SECONDS` (120), `KS_STUCK_AFTER_SECONDS` (900).

| Derived state | Meaning |
|---|---|
| `publishing` | outbox `pending` with a live lease |
| `publish_pending` | outbox `pending`, no error, younger than the grace |
| `unpublished_stuck` | outbox `pending`, no error, older than the grace, lease free or expired (e.g. API crashed after commit) |
| `publish_failed` | outbox `pending` with `last_error`, lease free |
| `queued` | outbox `published`, job `queued`, within the stuck threshold |
| `queued_stuck` | job `queued`, outbox `published`, older than the threshold (message lost or QStash retries exhausted) |
| `processing` | job `processing` with a live lease |
| `processing_stuck` | job `processing` with an expired lease |
| `failed` | terminal: `KS_JOB_MAX_ATTEMPTS` (4) reached or a non-retryable error |
| `done` | processed |

## Worker failure semantics (ING-16)
On a failed attempt the Worker releases the job to `queued` with `last_error` and returns HTTP 500 so QStash retries. When `jobs.attempts` reaches `KS_JOB_MAX_ATTEMPTS` it marks the job `failed` and returns a non-2xx, so it never acknowledges a failure with 200 while an automatic retry is pending. A later redelivery of a `failed` job returns `200 {"result":"failed"}` to stop QStash. How this interacts with QStash's real retry count and backoff is UNVERIFIED until a live test.

## Operator test surface (spike only, not public)
Routes on the **API**: `POST /internal/spike/jobs` (create; allow-listed `job_type`, test-only `skip_publish`), `GET /internal/spike/jobs` (list, `state` filter), `GET /internal/spike/jobs/{id}`, `POST /internal/spike/jobs/{id}/retry`. They use `include_in_schema=False` (absent from the public OpenAPI and the frontend client) and are unreachable through Pages (`proxy.md`).
- Authentication: a Google OIDC ID token (`Authorization: Bearer`) verified for audience `KS_SPIKE_OIDC_AUDIENCE`, `email_verified` true, email in `KS_SPIKE_OPERATOR_EMAILS`. The proxy guard still applies (the operator also sends `X-KS-Proxy-Secret` on the run.app URL).
- Mounted only when `KS_ENABLE_SPIKE_JOB_OPS=true` AND operator emails and audience are set; otherwise 404. `skip_publish` and job type `always_fail` additionally require `KS_ENABLE_SPIKE_FAILURE_HOOKS=true` (default false; only the isolated spike environment).
- This is not application authentication (M1) and not admin RBAC (M3). ADM-16 wraps the same core functions with the Admin role, CSRF and audit.
- UNVERIFIED spike item: how an operator mints an ID token for a human account with the right audience (`gcloud` may issue only a fixed audience for user accounts). Fallbacks, each needing user approval: a dedicated secret token, or an impersonated service account.

## Worker endpoints
| Endpoint | Authentication | Behavior |
|---|---|---|
| `POST /internal/jobs/run` | QStash signature (`Upstash-Signature` JWT, HS256, verified with the current key, then the next key; checks `iss`, `exp`/`nbf`, and the body hash). Missing or invalid: `401` before any other work. | Parse envelope, load job. Unknown job: `200 {"result":"unknown_job"}` and no work. Job `done`: `200 {"result":"already_done"}`. Job leased by another worker: `409` (retryable) and no execution. Job `failed`: `200 {"result":"failed"}`. Otherwise claim atomically (set `processing`, lease, `attempts+1`), run the no-op, mark `done`. A handler failure follows the failure semantics below. A crash leaves the lease to expire, and the next delivery reclaims. |
| `POST /internal/outbox/dispatch` (mounted only when `KS_ENABLE_RECOVERY_DISPATCHER=true`; otherwise `404`) | production: Google OIDC bearer token from Cloud Scheduler, verified for audience `KS_DISPATCHER_OIDC_AUDIENCE` and email `KS_DISPATCHER_OIDC_SERVICE_ACCOUNT`; local/ci only: `Authorization: Bearer <KS_DISPATCHER_LOCAL_TOKEN>`. Otherwise `401`. | Runs one `dispatch_pending` batch and returns `200 {"published": n, "failed": m}`. |
| `GET /health/live`, `GET /health/ready` | none | as in `api.md` |

The Worker allows unauthenticated network access to Cloud Run (QStash cannot present Google credentials), so every non-health route must authenticate itself as above; URL secrecy is not authentication (SEC-14).

## Correlation
`correlation_id` is copied from the request context into `jobs` and `outbox` at enqueue time and set again from the job row when the Worker processes it, so one id appears in API and Worker logs (MON-03).
