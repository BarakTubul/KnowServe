# KnowServe Terraform (M0-05)

One root module. Authored and validated **without cloud access**. Nothing here has been planned or applied. Requirements: INFRA-02, INFRA-05..07, INFRA-11, STACK-23. Interface: `docs/contracts/config-and-deploy.md`, `docs/contracts/jobs-outbox.md`, ADR 0003.

| File | Content |
|---|---|
| `versions.tf`, `backend.tf` | providers; `backend "gcs" {}` (partial config at init) |
| `variables.tf`, `terraform.tfvars.example` | typed, described inputs; placeholders only |
| `gcp_foundation.tf` | APIs, Artifact Registry, 3 service accounts (+ `ks-scheduler` only with the optional scheduler), 5 secret containers (incl. `proxy-shared-secret`) and per-secret accessor bindings |
| `gcp_cloud_run.tf` | `knowserve-api`, `knowserve-worker` (scale to zero, max 2 instances), public invoker, optional Scheduler job (`enable_recovery_scheduler`, default false) |
| `gcp_github_wif.tf` | Workload Identity pool/provider (repo-restricted), deployer roles |
| `cloudflare.tf` | Pages project with the plain production variable `API_ORIGIN` (no custom domain) |
| `check_no_secrets.py` | heuristic guard: no secret versions or secret-looking values in `.tf`/`*.example` |

## Topology (docs/contracts/proxy.md, OPEN-21)
The browser only talks to `https://<pages_project_name>.pages.dev`. Static files come from Cloudflare Pages; `/api/*` is handled by the Pages Function (`apps/frontend/functions`), which forwards to the Cloud Run API at `API_ORIGIN` adding header `X-KS-Proxy-Secret`. The API (`KS_PROXY_SHARED_SECRET`, from Secret Manager `proxy-shared-secret`) rejects any non-health request without the correct header (403 `DIRECT_ACCESS_DENIED`). `KS_API_ALLOWED_ORIGINS` is the single pages.dev origin (variable `api_allowed_origins`, validated: exactly one https origin, no `*`). The Worker is not behind the proxy (QStash calls it directly, signature-authenticated). Terraform sets only the plain Pages variable `API_ORIGIN` (variable `api_origin`); it never touches the proxy secret value.

## Design notes
- **Secrets:** Terraform creates only the five secret *containers* (`database-url`, `qstash-token`, `qstash-current-signing-key`, `qstash-next-signing-key`, `proxy-shared-secret`) and `secretAccessor` bindings (API: database-url, qstash-token, proxy-shared-secret; Worker: the four QStash/database ones, never the proxy secret). No `google_secret_manager_secret_version`, no values, no `KS_DISPATCHER_LOCAL_TOKEN`. Cloud Run references secrets with `secret_key_ref` at version `latest`, so values never enter state.
- **Images:** variables default to a public placeholder image. `lifecycle.ignore_changes` on the image means the deploy workflow rolls revisions without Terraform drift.
- **Public invoker (`allUsers`) is required on both services**: browsers and QStash cannot present Google credentials. This is network reachability only. The API authenticates with its own session/CSRF rules; the Worker authenticates `/internal/jobs/run` (QStash signature) itself, and `/internal/outbox/dispatch` (Scheduler Google OIDC: audience + service account email) only exists when the optional recovery dispatcher is enabled. URL secrecy is not authentication (SEC-14). Health routes are intentionally open.
- **Worker URL and audience:** a Cloud Run service cannot reference its own URL, so `worker_public_url` (`KS_WORKER_PUBLIC_URL`) is a **required variable** (https, validated). Apply once with the planned Worker URL (the URL shown by the console after a first deploy), then set the real value if it differed.
- **Optional scheduled recovery (default off):** `enable_recovery_scheduler=false` creates no Cloud Scheduler job, no `ks-scheduler` account and no `cloudscheduler` API enablement, and sets no dispatcher env on the Worker. M0 recovery is an admin-initiated manual retry. When true, `scheduler_cron`, `scheduler_time_zone` and `dispatcher_oidc_audience` become required (validated) and the Worker gets `KS_ENABLE_RECOVERY_DISPATCHER=true` plus the OIDC settings. Enabling needs a user decision (STACK-23).
- **Billing budgets:** not managed by Terraform. The user keeps manually configured budgets/alerts (COST-04); a budget only alerts and does not cap spend.
- **Spike operator job routes (default off):** `enable_spike_job_ops` (needs non-empty `spike_token_creator_emails`) creates the role-less service account `ks-spike-operator`, grants `roles/iam.serviceAccountOpenIdTokenCreator` on it to those Google accounts only, and sets plain env `KS_ENABLE_SPIKE_JOB_OPS`, `KS_SPIKE_OPERATOR_EMAILS` (= that service account's email) and `KS_SPIKE_OIDC_AUDIENCE` (= `api_origin`) on the API; `enable_spike_failure_hooks` (requires job ops) sets `KS_ENABLE_SPIKE_FAILURE_HOOKS`, for the isolated spike environment only. No new secrets. Your Google account email belongs only in the git-ignored `terraform.tfvars`.
- **Scaling:** both Cloud Run services use `min_instance_count = 0` and `max_instance_count = 2` to cap cost.
- **Deployer minimal roles:** `run.developer` on each service, `artifactregistry.writer` on the repo, `serviceAccountUser` on the two runtime accounts only, impersonable only by the single WIF subject `repo:<owner>/<repo>:environment:production`. The provider accepts a token only if the numeric repository and owner IDs, the repository name, `refs/heads/main`, the `production` environment, that exact `sub` and the `deploy.yml` workflow path all match (`docs/contracts/ci-and-branch-protection.md`).

## Bootstrap (the USER does this once, outside Terraform)
1. Create the GCP project, link billing.
2. Create a GCS bucket for state (versioning on, uniform access, restricted IAM) and note its name.
3. Enable the APIs Terraform itself needs: `serviceusage.googleapis.com`, `cloudresourcemanager.googleapis.com`, `iam.googleapis.com` (Terraform enables the rest).
4. Provide an identity for the first apply with enough rights to create the above resources (user account via `gcloud auth application-default login`, or a short-lived impersonated account). Do not create JSON keys.
5. Create a Cloudflare API token scoped to Pages; export it as `CLOUDFLARE_API_TOKEN` in the shell, never in files.
6. Manual third-party setup (see below): Neon, Upstash QStash, Cloudflare R2, Resend.
7. WIF trust is created by this module (`gcp_github_wif.tf`); the first apply must run with the user's own credentials since CI cannot yet authenticate.

## Manual steps in order (the USER; nothing here has been run)
1. Create the GCS state bucket; create the GCP project and link billing; enable `serviceusage`, `cloudresourcemanager`, `iam` (Bootstrap above).
2. Fill `backend.hcl` and `terraform.tfvars`. `api_allowed_origins` is `["https://<pages_project_name>.pages.dev"]` (approved: Pages project `knowserve-m0-spike`, region `europe-west1`). `api_origin` is unknown before the first apply: use a placeholder https URL.
3. `terraform apply -target=google_project_service.apis -target=google_secret_manager_secret.secrets`.
4. Generate a long random value and enter it as the first version of Secret Manager secret `proxy-shared-secret` (stdin or protected file, e.g. `gcloud secrets versions add proxy-shared-secret --data-file=-`); enter the other secret values too.
5. Full `terraform apply`. Read output `api_url`; set `api_origin` to it and apply again so the Pages variable `API_ORIGIN` is correct. Check that output `app_url` equals `api_allowed_origins[0]`.
6. Set the Pages secret with the SAME value: `wrangler pages secret put PROXY_SHARED_SECRET --project-name <pages_project_name>` (interactive prompt; not in CI, not in Terraform).
7. Set the GitHub variables and the `production` environment (`docs/contracts/ci-and-branch-protection.md`), then run the deploy workflow (it deploys the Function with the static files and smoke-tests through the proxy).

Secret rotation (contract): add a new version of `proxy-shared-secret`, roll a new API revision (Cloud Run reads `latest` at start), then update the Pages secret with `wrangler pages secret put` and redeploy. Requests get 403 between the two steps; rotate in a quiet window.

## Future authorized plan/apply (documented only; do not run without approval A3/A4)
```
cd infra/terraform
cp backend.hcl.example backend.hcl            # fill in bucket
cp terraform.tfvars.example terraform.tfvars  # fill in values
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive && terraform validate
python check_no_secrets.py
terraform plan -out=tfplan      # review: no secret values may appear
terraform apply tfplan
```
Services reference secret version `latest`: **populate the secrets before the Cloud Run services can start a revision**. Practical order: `terraform apply -target=google_project_service.apis -target=google_secret_manager_secret.secrets` first, enter secret values, then the full apply.

## Entering secret values (user only, never Terraform)
Use the console or `gcloud secrets versions add <secret-id> --data-file=-` reading from stdin or a protected file, for each id in output `secret_ids`. Values must never be placed in `.tfvars`, `.tf`, shell history or CI variables. Rotate by adding a new version.

## Manual / unverified resources (not in Terraform)
- **Neon** (project, database, pgvector extension, connection string -> `database-url`): no provider resource authored; manual.
- **Upstash QStash** (token, signing keys, region URL): no provider resource authored; manual. `qstash_url` variable is copied from the console.
- **Cloudflare R2** bucket and credentials: not authored here (no M0 requirement in this task); manual until a later milestone.
- **Resend**: manual, later milestone.
- **Custom domains:** none. The Cloud Run domain mapping, `api_custom_domain`, the Pages domain resource and `app_custom_domain` were removed (OPEN-21 route: pages.dev + Pages Function). No domain is required.
- **Pages secret `PROXY_SHARED_SECRET`:** set manually with wrangler, never in Terraform (see below).
- **GitHub** repository settings / secrets: outside this module.

## UNVERIFIED (proxy route)
- Pages Function streaming: SSE arriving incrementally through the deployed Function.
- `Set-Cookie` pass-through with attributes on the deployed edge.
- Whether injecting the Pages production variable `API_ORIGIN` through the Cloudflare Terraform provider v5 (`deployment_configs.production.env_vars`) works as expected (schema-validated only; possible drift, and a later apply might replace settings or drop a secret set with wrangler).
- Client IP forwarding (`CF-Connecting-IP` to `X-KS-Client-IP`).
- That `wrangler pages deploy` from `apps/frontend` bundles `functions/` and uses `dist/_routes.json` as expected (the workflow checks both files exist; the run itself is untested).

## UNVERIFIED ASSUMPTIONS
`terraform validate` (run with providers google 6.50.0 and cloudflare 5.28.1 per the lock file) proves syntax and provider schema only. Not verified against any real cloud:
1. That `plan`/`apply` succeed, IAM propagation, and API enablement ordering.
2. Provider major versions `~> 6.0` (google) and `~> 5.0` (cloudflare): Cloudflare v5 attribute names for `cloudflare_pages_project` were only schema-validated; behavior (build config, drift, import needs) unknown.
3. Region: `region` has no default; the approved value is `europe-west1` (Cloud Run and Artifact Registry support it; free-tier applicability unverified). The first apply must also confirm the real pages.dev host equals `api_allowed_origins[0]`.
4. Free-tier eligibility and costs of every resource, including Secret Manager and Artifact Registry: not asserted; see M0-09 research with dated sources.
5. (Removed: custom domains are no longer part of the design.)
6. (Removed: Terraform no longer manages a billing budget; the user's manual budgets only alert and do not cap spend.)
7. Startup probe `/health/live` assumes the apps' health routes exist in the deployed image (the placeholder bootstrap image will not serve them, so the first revision may fail its probe; may need the probe removed or a real first image).
8. The WIF claim names (`repository_id`, `repository_owner_id`, `environment`, `workflow_ref`, `sub`) are taken from GitHub's documentation and are unverified until a real GitHub Actions run; a wrong claim fails closed (no deployer token). The deploy workflow's own needs (e.g. migrations needing `database-url`, which the deployer deliberately cannot read) are unresolved and need an Owner decision.
9. Public Cloud Run may be blocked by an organization policy (domain restricted sharing); then the design needs revisiting.
10. Neon and QStash have no authored provider resources; their Terraform coverage is for M0-09 to assess.

## First-apply findings (2026-10-31)
- Cloudflare rejected the Pages project with error 8000066 ("`fail_open` must be equal for production and preview"). `cloudflare.tf` now sets `fail_open = false` in both environments (fail closed).
- Cloud Run returns a service-level `scaling` block (`min 0`, `manual 0`) that the provider planned to remove on every run; both services now ignore that block (scaling is set only on the template: min 0, max 2).
- Each Cloud Run service answers on two hostnames: the hash form (`https://<service>-<hash>-ew.a.run.app`, shown as `status.url`) and the project-number form (`https://<service>-<project number>.<region>.run.app`). Both were verified to reach the service. The configuration uses the project-number form.
- `enable_spike_endpoints` (default false) sets `KS_ENABLE_SPIKE_ENDPOINTS` on the API: the public test routes `/v1/spike/cookie|echo|stream` (reachable through the Pages proxy; `stream` can hold a connection up to 600 s). `/v1/spike/echo` also returns the client IP the Pages Function forwarded (M0-AC11). Enable only briefly, then re-apply with it false. Changing it creates a new Cloud Run revision but does not change the image (image is in `ignore_changes`; roll images with `gcloud run deploy`).
- **Pages secret and Terraform:** `PROXY_SHARED_SECRET` is set with `wrangler pages secret put`; Cloudflare then reports it back as a production env var (`secret_text`, empty value), which the provider planned to strip. `cloudflare_pages_project.app` therefore has `ignore_changes` on `deployment_configs.production.env_vars["PROXY_SHARED_SECRET"]`. Never apply a plan that shows that variable being changed or removed; if the ignore does not take effect, widen it to the whole production `env_vars` and manage `API_ORIGIN` by hand.
- `github_environment` (default `production`; the spike sets `spike`) is the GitHub Environment name the Workload Identity condition and the single impersonation subject trust. Changing it updates the provider in place and replaces the `deployer_wif` binding (preview: 1 add, 1 change, 1 destroy); apply it before the first deploy that uses the new name.
