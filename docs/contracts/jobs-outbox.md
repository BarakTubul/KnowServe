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
Computed from existing columns; the stored `jobs.status` and `outbox.status` values above are unchanged. Thresholds: `KS_PUBLISH_GRACE_SECONDS` (120), `KS_STUCK_AFTER_SECONDS` (2400).

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
- Mounted only when `KS_ENABLE_SPIKE_JOB_OPS=true` AND operator emails and audience are set; otherwise 404. `skip_publish` and the job types `always_fail` and `fail_then_ok` additionally require `KS_ENABLE_SPIKE_FAILURE_HOOKS=true` (default false; only the isolated spike environment).
- Test job types (hooks flag only; the Worker registers their handlers only with `KS_ENABLE_SPIKE_FAILURE_HOOKS`, so real job types and document processing are unaffected): `always_fail` always raises; `fail_then_ok` raises until the job has been manually requeued, then succeeds. A manual requeue writes `manual retry requested; previous: <last error>` into `jobs.last_error`, which `fail_then_ok` reads to demonstrate the full cycle: 4 failed attempts, `failed`, manual retry, `done`. Without the flag these types have no handler and their jobs fail at once.
- This is not application authentication (M1) and not admin RBAC (M3). ADM-16 wraps the same core functions with the Admin role, CSRF and audit.
- Minting (decision B2 = impersonated service account, user-approved): a personal account cannot set a custom audience (`gcloud auth print-identity-token --audiences` is refused for user accounts; the default token carries the fixed gcloud client audience). Instead the operator impersonates the role-less service account `ks-spike-operator` (Terraform creates it only when `enable_spike_job_ops`; only the accounts in `spike_token_creator_emails` get `roles/iam.serviceAccountOpenIdTokenCreator` on it) and mints the token by calling IAM Credentials `projects/-/serviceAccounts/ks-spike-operator@<project>.iam.gserviceaccount.com:generateIdToken` (body `{"audience": "<API URL>", "includeEmail": true}`) with the operator's own access token (`gcloud auth print-access-token`). Verified live: `gcloud auth print-identity-token --impersonate-service-account` is refused with only the narrow role because it also calls `generateAccessToken` (`iam.serviceAccounts.getAccessToken`); the direct `generateIdToken` call needs only `getOpenIdToken`. The API allow-list holds the service account email, not the human one. The narrower `roles/iam.serviceAccountOpenIdTokenCreator` (only `iam.serviceAccounts.getOpenIdToken`) is used instead of `serviceAccountTokenCreator` (which also allows access tokens and signing); it is bound on that one service account's own IAM policy, never on the project. UNVERIFIED until the first deployed run: that this role is enough for the exact `gcloud` command (Google documents it for ID tokens, but its `gcloud` reference does not name the role) and that the API accepts the token (audience, `email_verified`, email claim). If the role is refused, widening to `serviceAccountTokenCreator` needs user approval.

## Worker endpoints
| Endpoint | Authentication | Behavior |
|---|---|---|
| `POST /internal/jobs/run` | QStash signature (`Upstash-Signature` JWT, HS256, verified with the current key, then the next key; checks `iss`, `exp`/`nbf`, and the body hash). Missing or invalid: `401` before any other work. | Parse envelope, load job. Unknown job: `200 {"result":"unknown_job"}` and no work. Job `done`: `200 {"result":"already_done"}`. Job leased by another worker: `409` (retryable) and no execution. Job `failed`: `200 {"result":"failed"}`. Otherwise claim atomically (set `processing`, lease, `attempts+1`), run the no-op, mark `done`. A handler failure follows the failure semantics below. A crash leaves the lease to expire, and the next delivery reclaims. |
| `POST /internal/outbox/dispatch` (mounted only when `KS_ENABLE_RECOVERY_DISPATCHER=true`; otherwise `404`) | production: Google OIDC bearer token from Cloud Scheduler, verified for audience `KS_DISPATCHER_OIDC_AUDIENCE` and email `KS_DISPATCHER_OIDC_SERVICE_ACCOUNT`; local/ci only: `Authorization: Bearer <KS_DISPATCHER_LOCAL_TOKEN>`. Otherwise `401`. | Runs one `dispatch_pending` batch and returns `200 {"published": n, "failed": m}`. |
| `GET /health/live`, `GET /health/ready` | none | as in `api.md` |

The Worker allows unauthenticated network access to Cloud Run (QStash cannot present Google credentials), so every non-health route must authenticate itself as above; URL secrecy is not authentication (SEC-14).

## Scheduled maintenance endpoint (M1, OPEN-26 N6)
One exception to the job-row requirement: `POST /internal/maintenance/demo-cleanup` on the Worker. It verifies the QStash signature with the same code as the job endpoint, accepts **no** caller-controlled parameters (the body and query are ignored; limits come from configuration), and runs one fixed, bounded, idempotent cleanup (`AUTH-35`). It is triggered by one daily QStash schedule. No other maintenance routes exist.

## Correlation
`correlation_id` is copied from the request context into `jobs` and `outbox` at enqueue time and set again from the job row when the Worker processes it, so one id appears in API and Worker logs (MON-03).

## M3 changes (`admin-api.md`, `../milestones/M3/plan.md`, OPEN-31)
Fixed by M3-01 and implemented by M3-00a and M3-02b. The envelope does not change.

- Job to revision link: `document_revisions.job_id` (unique where set). The handler loads the revision from the job id. Seeded revisions have none until the reindex run.
- Job type `ingest_revision`. The Worker sets the revision `phase` before each stage and `status` to `processing` after the claim.
- Hooks (`knowserve_core/job_hooks.py`): a handler raises `NonRetryableJobError(code)` to fail the job at once or `RetryableJobError(code)` for a failure that a later attempt may fix. `TerminalFailureHook` runs in the transaction that marks a job `failed` (terminal error, attempt cap, or the crash guard) and sets the revision `failed`; it never touches a `ready` revision (reindex mode, D4). `RequeueHook` runs in the transaction that `retry_job` uses to requeue and sets the revision back to `queued`.
- Claim: checks `attempts < KS_JOB_MAX_ATTEMPTS`. A job past the cap is marked `failed` with `PROCESSING_CRASHED` instead of running again. The Worker keeps the lease alive while a handler runs. Every pipeline write is conditional on the job still being claimed by this worker (fencing), so a late writer after a Cloud Run timeout changes nothing.
- No persisted outbox dead state (D13). Delivery states stay derived.
- Deliveries and attempts are different counters. A delivery is one HTTP call from QStash; an attempt is one successful claim (`jobs.attempts`). A 409 or a 200 for a finished job uses a delivery and no attempt. QStash retries any non-2xx answer (default 3 retries, 4 deliveries, delay `min(86400, e^(2.5 n))` seconds; a 489 with `Upstash-NonRetryable-Error: true` stops retries; the destination sees `Upstash-Retried`). Changing a job row to `queued` does not make QStash deliver again; only a new publish does. The D15 experiment (plan section 12.2) checks this against the real service.

### Implemented in M3-00a (Worker reliability)
Code: `knowserve_core/job_claims.py` (claim, lease renewal, complete, release, fail), `job_fencing.py` (`assert_claimed`, `LostClaimError`), `revision_hooks.py` (default `TerminalFailureHook` `mark_revision_failed` and `RequeueHook` `requeue_revision`), and `run_job` in the Worker app. Tests: `apps/worker/tests/test_m3_worker_reliability.py`.

- **Claim.** `attempts < KS_JOB_MAX_ATTEMPTS` is part of the claim UPDATE. A `queued` job, or a `processing` job whose lease expired, that is already at the cap is not run: in the same transaction it is marked `failed` (`last_error` starts with `PROCESSING_CRASHED`) and the terminal hook sets its revision `failed` with `PROCESSING_CRASHED`. The Worker answers `500 JOB_FAILED_PERMANENTLY`. A live lease at the cap is left alone (`409`). Only a successful claim increments `attempts`.
- **Heartbeat.** While a handler runs, the Worker renews the lease every `KS_JOB_LEASE_SECONDS / 3` seconds (`UPDATE ... WHERE claimed_by = me AND status = 'processing'`). A failed renewal because of a database error is logged and retried on the next beat. If the renewal finds the claim gone, the handler is cancelled and the delivery answers `409 JOB_CLAIM_LOST` without touching the job. The handler timeout (`KS_JOB_HANDLER_TIMEOUT_SECONDS`) still bounds one attempt.
- **Fencing.** A handler writes only through `ctx.fenced_session()` (`job_fencing.fenced_session`): a transaction whose first statement is the fence, used for every write including phase updates. `ctx.fence(session)` is the low-level call under it. It runs `SELECT ... WHERE id = job AND claimed_by = me AND status = 'processing' FOR UPDATE` and raises `LostClaimError` when no row matches. The row lock also makes a competing reclaim wait until that transaction ends. The Worker's own finishing statements (done, release, fail) are conditional on the same claim and check the row count.
- **Errors.** `NonRetryableJobError(code)`: the job is `failed` at once, the terminal hook runs in that transaction, the answer is `500 JOB_FAILED_PERMANENTLY` (QStash may redeliver, and a redelivery gets `200 {"result":"failed"}`). `RetryableJobError(code)`: released to `queued` with `500 JOB_FAILED` while attempts remain; at the cap it is `failed` with that code. A handler timeout counts as `PROCESSING_TIMEOUT` and any other exception as `INTERNAL_ERROR`. For an untyped exception only the class names (the exception and its cause, for example `RuntimeError <- ValueError`) are stored in `jobs.last_error` and logged, never the message or a traceback: SQLAlchemy and parser errors can quote chunk or document text (MON-05, SEC-18). Handlers therefore wrap parser, storage and database errors in `NonRetryableJobError` or `RetryableJobError`. A failed lease renewal is logged with the error type only. A job type with no handler is `failed` with `INTERNAL_ERROR` and the same hook. If the hook raises, the whole transaction rolls back, the job stays `processing` and the lease expires into the crash guard.
- **Hooks.** `mark_revision_failed` sets `status='failed'`, `failure_reason=<code>`, `phase=NULL` on the revision with `job_id = <job>` unless it is `ready`. `requeue_revision` sets `status='queued'`, `phase=NULL`, `failure_reason=NULL` under the same rule. `retry_job` runs `requeue_revision` in the transaction that requeues the job and re-arms the outbox row. A job without a linked revision matches no row.
- **HTTP answers.** `200` for done, failed and unknown jobs; `409` for a claim conflict or a lost claim; `500` for a failure. Deliveries and attempts stay separate: `409`, `200` for a finished job and a Cloud Run rejection before the app use no attempt.
- **Lock order.** Publication (`ingest_revision`) locks the job row first (the fence, `SELECT ... FOR UPDATE`) and the document row second. Any code that locks both, such as delete, replace and retry in M3-05, must follow job then document and never lock the document first, or it can deadlock with a publishing Worker. Code that needs only the document (a plain soft delete, the access update) may lock just the document row. In M3-05 only replace locks both (`admin/replace.py`): it reads the failed revision, locks that revision's job row, then the document row, then reads the state again and answers 409 if the latest revision changed. Retry (`retry_job`) locks the job and outbox rows and never the document; delete and the access update lock only the document.
