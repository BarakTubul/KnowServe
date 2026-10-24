# M0 spike report: provider research (M0-09)

Status: DOCUMENTED values only. Nothing here was measured; the M0 deployment spike has not run. Every row has an official source and a retrieval date. UNKNOWN means the value was not retrievable from an official page in this session. No recommendation to spend money is made. Supports M0-AC09, INFRA-03, INFRA-08, COST-01, ING-22, OPEN-06, OPEN-09, OPEN-10, OPEN-04.

Conventions: Retrieved = 2026-10-24 for every row. Measured column = "not measured, M0 deployment spike not run" for every row (stated once here to keep tables short; it applies to every table). Prices are USD as shown on the page. Pricing pages can change; re-check at go-live.

Note on fetching: Google pricing pages were read as full HTML text (Cloud Run, Scheduler, Secret Manager, Artifact Registry, Observability). Terraform registry content was read through the public registry API for the latest provider versions (see section 4).

---

## 1. Cost and free tiers (DOCUMENTED)

| # | Service | Documented fact | Conditions / limits that matter | Source |
|---|---|---|---|---|
| 1.1 | Cloud Run (request-based billing) | Free per month: 180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million requests | "Free tier (based on us-central1 active pricing)"; aggregated across projects by billing account; applied as a spending-based discount using Tier 1 pricing; resets monthly | https://cloud.google.com/run/pricing |
| 1.2 | Cloud Run (instance-based billing) | Free per month: 240,000 vCPU-seconds, 450,000 GiB-seconds | Same aggregation rule | https://cloud.google.com/run/pricing |
| 1.3 | Cloud Run | Free: 1 GB outbound data transfer from North America per month | Pricing page: "1GiB free data transfer within North America per month"; the free-features page says 1 GB; units differ by page | https://docs.cloud.google.com/free/docs/free-cloud-features , https://cloud.google.com/run/pricing |
| 1.4 | Cloud Run | Min instances are billed. Idle min-instance time is billed at a separate "idle" rate. Idle instances that are not min instances are not charged | Default min instances = 0 | https://cloud.google.com/run/pricing , https://docs.cloud.google.com/run/docs/configuring/min-instances |
| 1.5 | Cloud Run | Requests are billed only when they reach the container after authentication; requests denied by IAM are not billed | Both services use allUsers invoker in Terraform, so unauthenticated requests are billed | https://cloud.google.com/run/pricing |
| 1.6 | Cloud Run | Per-unit prices beyond the free tier | UNKNOWN (price table columns by region could not be mapped reliably from the text; not recorded) | https://cloud.google.com/run/pricing |
| 1.7 | Cloud Scheduler | $0.10 per job per 31 days; 3 jobs per month free | Free tier is per account (billing account), not per project | https://cloud.google.com/scheduler/pricing |
| 1.8 | Secret Manager | Free per month: 6 active secret versions, 10,000 access operations, 3 rotation notifications. Beyond: $0.06 per active version per month (page example), $0.03 per 10,000 access operations | Aggregated across projects by billing account | https://cloud.google.com/secret-manager/pricing |
| 1.9 | Artifact Registry | First 0.5 GiB-month of storage free, per billing account (across all projects). Data transfer into Google Cloud free | Storage price beyond free: $0.000136986 per GiB-hour (as shown) | https://cloud.google.com/artifact-registry/pricing |
| 1.10 | Cloud Logging | First 50 GiB per project per month free; $0.50/GiB beyond; default retention incurs no retention cost; retention beyond 30 days $0.01/GiB/month | Pricing language changed 2023-07-19, rates unchanged | https://cloud.google.com/stackdriver/pricing |
| 1.11 | Cloud Monitoring | Uptime checks: 1 million free executions per month; Monitoring API reads: first 1 million time series returned per billing account | Not otherwise needed for M0 | https://cloud.google.com/stackdriver/pricing , https://docs.cloud.google.com/free/docs/free-cloud-features |
| 1.12 | GCP billing budgets | Alerts-only budgets do not cap usage or spending. Notifications may take several hours to start and costs are reported with a delay. Default thresholds 50%, 90%, 100% | A real spend cap needs another mechanism (not researched; UNKNOWN for this stack) | https://docs.cloud.google.com/billing/docs/how-to/budgets |
| 1.13 | Cloudflare Pages | Free plan: 500 builds per month, 20,000 files per site, 25 MiB max asset size, 100 custom domains per project. No bandwidth limit stated on the limits page | Pages Functions count against Workers plan quota (not used by the static plan) | https://developers.cloudflare.com/pages/platform/limits/ |
| 1.14 | Cloudflare R2 (Standard) | Free per month: 10 GB-month storage, 1 million Class A ops, 10 million Class B ops. Egress free. Beyond: $0.015/GB-month, $4.50/million Class A, $0.36/million Class B | Free tier applies to Standard storage only | https://developers.cloudflare.com/r2/pricing/ |
| 1.15 | Neon Free | $0/month; 100 CU-hours per project; 1 GB storage per project (20 GB account total); 5 GB egress per project; 10 branches; scale to zero after 5 min (cannot be disabled); max autoscaling 2 CU; 100 projects | Compute allowance is per project | https://neon.com/pricing , https://neon.com/docs/introduction/plans |
| 1.16 | Neon Launch | Usage-based: $0.106/CU-hour, $0.35/GB-month; 500 GB egress per project then $0.10/GB | Shown for comparison only (OPEN-09) | https://neon.com/pricing |
| 1.17 | Neon | Minimum compute size / CU used by an idle-but-active database | UNKNOWN (not retrieved) | https://neon.com/docs/introduction/plans |
| 1.18 | Neon | pgvector availability on Free plan | UNKNOWN (not checked in this session; the M0 spike_vector_probe migration verifies it) | n/a |
| 1.19 | Upstash QStash Free | 1,000 messages per day; max message size 1 MB; max HTTP response duration 15 minutes; DLQ retention 3 days; log retention 3 days; bandwidth 50 GB per month (first column of the limits table); 10 active schedules | "Each delivery attempt counts as one message", so retries consume the daily quota | https://upstash.com/docs/qstash/overall/pricing |
| 1.20 | Upstash QStash Pay-as-you-go | $1 per 100K messages; bandwidth free to 50 GB per month then $0.05/GB; 10 MB max message; 2 hours max HTTP response duration | Shown for comparison only | https://upstash.com/docs/qstash/overall/pricing |
| 1.21 | Resend Free | 3,000 emails per month; 100 emails per day; 3 domains; 30-day data retention. Pro $20/month for 50,000 emails | Daily cap applies on Free | https://resend.com/pricing |
| 1.22 | OpenAI embeddings | text-embedding-3-small $0.02, text-embedding-3-large $0.13, text-embedding-ada-002 $0.10 per 1M input tokens (Standard). No batch price listed for embeddings | Model choice is fixed by the stack docs, not by this report | https://developers.openai.com/api/docs/pricing |
| 1.23 | OpenRouter | `:free` model variants: 20 requests/min; 50 requests/day with under 10 credits purchased, 1000/day with at least 10. A negative credit balance can cause errors, including for free models | Paid-model token prices are model-specific: UNKNOWN (no model chosen) | https://openrouter.ai/docs/api-reference/limits , https://openrouter.ai/docs/faq |
| 1.24 | OpenRouter | Platform fee on credit purchases | UNKNOWN (page showed an unrendered template placeholder) | https://openrouter.ai/docs/faq |
| 1.25 | Domain registration | Typical price | not found in official documentation (no registrar chosen; Cloudflare Registrar pricing page not retrieved) | n/a |

### 1.A ESTIMATE (clearly not measured; documented figures combined with assumptions)

Assumptions (stated by this report, not provided by the project): A1 about 500 page views, 50 API-using sessions, 10,000 API requests, 1,000 chat requests per month; A2 average API request 0.2 s on 1 vCPU/0.5 GiB; A3 20 documents ingested per month, each job under 5 minutes; A4 0 min instances for both services; A5 one Scheduler job (the Terraform has one); A6 one Neon project; A7 the Terraform's four secrets with one version each; A8 two container images of unknown size.

| Item | Estimate arithmetic (documented figures x assumptions) | Result vs documented free tier |
|---|---|---|
| Cloud Run requests | 10,000 + 1,000 + job deliveries, vs 2,000,000 free | Far below (estimate) |
| Cloud Run vCPU-seconds | about 11,000 x 0.2 s + ingestion 20 x 300 s = about 8,200 vCPU-s, vs 180,000 free | Below (estimate; chat streaming duration not modeled: a stream of 30 s x 1,000 = 30,000 vCPU-s, still below) |
| Cloud Scheduler | 1 job vs 3 free jobs per account | Within free tier (shared with any other jobs on the billing account) |
| Secret Manager | 4 versions vs 6 free; accesses depend on instance starts, vs 10,000 free | Within free tier if no rotation adds versions beyond 6 |
| Artifact Registry | 0.5 GiB free; image sizes UNKNOWN | UNKNOWN. Two Python images plus kept revisions may exceed 0.5 GiB (assumption); cleanup policy would matter |
| Cloud Logging | 50 GiB free per project per month | Far below at demo volume (assumption A1) |
| Cloudflare Pages | builds under 500 per month if only main deploys | Within free tier |
| R2 | 10 GB-month, 1M Class A, 10M Class B free | Within free tier for a small PDF set (assumed under 10 GB) |
| Neon Free | 100 CU-hours per project per month, 1 GB storage | UNKNOWN: depends on CU size and active hours (not retrieved). 1 GB must hold relational rows plus pgvector embeddings; unmeasured |
| QStash Free | 1,000 messages per day including retries | Within free tier for 20 jobs per month; a backlog or retry storm could hit it |
| Resend Free | 3,000/month, 100/day | Within free tier for demo registrations |
| OpenAI embeddings | e.g. 1M tokens of PDFs x $0.02 per 1M = $0.02 one time, plus query embeddings | Cents (estimate) |
| OpenRouter chat | depends on the model; free models limited to 50 or 1000 requests per day | UNKNOWN (model unchosen); a paid model's cost is unbounded without COST-02/03 limits |
| Domain | no official price found | UNKNOWN; the only certain non-free line item |

Conclusion (OPEN-10): the documented free tiers alone appear sufficient for the hosting services at the assumed demo traffic, with three uncertain items that decide whether $0-5/month holds: Neon compute hours, Artifact Registry image storage, and the LLM and domain cost. The budget is not claimed to be achievable; billing data from the spike is required. Alerts-only budgets do not stop spend (row 1.12).

---

## 2. Limits that affect the design (DOCUMENTED)

### 2.1 Cloud Run

| # | Fact | Source |
|---|---|---|
| 2.1.1 | Request timeout default 300 s (5 min), maximum 3600 s (60 min). On timeout Cloud Run closes the connection and returns 504; the container "might continue processing the aborted request". Over 15 min: Google advises retry logic and re-connecting clients | https://docs.cloud.google.com/run/docs/configuring/request-timeout |
| 2.1.2 | Concurrency per instance: default 80; quotas page lists maximum 1,000 for services | https://docs.cloud.google.com/run/docs/configuring/concurrency , https://docs.cloud.google.com/run/quotas |
| 2.1.3 | Max instances: 100 per project and region (default quota, increase on request). Max request size 32 MiB (HTTP/1); max response 32 MiB when not streaming/chunked; 100 concurrent streams per HTTP/2 client connection | https://docs.cloud.google.com/run/quotas |
| 2.1.4 | Max 8 vCPU and 32 GiB per instance. Below 1 vCPU: concurrency must be 1 and request-based billing required | https://docs.cloud.google.com/run/quotas , https://docs.cloud.google.com/run/docs/configuring/services/cpu |
| 2.1.5 | Min instances default 0; min instances are "a best-effort target"; they incur cost. Cold-start mitigations named: startup CPU boost, min instances, fewer dependencies | https://docs.cloud.google.com/run/docs/configuring/min-instances , https://docs.cloud.google.com/run/docs/tips/general |
| 2.1.6 | Cold-start duration for this stack | UNKNOWN (no documented figure; measured in spike) |
| 2.1.7 | Streaming: "Cloud Run supports streaming HTTP responses. No configuration is required"; the service must send `Transfer-Encoding: chunked`. HTTP/2 is downgraded to HTTP/1 toward the container by default. SSE is not mentioned by name on that page | https://docs.cloud.google.com/run/docs/triggering/https-request |
| 2.1.8 | A stream is an HTTP request and is still bound by the request timeout (WebSocket page: "subject to the request timeout"; clients "should handle reconnecting") | https://docs.cloud.google.com/run/docs/triggering/websockets |
| 2.1.9 | Request-based billing: after the response, CPU is "disabled or severely limited"; background threads are discouraged. Instance-based billing allows background work | https://docs.cloud.google.com/run/docs/tips/general |
| 2.1.10 | Proxy/buffering behavior of SSE through Cloud Run and Cloudflare for `text/event-stream` | UNKNOWN (not documented on retrieved pages; measure in spike) |
| 2.1.11 | Terraform sets no timeout, min or max instances, concurrency or CPU billing mode, so defaults apply (300 s, 0, 80, request-based) | infra/terraform/gcp_cloud_run.tf |

### 2.2 QStash vs contract and code

| # | Documented fact | Source |
|---|---|---|
| 2.2.1 | Publish: `POST /v2/publish/{destination}`; auth by bearer token or `qstash_token` query param; headers with the `Upstash-Forward-` prefix are forwarded with the prefix stripped; `Upstash-Timeout` can shorten but not exceed the plan limit; `Upstash-Deduplication-Id` ignores a duplicate published within 10 minutes; `Upstash-Method` default POST | https://upstash.com/docs/qstash/api/publish |
| 2.2.2 | Retries: default 3 retries (so 4 deliveries); override with `Upstash-Retries`; no documented maximum. Backoff `delay = min(86400, e ** (2.5*n))` (12 s, 2 m 28 s, 30 m 8 s, 6 h 7 m, then 24 h cap). Any non-2xx triggers a retry; `Retry-After`-style headers are honored (max 1 day); status 489 with `Upstash-NonRetryable-Error: true` stops retries | https://upstash.com/docs/qstash/features/retry |
| 2.2.3 | Signature: header `Upstash-Signature`, JWT, "HMAC SHA256". Claims: `iss`="Upstash", `sub`= destination URL published to (even after redirect), `exp`, `nbf`, `iat`, `jti`, `body` = base64url SHA-256 of raw body (RFC 4648 section 5; the documented example ends in "=" padding). Lifetime 5 minutes by default | https://upstash.com/docs/qstash/features/security , https://upstash.com/docs/qstash/howto/signature |
| 2.2.4 | Two keys: current and next signing key. Procedure for rotating keys and any automatic rotation timing | UNKNOWN (not on retrieved pages; the verify-signature how-to URL returned 404) |
| 2.2.5 | Regions: EU (`https://qstash-eu-central-1.upstash.io` or `https://qstash.upstash.io`, SDK default) and US (`https://qstash-us-east-1.upstash.io`). Tokens and signing keys are per region; messages are region-specific | https://upstash.com/docs/qstash/howto/multi-region |
| 2.2.6 | Free plan: 1 MB message, 15 min max HTTP response duration, 1,000 messages per day | https://upstash.com/docs/qstash/overall/pricing |
| 2.2.7 | Public IPs of QStash for firewalling | UNKNOWN (not checked; not needed: Worker is public and verifies signatures) |

MISMATCH / CHECK table: contract `docs/contracts/jobs-outbox.md` and `packages/backend_core/src/knowserve_core/qstash.py` (qstash.py states it is not verified against a live QStash).

| # | Contract / code assumption | Documentation says | Verdict |
|---|---|---|---|
| M1 | HS256 JWT in `Upstash-Signature` | "HMAC SHA256" (security page); HS256 not spelled out on the how-to page | Consistent in substance; HS256 literal unconfirmed |
| M2 | Verifies `iss`, `exp`, `nbf`, body hash, optional `sub` | Same claims plus `iat`, `jti` | Consistent. `iat` and `jti` unchecked; fine (no replay store) |
| M3 | Body hash compared after stripping "=" on both sides | base64url, example padded | Consistent |
| M4 | `sub` check is optional (`expected_url` may be None) | `sub` is the destination URL published to, including path (`.../internal/jobs/run`) | CHECK: Worker must pass the exact published URL (publisher builds `base + /internal/jobs/run`); behind a custom domain or redirect the host must match what was published. The contract does not say whether the Worker enforces `sub` |
| M5 | Contract: "verified with the current key, then the next key" | Two keys exist; rotation procedure UNKNOWN | Consistent; procedure to be verified in the spike |
| M6 | Contract: Worker returns 409 (retryable) when leased by another worker | Any non-2xx retries with backoff 12 s, 2 m 28 s, 30 m, 6 h; 3 retries by default | CHECK: default retries (3) may be exhausted for a long-running job, and each retry counts toward the 1,000/day free quota. Retry count is not set by `HttpPublisher` (default used). Exhaustion leaves job `queued` with outbox `published`; the contract does not name a recovery path for published-but-exhausted jobs |
| M7 | Contract: unknown job returns 200 | 2xx ends retries | Consistent |
| M8 | `HttpPublisher` appends the destination URL raw to `/v2/publish/` and sets `Upstash-Forward-X-Correlation-ID` | Format and forward prefix match | Consistent |
| M9 | `HttpPublisher` sends no `Upstash-Deduplication-Id`, `Upstash-Retries` or `Upstash-Timeout` | Dedup window is 10 minutes | CHECK: outbox recovery can republish after a lost ack; at-least-once is already assumed (ING-15), so dedup is optional |
| M10 | Terraform var `qstash_url` is a copy from the console | Per-region URLs; token and keys are region-bound; SDK default is EU | CHECK: token, signing keys and `KS_QSTASH_URL` must all be from the same region |
| M11 | Worker job duration vs timeouts | Free plan 15 min response duration vs Cloud Run default 300 s and max 3600 s | Not a mismatch for the no-op job; for M3 the effective limit is min(Cloud Run timeout, 15 min). Unset Cloud Run timeout means 300 s |
| M12 | `publish_after_commit` is a "best-effort immediate publish" after commit, possibly in the API process after the response | Request-based billing throttles CPU after the response; background work discouraged | RISK: if run after the response is sent on the API (request-based billing), the publish may be delayed or stalled until the next request; the recovery dispatcher covers it, but latency is unmeasured |

### 2.3 Cloud Scheduler OIDC

| # | Fact | Source |
|---|---|---|
| 2.3.1 | OIDC is used for non-`*.googleapis.com` targets; a header token is minted for the job's service account | https://docs.cloud.google.com/scheduler/docs/http-target-auth |
| 2.3.2 | If audience is unspecified, "the entire URL is used as the audience including request parameters"; with URL parameters the audience must not contain them | same |
| 2.3.3 | Creating the job needs `roles/iam.serviceAccountUser` on the job's service account; the target needs an invoker role (e.g. `roles/run.invoker`) for that account; the Cloud Scheduler service agent needs `roles/cloudscheduler.serviceAgent` to mint tokens | same |
| 2.3.4 | JWT claims inside the Scheduler token (email, email_verified, sub) | UNKNOWN (page does not enumerate claims) |
| 2.3.5 | Terraform: `oidc_token` has `service_account_email` and `audience` (registry v8.8.1 docs); repo sets both. The scheduler account is not granted `run.invoker`; not needed because the Worker is `allUsers`, so the token is verified by app code (contract) | https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_scheduler_job |

Contract check: `jobs-outbox.md` verifies audience `KS_DISPATCHER_OIDC_AUDIENCE` and email `KS_DISPATCHER_OIDC_SERVICE_ACCOUNT`. Consistent with the documented behavior. Not documented on retrieved pages: whether `email_verified` must be checked (UNKNOWN; add to the spike).

---

## 3. Backups and durability (DOCUMENTED, no guarantees; OPEN-09, INFRA-08)

| # | Fact (exact wording where quoted) | Source |
|---|---|---|
| 3.1 | Neon history window / restore: Free "6 hours (1 GB limit)"; Launch default 1 day, up to 7 days; Scale default 1 day, up to 30 days. "Free plans cap retention at 6 hours (1 GB)" | https://neon.com/docs/postgres/backup-restore/history-window , https://neon.com/pricing |
| 3.2 | Instant restore is point-in-time on a branch: "Instant restore is only supported for root branches"; the pre-restore state is kept as a backup branch `{branch_name}_old_{head_timestamp}`; "complete overwrite of the database timeline, not a merge or refresh" | https://neon.com/docs/introduction/branch-restore |
| 3.3 | Docs distinguish instant restore and history window ("apply to branch data (point-in-time recovery)") from project-level recovery and from `pg_dump` backups | https://neon.com/docs/postgres/backup-restore/history-window |
| 3.4 | Scheduled automated backups: "available on paid plans only"; manual snapshots limited to 1 (Free), 100 (Launch/Scale) (as summarized from the plans page) | https://neon.com/docs/introduction/plans |
| 3.5 | Terraform provider has `neon_branch_backup_schedule` (automatic snapshot schedule) | https://registry.terraform.io/providers/kislerdm/neon/latest/docs/resources/branch_backup_schedule |
| 3.6 | Neon: recovery after the project or account is deleted; behavior when a free project is suspended or deleted for inactivity | UNKNOWN (not retrieved) |
| 3.7 | R2: "designed to provide 99.999999999% (eleven 9s) of annual durability"; "availability SLA of 99.9%"; "Durability is not a guarantee of data availability. It is a measure of the likelihood of data loss." | https://developers.cloudflare.com/r2/reference/durability/ |
| 3.8 | The R2 durability page does not mention backup or versioning; the R2 limits page also has no mention of object versioning. There is a `cloudflare_r2_bucket_lock` resource (bucket lock) in the provider | https://developers.cloudflare.com/r2/reference/durability/ , https://developers.cloudflare.com/r2/platform/limits/ |
| 3.9 | R2 object versioning / accidental-delete recovery supported | not found in official documentation (do not claim) |
| 3.10 | Restore attempt on the selected Neon plan | not measured, M0 deployment spike not run |

INFRA-08 wording supported: a 6-hour point-in-time window on Neon Free, no scheduled backups on Free, R2 durability stated as a design figure that is not a versioned recovery backup.

---

## 4. Terraform provider coverage (OPEN-06)

Registry data read via the public registry API on 2026-10-24. Latest versions: hashicorp/google 8.8.1 (published 2026-10-23), cloudflare/cloudflare 5.28.1 (2026-10-20), kislerdm/neon 0.18.0 (2026-09-11), upstash/upstash 2.1.0 (2025-08-27). Source: https://registry.terraform.io/v1/providers/{namespace}/{name}/{version} and https://registry.terraform.io/v2/provider-docs/{id}; pages https://registry.terraform.io/providers/hashicorp/google/latest , .../cloudflare/cloudflare/latest , .../kislerdm/neon/latest , .../upstash/upstash/latest.

Caveat: `versions.tf` pins google `~> 6.0` and cloudflare `~> 5.0`. The docs below are for the latest versions (google 8.x), so some argument-level statements may differ in 6.x. Not verified against 6.x docs (UNKNOWN).

| Area | Resource in registry docs | Status | Repo use |
|---|---|---|---|
| Cloud Run v2 service | `google_cloud_run_v2_service` (+ `_iam`, `_job`) | Exists. `deletion_protection` defaults to true (a destroy or replace fails unless set false) | Used; the repo does not set `deletion_protection` (see F6) |
| Cloud Run domain mapping | `google_cloud_run_domain_mapping` (v1 API based) | Exists in registry; the provider page lists no preview flag, but the Cloud Run docs say domain mappings are preview and "not production-ready" (section 6) | Used behind `count` |
| Cloud Scheduler | `google_cloud_scheduler_job` with `http_target.oidc_token` | Exists | Used |
| Secret Manager | `google_secret_manager_secret` (+ `_iam`, `_version`) | Exists; `replication` is required in the docs | Used with `auto {}`; no versions (values entered manually) |
| Artifact Registry | `google_artifact_registry_repository` (+ `_iam`) | Exists | Used |
| Workload Identity Federation | `google_iam_workload_identity_pool`, `_provider` (+ `_iam`) | Exist; `attribute_mapping` and `attribute_condition` supported | Used |
| Billing budget | `google_billing_budget` with `budget_filter`, `amount`, `threshold_rules`, `all_updates_rule` | Exists | Used; needs billing-account level permissions (budgets doc) |
| Cloudflare Pages project | `cloudflare_pages_project`: required `account_id`, `name`, `production_branch` | Exists. Deprecated in docs: `deployments_enabled` (source config), `usage_model` | Repo uses only the three required arguments |
| Cloudflare Pages domain | `cloudflare_pages_domain`: required `account_id`, `project_name`, `name` | Exists. Note: DNS record is not created automatically (needs a DNS record resource) | Used; the repo creates no DNS record, so the domain stays pending until DNS exists (manual step or add `cloudflare_dns_record`) |
| Cloudflare R2 | `cloudflare_r2_bucket`, `_cors`, `_lifecycle`, `_lock` | Exist | NOT in repo (no R2 bucket in Terraform; gap, see F7) |
| Neon | `neon_project` (arg `history_retention_seconds`, `region_id`, `pg_version`), `neon_branch`, `neon_database`, `neon_role`, `neon_endpoint`, `neon_branch_backup_schedule`, `neon_api_key` | Exist (community provider, not Neon-official; owner kislerdm). Neon account/organization creation is not a resource | NOT in repo (manual) |
| Upstash QStash | `upstash_qstash_topic(_v2)`, `upstash_qstash_endpoint`, `upstash_qstash_schedule(_v2)` | Exist; the docs list no resource or data source for QStash tokens or signing keys | NOT in repo (QStash token and signing keys are manual; this matches the secrets-entered-by-user design) |
| Resend | no provider checked | UNKNOWN | n/a |
| Remote state | `backend "gcs"` partial configuration | GCS backend locking behavior: UNKNOWN (Terraform backend docs not retrieved) | Used |

Manual steps implied by the docs: Neon project and database creation (or the community provider), Neon connection string into Secret Manager; QStash account, token, signing keys and URL; Resend domain/API key; Cloudflare DNS records and zone for the domain; secret values; billing account linking.

Repo vs registry findings:

| # | Finding |
|---|---|
| T1 | No resource or argument used in `infra/terraform/*.tf` is absent from the registry docs for the latest versions. |
| T2 | `deployments_enabled` and `usage_model` (deprecated Pages arguments) are not used. No deprecated argument found in use. |
| T3 | Provider pins (google `~> 6.0`, cloudflare `~> 5.0`) are behind the latest google 8.8.1; compatibility with the latest docs is unchecked. Cloudflare 5.x docs were read (5.28.1 matches the pin). |
| T4 | `google_cloud_run_domain_mapping` is flagged by Cloud Run docs as preview (section 6); the Terraform resource exists but the product limitation applies. |
| T5 | `cloudflare_pages_domain` does not create DNS; the repo lacks a DNS record resource. |
| T6 | `terraform validate`, `plan` and apply were not run in this task (research only). |

---

## 5. Regions (DOCUMENTED)

| # | Fact | Source |
|---|---|---|
| 5.1 | Cloud Run Tier 1 regions: asia-east1, asia-northeast1, asia-northeast2, asia-south1, asia-southeast3, europe-north1, europe-north2, europe-southwest1, europe-west1, europe-west4, europe-west8, europe-west9, me-west1, northamerica-south1, us-central1, us-east1, us-east4, us-east5, us-south1, us-west1. All other listed regions (e.g. europe-west2, europe-west3, us-west2, asia-southeast1) are Tier 2 | https://docs.cloud.google.com/run/docs/locations |
| 5.2 | Free tier is "based on us-central1" pricing and applied as a spending discount using Tier 1 pricing, so Tier 2 usage may consume the discount faster. Exact effect UNKNOWN | https://cloud.google.com/run/pricing |
| 5.3 | Cloud Run domain mapping works only in: asia-east1, asia-northeast1, asia-southeast1, europe-north1, europe-west1, europe-west4, us-central1, us-east1, us-east4, us-west1 | https://docs.cloud.google.com/run/docs/mapping-custom-domains |
| 5.4 | Neon regions (AWS): aws-us-east-1 (N. Virginia), aws-us-east-2 (Ohio), aws-us-west-2 (Oregon), aws-eu-central-1 (Frankfurt), aws-eu-west-2 (London), aws-ap-southeast-1 (Singapore), aws-ap-southeast-2 (Sydney), aws-sa-east-1 (Sao Paulo). Azure regions deprecated for new projects | https://neon.com/docs/introduction/regions |
| 5.5 | QStash regions: EU (eu-central-1) and US East (us-east-1) only | https://upstash.com/docs/qstash/howto/multi-region |
| 5.6 | Cloud Scheduler, Secret Manager and Artifact Registry location lists | UNKNOWN (not retrieved) |
| 5.7 | R2 location hints/jurisdictions | UNKNOWN (not retrieved) |
| 5.8 | Co-location latency (Cloud Run to Neon, to QStash, to OpenRouter), and which GCP region is physically near a Neon AWS region | UNKNOWN: no official latency figures; measure in the spike. No region is recommended here |

---

## 6. Custom domain and same-site topology (OPEN-04, INFRA-11)

| # | Fact | Source |
|---|---|---|
| 6.1 | Cloud Run domain mappings are in "preview launch stage" and "not production-ready": "Due to latency issues, they are not production-ready and are not supported at General Availability." Available only in the regions in 5.3 | https://docs.cloud.google.com/run/docs/mapping-custom-domains |
| 6.2 | Domain mapping limits: Google-managed certificates only; domain name up to 64 characters; cannot disable TLS 1.0/1.1; no wildcard certificates; maps only to "/"; SSL provisioning "about 15 minutes but can take up to 24 hours"; third-party CDNs may interfere with validation; CAA must authorize `pki.goog` and `letsencrypt.org` | same |
| 6.3 | Google's recommended alternatives to domain mapping: global external Application Load Balancer, or Firebase Hosting. Cost of the load balancer | UNKNOWN (cost not retrieved; do not assume it is free) | https://docs.cloud.google.com/run/docs/mapping-custom-domains |
| 6.4 | Pages custom domain: subdomains use a CNAME to `<site>.pages.dev`, zone need not be on Cloudflare; apex domains need Cloudflare nameservers; certificates provisioned automatically; CAA records can block issuance; adding a CNAME without registering the domain in the dashboard fails with a 522; up to 100 custom domains on Free | https://developers.cloudflare.com/pages/configuration/custom-domains/ , https://developers.cloudflare.com/pages/platform/limits/ |
| 6.5 | `cloudflare_pages_domain` registry doc: reports `certificate_authority` ("google" or "lets_encrypt") and domain `status`; no DNS creation | https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/pages_domain |
| 6.6 | Whether `*.run.app` and `*.pages.dev` are on the Public Suffix List, and so whether default hosts are same-site with each other | UNKNOWN (not retrieved from an official page; the docs already say not to assume it) |
| 6.7 | Cookie behavior: nothing in the retrieved provider docs states that Cloud Run or Cloudflare strips or rewrites `Set-Cookie` for custom domains. Behavior with a host-only `SameSite=Lax; Secure; HttpOnly` cookie on `api.<domain>` | UNKNOWN: to be tested in M0-08 (AC11) |
| 6.8 | Cookies are host-only on `api.<domain>` and `app.<domain>` is a sibling of it, so a cross-origin credentialed fetch from `app.` to `api.` is same-site (site = registrable domain) but cross-origin: CORS with credentials must be explicit. This is browser standard behavior, not a provider claim, and is not sourced here | n/a (no official provider source) |
| 6.9 | A Cloud Run custom domain served through a Cloudflare proxied record (orange cloud) | UNKNOWN; the Cloud Run page warns that third-party CDNs may interfere with certificate validation |

---

## Findings that change the plan or contracts

| # | Finding | Affects |
|---|---|---|
| F1 | Cloud Run domain mapping (used in `gcp_cloud_run.tf` for `api.<domain>`) is preview, "not production-ready" because of latency, region-limited, with no wildcard or custom certs. INFRA-11 and OPEN-04 assume it. The documented alternatives (global external Application Load Balancer, Firebase Hosting) change cost and topology and may break the $0-5 target. Decision belongs to the Owner and user if the spike confirms | INFRA-11, OPEN-04, M0-AC11, COST-01, `gcp_cloud_run.tf` |
| F2 | Region interplay: the chosen GCP region must be in the domain-mapping list (5.3) if mapping is used; the Terraform `region` variable has no default. Neon and QStash have no GCP regions; latency unknown. No region is recommended | OPEN-06, INFRA-03 |
| F3 | QStash retries (default 3, exponential up to 6 h) and message counts: each retry counts toward 1,000/day free. A 409 from the Worker lease conflict will be retried by QStash with backoff. The contract does not say what happens when retries are exhausted (job stays queued, outbox published) | `docs/contracts/jobs-outbox.md` (ING-13/15) |
| F4 | `qstash.py` consistency with docs holds for claims, body hash, key order; unverified items: key rotation procedure, `sub` enforcement (must equal the published full URL), HS256 literal. Region/URL/token/key consistency is a deployment risk (M10) | `qstash.py`, `config-and-deploy.md` |
| F5 | Request-based billing throttles CPU after the response; best-effort `publish_after_commit` run after the API response may stall. Recovery dispatcher covers loss, but latency and the Scheduler cadence need measuring | `jobs-outbox.md`, `gcp_cloud_run.tf` (no CPU billing mode set) |
| F6 | Cloud Run timeout is not set in Terraform: default 300 s applies. Maximum is 3600 s. Streaming chat is bound by the same timeout. QStash free max response duration is 15 min. Terraform also omits `deletion_protection` (default true per latest docs), which blocks destroy/replace until changed | ING-22, M3 decision note, `gcp_cloud_run.tf` |
| F7 | R2 bucket is not in Terraform, although the registry has resources for it; the Neon project, QStash and Resend are also absent (manual or community providers). The M0 plan expects each resource be labelled managed or manual gap | OPEN-06, INFRA-06 |
| F8 | Neon Free: 6-hour point-in-time window (capped at 1 GB), no scheduled backups, one manual snapshot, 100 CU-hours per project, 1 GB storage, scale to zero after 5 min (documented reactivation "within a few hundred milliseconds"). This supports INFRA-08 wording; no independent backup exists on Free. pgvector data and embeddings must fit 1 GB | INFRA-08, OPEN-09, OPEN-10, M3 |
| F9 | `cloudflare_pages_domain` does not create DNS; custom domain stays pending without a DNS record. Add a resource or document the manual step | `cloudflare.tf`, M0-08 |
| F10 | GCP alerts-only budgets do not cap spend and notify with a delay of hours; COST-04 alerts alone cannot protect the $0-5 target | COST-04, M0-AC09 |
| F11 | Free-tier items shared at the billing-account level (Scheduler 3 jobs, Secret Manager, Artifact Registry 0.5 GiB) can be consumed by other projects on the same account | OPEN-10 |
| F12 | OpenRouter free models are capped (50/day, or 1000/day with 10 credits) and a negative balance blocks even free models; model and token cost are undecided, so chat cost is UNKNOWN | COST-02/03, OPEN-10 |
| F13 | Provider pins (google `~> 6.0`) are far behind latest (8.8.1); docs read for latest only | OPEN-06 |

## Open items needing the M0 deployment spike

| # | Item | Why it can only be measured |
|---|---|---|
| S1 | Cloud Run cold-start time (API and Worker) and effect of startup CPU boost | No documented figure |
| S2 | SSE through Cloud Run (and Cloudflare, if proxied): buffering, behavior at the 300 s default, reconnect needs | Not documented for `text/event-stream` |
| S3 | Worker job end-to-end: QStash delivery, signature verification live (`sub` value, `iss`, key rotation using next key), retry counts, 409 behavior | `qstash.py` is unverified against a live QStash |
| S4 | Scheduler OIDC token claims as seen by the Worker (audience, email, `email_verified`) | Claims not enumerated in docs |
| S5 | `publish_after_commit` latency on request-based billing | CPU throttling after the response |
| S6 | Neon: compute hours consumed (CU size, idle behavior), pgvector enabled on Free, 1 GB sufficiency, restore attempt within the 6-hour window | Not documented / not measured |
| S7 | Artifact Registry image sizes vs 0.5 GiB free | Depends on built images |
| S8 | Custom-domain mapping for `api.<domain>`: preview latency, certificate time, region support; load balancer alternative cost; Pages custom domain and DNS | Domain mapping is preview; costs UNKNOWN |
| S9 | Host-only `SameSite=Lax` cookie and credentialed CORS between `app.` and `api.` | No official provider statement |
| S10 | Public Suffix List status of `*.run.app` and `*.pages.dev` (informational) | Not retrieved |
| S11 | Real monthly cost per service from billing data; domain price; OpenRouter model cost; Resend and QStash actual usage | Only billing data can fill the Measured column |
| S12 | `terraform validate`, `plan`, apply with google 6.x and cloudflare 5.x pins; managed vs manual-gap labels per resource | Not run in this research |
| S13 | Region selection and latency between Cloud Run, Neon and QStash (no recommendation made here) | No official latency data |
| S14 | Billing budget export and alert delivery test | Needs A3 billing account |
