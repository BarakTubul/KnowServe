# KnowServe Terraform (M0-05)

One root module. Authored and validated **without cloud access**. Nothing here has been planned or applied. Requirements: INFRA-02, INFRA-05..07, INFRA-11, COST-04. Interface: `docs/contracts/config-and-deploy.md`, `docs/contracts/jobs-outbox.md`, ADR 0003.

| File | Content |
|---|---|
| `versions.tf`, `backend.tf` | providers; `backend "gcs" {}` (partial config at init) |
| `variables.tf`, `terraform.tfvars.example` | typed, described inputs; placeholders only |
| `gcp_foundation.tf` | APIs, Artifact Registry, 4 service accounts, secret containers and per-secret accessor bindings |
| `gcp_cloud_run.tf` | `knowserve-api`, `knowserve-worker`, public invoker, optional API domain mapping, Scheduler job |
| `gcp_github_wif.tf` | Workload Identity pool/provider (repo-restricted), deployer roles |
| `gcp_budget.tf` | billing budget with threshold alerts |
| `cloudflare.tf` | Pages project, optional app custom domain |
| `check_no_secrets.py` | heuristic guard: no secret versions or secret-looking values in `.tf`/`*.example` |

## Design notes
- **Secrets:** Terraform creates only the four secret *containers* (`database-url`, `qstash-token`, `qstash-current-signing-key`, `qstash-next-signing-key`) and `secretAccessor` bindings (API: database-url, qstash-token; Worker: all four). No `google_secret_manager_secret_version`, no values, no `KS_DISPATCHER_LOCAL_TOKEN`. Cloud Run references secrets with `secret_key_ref` at version `latest`, so values never enter state.
- **Images:** variables default to a public placeholder image. `lifecycle.ignore_changes` on the image means the deploy workflow rolls revisions without Terraform drift.
- **Public invoker (`allUsers`) is required on both services**: browsers and QStash cannot present Google credentials. This is network reachability only. The API authenticates with its own session/CSRF rules; the Worker authenticates `/internal/jobs/run` (QStash signature) and `/internal/outbox/dispatch` (Scheduler Google OIDC: audience + service account email) itself. URL secrecy is not authentication (SEC-14). Health routes are intentionally open.
- **Worker URL and audience:** a Cloud Run service cannot reference its own URL, so `worker_public_url` (`KS_WORKER_PUBLIC_URL`) and `dispatcher_oidc_audience` (Scheduler token audience and `KS_DISPATCHER_OIDC_AUDIENCE`) are **required variables** (https, validated). The Worker refuses to start in production without them. Apply once with the planned Worker URL (a custom domain, or the URL shown by the console after a first deploy), then set the real value if it differed. Cadence (`scheduler_cron`) has no default and no recommendation.
- **Deployer minimal roles:** `run.developer` on each service, `artifactregistry.writer` on the repo, `serviceAccountUser` on the two runtime accounts only, impersonable only by the repository-restricted WIF principal.

## Bootstrap (the USER does this once, outside Terraform)
1. Create the GCP project, link billing.
2. Create a GCS bucket for state (versioning on, uniform access, restricted IAM) and note its name.
3. Enable the APIs Terraform itself needs: `serviceusage.googleapis.com`, `cloudresourcemanager.googleapis.com`, `iam.googleapis.com` (Terraform enables the rest).
4. Provide an identity for the first apply with enough rights to create the above resources (user account via `gcloud auth application-default login`, or a short-lived impersonated account). Do not create JSON keys.
5. Create a Cloudflare API token scoped to Pages (and DNS only if custom domains are used); export it as `CLOUDFLARE_API_TOKEN` in the shell, never in files.
6. Manual third-party setup (see below): Neon, Upstash QStash, Cloudflare R2, Resend.
7. WIF trust is created by this module (`gcp_github_wif.tf`); the first apply must run with the user's own credentials since CI cannot yet authenticate.

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
- **Custom domains** (`api_custom_domain`, `app_custom_domain`): authored but disabled by default; behavior unverified (M0-08).
- **GitHub** repository settings / secrets: outside this module.

## UNVERIFIED ASSUMPTIONS
`terraform validate` (run with providers google 6.50.0 and cloudflare 5.28.1 per the lock file) proves syntax and provider schema only. Not verified against any real cloud:
1. That `plan`/`apply` succeed, IAM propagation, and API enablement ordering.
2. Provider major versions `~> 6.0` (google) and `~> 5.0` (cloudflare): Cloudflare v5 attribute names for `cloudflare_pages_project`/`cloudflare_pages_domain` were only schema-validated; behavior (build config, drift, import needs) unknown.
3. Region choice: `region` has no default; Cloud Run, Artifact Registry and Scheduler locations must be supported and are decided in M0-09.
4. Free-tier eligibility and costs of every resource, including Secret Manager, Scheduler, Artifact Registry and budgets: not asserted; see M0-09 research with dated sources.
5. `google_cloud_run_domain_mapping` availability in the chosen region and its TLS/cookie behavior (INFRA-11); Pages custom-domain support and DNS setup for a domain not on Cloudflare.
6. The budget only alerts, it does not cap spend; the notification path (default billing-admin email vs `budget_notification_channel_ids`) is unverified.
7. Startup probe `/health/live` assumes the apps' health routes exist in the deployed image (the placeholder bootstrap image will not serve them, so the first revision may fail its probe; may need the probe removed or a real first image).
8. The WIF condition restricts by repository only, not branch/environment; the deploy workflow's own needs (e.g. migrations needing `database-url`, which the deployer deliberately cannot read) are unresolved and need an Owner decision.
9. Public Cloud Run may be blocked by an organization policy (domain restricted sharing); then the design needs revisiting.
10. Neon and QStash have no authored provider resources; their Terraform coverage is for M0-09 to assess.
