# Infrastructure, deployment and cost

**Status:** Target spec. Nothing is implemented: there is no Dockerfile, Compose file, Terraform, CI or deployment config in the repo. Proven first by the M0 deployment spike (`../milestones/M0/plan.md`).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| INFRA-01 | Environments: local development uses Docker Compose (API, Worker, local PostgreSQL+pgvector where practical) and Vite for the frontend. CI uses ephemeral test resources. There is one Production environment and **no permanent staging**. | M0 |
| INFRA-02 | Hosting: Cloudflare Pages (static frontend), Google Cloud Run (separate FastAPI API and Worker HTTP services), Neon PostgreSQL+pgvector, Cloudflare R2 (private objects), Upstash QStash (signed deliveries) and Resend (email). Cloud Run region `europe-west1`, both services scale to zero with at most 2 instances. Outbox recovery in M0 is an admin manual retry; Cloud Scheduler is optional, deferred and disabled by default (STACK-23). | M0 |
| INFRA-03 | An **early M0 deployment spike** checks and documents provider interoperability, quotas and free-tier conditions, region and cold starts, Cloud Run streaming and request timeouts, QStash invocation and signatures, and real cost. Uncertainties are recorded, not guaranteed. Evidence is not yet collected: every live-cloud claim stays UNVERIFIED until the spike report records it. | M0 |
| INFRA-04 | Production deploys automatically on merge to `main`, and only after a **human-approved milestone PR** with passing CI. GitHub Actions runs the tests, builds the containers, deploys, and runs post-deploy smoke tests. | M0 |
| INFRA-05 | Rollback uses Cloud Run revision rollback where safe. DB migrations are backward-compatible; any rollback-incompatible migration is handled explicitly. | M0 |
| INFRA-06 | Terraform manages the supported resources, IAM and deployment settings, with a protected remote state and locking. **No secret values ever enter Terraform state.** Unsupported IaC gaps are documented. Image release may be independent of `terraform apply`. | M0 |
| INFRA-07 | Secrets live in Google Secret Manager with per-service IAM (API and Worker least privilege). Locally, `.env` is private and git-ignored, and `.env.example` holds placeholders. GitHub Actions authenticates to GCP via OIDC / Workload Identity Federation. | M0 |
| INFRA-08 | Backups are basic provider backups only. The docs must not promise an independent or complete backup solution on free tiers; R2 durability is not a versioned recovery backup (OPEN-09). | M0 (doc) |
| INFRA-09 | Logs and basic metrics follow MON-03 to MON-06. There is no full distributed tracing or Sentry initially. | M0 |
| INFRA-10 | A DB or auth outage fails closed (SEC-13). An LLM outage degrades chat but never prevents reading permitted documents. | M1/M4 |
| INFRA-11 | **Same-origin API route without Domain Mapping** (OPEN-21, approved provisionally): the frontend on Cloudflare Pages (default `pages.dev` host) forwards `/api/*` to Cloud Run through a Pages Function; no custom domain, load balancer or Cloud Run Domain Mapping is required (`../contracts/proxy.md`). The M0 spike must confirm incremental SSE, `Set-Cookie`/`Cookie` pass-through, the forwarded client IP and the Function quota fit on Cloudflare's edge. If it fails, the Owner reports the blocker and alternatives (load balancer cost, Firebase limits) to the user; insecure cross-site cookies are not adopted. | M0 spike |
| COST-01 | The aspirational target is a working public demo at **$0–5/month** including limited AI usage. This is a goal to verify (INFRA-03), not a guarantee (OPEN-10). | M0 |
| COST-02 | Application-level limits: per-day question quotas (Demo 20, Registered 100, Admin 100; OPEN-25, AUTH-36), per-request token caps, and parallel/concurrency caps. Other values are OPEN-05. The quota counters ship in M1; chat applies them in M4. | M1 / M4 |
| COST-03 | An atomic global token/dollar budget reservation happens before each LLM call. The global usage guard and its configuration are built in M1 (AUTH-36, threshold still open in OPEN-05) and applied to chat in M4. | M1 / M4 |
| COST-04 | Provider billing alerts and an AI kill switch. GCP billing budgets/alerts are **configured manually by the user** in the console; Terraform neither creates nor manages a billing budget. | M0 (alerts, manual) / M4 (switch) |
| COST-05 | With an exhausted budget or the kill switch on, live LLM generation is disabled, while authorized document reading and chat history keep working. Optional labeled pre-verified sample exchanges respect permissions (PROD-10, CHAT-17). | M4 |

## Required tests / evidence
| Req | Level | Scenario | Expected / evidence |
|---|---|---|---|
| INFRA-01 | manual + CI | `docker compose up`, then the health endpoints | API, Worker and DB healthy |
| INFRA-02/03 | spike report | Deployed hello-path Pages → API → Neon, QStash → Worker | M0-AC02, M0-AC04, M0-AC09 |
| INFRA-04 | CI | PR without approval, or with failing checks | deploy job does not run; post-merge smoke results attached (M0-AC08) |
| INFRA-05 | review | The migration PR template asks about backward compatibility | checklist item present and answered |
| INFRA-06/07 | CI + review | Secret scan; inspect state for secret values; OIDC deploy without JSON keys | no secrets found; no long-lived keys |
| INFRA-08 | review | Spike report backup section | provider backup capabilities stated without guarantees (OPEN-09) |
| INFRA-09 | integration | See MON-03 to MON-06 | JSON logs with correlation ids; alerts defined |
| INFRA-10 | integration | LLM provider mocked down | chat returns an `error` event; library and viewer still 200 |
| INFRA-11 | spike report + deploy smoke | Deployed Pages Function proxy to the Cloud Run API with the spike endpoints on | SSE events arrive incrementally for 30 to 300 s streams; the test cookie is host-only, HttpOnly, Secure, Lax; `X-KS-Client-IP` equals the real client IP; direct Cloud Run access without the secret returns 403; request count fits the free quota (M0-AC11) |
| COST-01 | spike report | Measured and estimated monthly cost per service at demo traffic | documented with assumptions (M0-AC09); no guarantee claimed |
| COST-02 | integration | Exceed a visitor quota | request refused with a clear message; registered quota unaffected |
| COST-03 | integration | Concurrent requests near the budget limit | total reserved never exceeds the budget |
| COST-04/05 | integration + e2e | Kill switch on | no LLM call made; documents and history available |

## Current implementation (LEGACY)
None of this exists. The legacy app runs locally only: `uvicorn` plus a Celery worker, and it needs local Postgres and Redis. CORS allows `localhost:5173` and `knowserve.vercel.app` (`backend/app/main.py`), which conflicts with INFRA-02 (Pages, not Vercel).

## Related docs
`tech-stack.md`, `rollback.md`, `ci-cd-proposals.md`, `../backend/monitoring.md`, `../milestones/M0/plan.md`, `../open-decisions.md`

## M3 credential and infrastructure ownership (OPEN-31, M3-09)
- R2 uses two bucket-scoped tokens that the Owner creates in Cloudflare: the API's token allows read, write and delete, and the Worker's token is read only (D6). Whether the API token can delete is unverified (Cloudflare's documentation does not list delete per permission level) and is checked with a test object before the first deployed upload.
- The OpenAI key lives in a dedicated OpenAI project with an initial budget of 5 USD per month and is read only by the Worker (D3). Pricing, budget controls and whether the limits are enforced get verified before production setup.
- Terraform (M3-09) creates secret containers and per-service access bindings only. Each service reads only the secrets it needs. The Worker gets no write token and no database role beyond what the Worker already has.
- Worker memory, concurrency and request timeout change only as far as the M3-00b measurements justify (D2). M3-09 prepares and plans the change; applying it needs the Owner's separate approval.
- No credential is created or rotated, no IAM binding is changed and no `terraform apply` runs without the Owner's approval.

### M3-09 Terraform preparation (written, validated locally, not planned or applied)
The exact plan command, the expected diff, the Owner-only apply order, rollback and cost are in `../milestones/M3/infra-apply-runbook.md`.

Secrets, one container per credential, no versions in Terraform:

| Secret container | Env name | Read by |
|---|---|---|
| `r2-access-key-id`, `r2-secret-access-key` (existing) | `KS_R2_ACCESS_KEY_ID`, `KS_R2_SECRET_ACCESS_KEY` | API (read, write and delete token), and the seed job while it exists |
| `r2-worker-access-key-id`, `r2-worker-secret-access-key` (new) | the same two names | Worker only (read-only token) |
| `openai-api-key` (new) | `KS_OPENAI_API_KEY` | Worker only |

The API and the Worker use the same variable names with different secrets, as `config-and-deploy.md` requires. The Worker has no binding on the API's R2 containers, so it holds no write credential. The API has no binding on the three new containers. If the existing API token turns out unable to delete, the Owner adds a new version to the existing containers; no rename is needed.

Environment: the API gets `KS_UPLOADS_ENABLED` (variable `uploads_enabled`, default true). The Worker gets `KS_OBJECT_STORE=r2`, the R2 endpoint and bucket, and `KS_EMBEDDING_PROVIDER=openai`. The provider is fixed in Terraform and cannot be set to `fake`, and the application refuses `fake` in production as well. The remaining M3 keys (upload limits, chunking, embedding, extraction timeout, SSE timing) are optional allow-listed maps, `api_m3_settings` and `worker_m3_settings`, empty by default so the OPEN-31 D1 defaults in the application apply. The Worker map mirrors three application guards (handler timeout below lease, overlap below chunk size, 1536 dimensions).

Worker sizing is pending the M3-00b measurements (D2). `worker_memory`, `worker_cpu`, `worker_concurrency` and `worker_request_timeout_seconds` exist as variables and default to null, which leaves the attributes unmanaged: 512 MiB, 300 s and concurrency 80 stay as in M2. The timeout variable must exceed `KS_JOB_HANDLER_TIMEOUT_SECONDS`. No value is proposed until `docs/milestones/M3/measurements.md` exists.

Alerts (MON-06, M3-AC24) sit behind `enable_m3_alerts`, default false, and create nothing while it is off. When on, they are two log-based metrics counting application ERROR logs of the Worker and the API, two alert policies and one email channel (`alert_email`). They do not cover stuck outbox rows or stuck jobs: those states are derived from the database when the Admin list is read, and nothing is logged for them. Cloud Run request logs are not matched, so a 5xx that QStash retries does not alert. The Worker also logs an error for each failed attempt that will be retried, so a transient failure can alert until the filter is narrowed to a permanent-failure event.

QStash is not changed. Two facts from plan section 12.2 matter for infrastructure sizing and timeouts. A delivery is one HTTP call from QStash. A processing attempt is one successful claim of the job. A request that Cloud Run rejects before the app runs (a cold start 500) or that the Worker answers with 409 uses a delivery and no attempt, and a delivery cut by the Cloud Run request timeout may leave the container running, which the publish fencing check covers. The QStash retry behaviour itself stays unverified until the D15 experiment.

Database access: the Worker keeps the same runtime role. Migration `0004` is run by the DDL role, and the default privileges in `infra/neon/runtime-roles.sql` give `ks_runtime` DML on tables that role creates later. The Owner confirms this on the first deployed run (the publish transaction deletes and inserts chunks).
