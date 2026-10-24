# Infrastructure, deployment and cost

**Status:** Target spec. Nothing is implemented: there is no Dockerfile, Compose file, Terraform, CI or deployment config in the repo. Proven first by the M0 deployment spike (`../milestones/M0/plan.md`).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| INFRA-01 | Environments: local development uses Docker Compose (API, Worker, local PostgreSQL+pgvector where practical) and Vite for the frontend. CI uses ephemeral test resources. There is one Production environment and **no permanent staging**. | M0 |
| INFRA-02 | Hosting: Cloudflare Pages (static frontend), Google Cloud Run (separate FastAPI API and Worker HTTP services), Neon PostgreSQL+pgvector, Cloudflare R2 (private objects), Upstash QStash (signed deliveries), Cloud Scheduler (outbox recovery) and Resend (email). | M0 |
| INFRA-03 | An **early M0 deployment spike** checks and documents provider interoperability, quotas and free-tier conditions, region and cold starts, Cloud Run streaming and request timeouts, QStash invocation and signatures, and real cost. Uncertainties are recorded, not guaranteed. | M0 |
| INFRA-04 | Production deploys automatically on merge to `main`, and only after a **human-approved milestone PR** with passing CI. GitHub Actions runs the tests, builds the containers, deploys, and runs post-deploy smoke tests. | M0 |
| INFRA-05 | Rollback uses Cloud Run revision rollback where safe. DB migrations are backward-compatible; any rollback-incompatible migration is handled explicitly. | M0 |
| INFRA-06 | Terraform manages the supported resources, IAM and deployment settings, with a protected remote state and locking. **No secret values ever enter Terraform state.** Unsupported IaC gaps are documented. Image release may be independent of `terraform apply`. | M0 |
| INFRA-07 | Secrets live in Google Secret Manager with per-service IAM (API and Worker least privilege). Locally, `.env` is private and git-ignored, and `.env.example` holds placeholders. GitHub Actions authenticates to GCP via OIDC / Workload Identity Federation. | M0 |
| INFRA-08 | Backups are basic provider backups only. The docs must not promise an independent or complete backup solution on free tiers; R2 durability is not a versioned recovery backup (OPEN-09). | M0 (doc) |
| INFRA-09 | Logs and basic metrics follow MON-03 to MON-06. There is no full distributed tracing or Sentry initially. | M0 |
| INFRA-10 | A DB or auth outage fails closed (SEC-13). An LLM outage degrades chat but never prevents reading permitted documents. | M1/M4 |
| INFRA-11 | **Same-site domain topology** (OPEN-04): production serves the frontend and API from subdomains of one registrable domain (e.g. `app.<domain>` on Pages, `api.<domain>` mapped to the Cloud Run API). The default `*.pages.dev` / `*.run.app` hosts are not assumed same-site. The M0 spike verifies custom-domain mapping for both, TLS, the cookie and CORS behavior (AUTH-06, AUTH-19), and the domain's cost against COST-01. If this is infeasible or over budget, the Owner reports the blocker and alternatives to the user; insecure cross-site cookies are not adopted silently. | M0 spike |
| COST-01 | The aspirational target is a working public demo at **$0–5/month** including limited AI usage. This is a goal to verify (INFRA-03), not a guarantee (OPEN-10). | M0 |
| COST-02 | Application-level limits: separate anonymous and registered AI quotas, per-request token caps, and parallel/concurrency caps. Values are OPEN-05. | M4 |
| COST-03 | An atomic global token/dollar budget reservation happens before each LLM call. | M4 |
| COST-04 | Provider billing alerts and an AI kill switch. | M0 (alerts) / M4 (switch) |
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
| INFRA-11 | spike report + deploy smoke | Pages app host and Cloud Run API host on one custom domain; login from `app.` | cookie set host-only on `api.` with `SameSite=Lax`; credentialed call works from `app.`, fails from another origin; domain cost recorded (M0-AC11) |
| COST-01 | spike report | Measured and estimated monthly cost per service at demo traffic | documented with assumptions (M0-AC09); no guarantee claimed |
| COST-02 | integration | Exceed a visitor quota | request refused with a clear message; registered quota unaffected |
| COST-03 | integration | Concurrent requests near the budget limit | total reserved never exceeds the budget |
| COST-04/05 | integration + e2e | Kill switch on | no LLM call made; documents and history available |

## Current implementation (LEGACY)
None of this exists. The legacy app runs locally only: `uvicorn` plus a Celery worker, and it needs local Postgres and Redis. CORS allows `localhost:5173` and `knowserve.vercel.app` (`backend/app/main.py`), which conflicts with INFRA-02 (Pages, not Vercel).

## Related docs
`tech-stack.md`, `../backend/monitoring.md`, `../milestones/M0/plan.md`, `../open-decisions.md`
