# KnowServe Terraform (M0-05)

One root module. Authored and validated **without cloud access**. Nothing here has been planned or applied. Requirements: INFRA-02, INFRA-05..07, INFRA-11, STACK-23. Interface: `docs/contracts/config-and-deploy.md`, `docs/contracts/jobs-outbox.md`, ADR 0003.

| File | Content |
|---|---|
| `versions.tf`, `backend.tf` | providers; `backend "gcs" {}` (partial config at init) |
| `variables.tf`, `terraform.tfvars.example` | typed, described inputs; placeholders only |
| `gcp_foundation.tf` | APIs, Artifact Registry, 3 service accounts (+ `ks-scheduler` only with the optional scheduler), 6 secret containers (incl. `proxy-shared-secret` and, from M1, `migration-database-url`) and per-secret accessor bindings |
| `gcp_cloud_run.tf` | `knowserve-api`, `knowserve-worker` (scale to zero, max 2 instances), public invoker, optional Scheduler job (`enable_recovery_scheduler`, default false) |
| `gcp_migration_job.tf` | M1: `knowserve-migrate` Cloud Run job, its own service account, deployer grants on the job; optional `knowserve-admin-seed` job |
| `gcp_github_wif.tf` | Workload Identity pool/provider (repo-restricted), deployer roles |
| `cloudflare.tf` | Pages project with the plain production variable `API_ORIGIN` (no custom domain) |
| `check_no_secrets.py` | heuristic guard: no secret versions or secret-looking values in `.tf`/`*.example` |

## Topology (docs/contracts/proxy.md, OPEN-21)
The browser only talks to `https://<pages_project_name>.pages.dev`. Static files come from Cloudflare Pages; `/api/*` is handled by the Pages Function (`apps/frontend/functions`), which forwards to the Cloud Run API at `API_ORIGIN` adding header `X-KS-Proxy-Secret`. The API (`KS_PROXY_SHARED_SECRET`, from Secret Manager `proxy-shared-secret`) rejects any non-health request without the correct header (403 `DIRECT_ACCESS_DENIED`). `KS_API_ALLOWED_ORIGINS` is the single pages.dev origin (variable `api_allowed_origins`, validated: exactly one https origin, no `*`). The Worker is not behind the proxy (QStash calls it directly, signature-authenticated). Terraform sets only the plain Pages variable `API_ORIGIN` (variable `api_origin`); it never touches the proxy secret value.

## Design notes
- **Secrets:** Terraform creates only the six secret *containers* (`database-url`, `migration-database-url` (M1, readable only by the migration job), `qstash-token`, `qstash-current-signing-key`, `qstash-next-signing-key`, `proxy-shared-secret`) and `secretAccessor` bindings (API: database-url, qstash-token, proxy-shared-secret; Worker: the four QStash/database ones, never the proxy secret). No `google_secret_manager_secret_version`, no values, no `KS_DISPATCHER_LOCAL_TOKEN`. Cloud Run references secrets with `secret_key_ref` at version `latest`, so values never enter state.
- **Images:** variables default to a public placeholder image. `lifecycle.ignore_changes` on the image means the deploy workflow rolls revisions without Terraform drift.
- **Public invoker (`allUsers`) is required on both services**: browsers and QStash cannot present Google credentials. This is network reachability only. The API authenticates with its own session/CSRF rules; the Worker authenticates `/internal/jobs/run` (QStash signature) itself, and `/internal/outbox/dispatch` (Scheduler Google OIDC: audience + service account email) only exists when the optional recovery dispatcher is enabled. URL secrecy is not authentication (SEC-14). Health routes are intentionally open.
- **Worker URL and audience:** a Cloud Run service cannot reference its own URL, so `worker_public_url` (`KS_WORKER_PUBLIC_URL`) is a **required variable** (https, validated). Apply once with the planned Worker URL (the URL shown by the console after a first deploy), then set the real value if it differed.
- **Optional scheduled recovery (default off):** `enable_recovery_scheduler=false` creates no Cloud Scheduler job, no `ks-scheduler` account and no `cloudscheduler` API enablement, and sets no dispatcher env on the Worker. M0 recovery is an admin-initiated manual retry. When true, `scheduler_cron`, `scheduler_time_zone` and `dispatcher_oidc_audience` become required (validated) and the Worker gets `KS_ENABLE_RECOVERY_DISPATCHER=true` plus the OIDC settings. Enabling needs a user decision (STACK-23).
- **Billing budgets:** not managed by Terraform. The user keeps manually configured budgets/alerts (COST-04); a budget only alerts and does not cap spend.
- **Spike operator job routes (default off):** `enable_spike_job_ops` (needs non-empty `spike_token_creator_emails`) creates the role-less service account `ks-spike-operator`, grants `roles/iam.serviceAccountOpenIdTokenCreator` on it to those Google accounts only, and sets plain env `KS_ENABLE_SPIKE_JOB_OPS`, `KS_SPIKE_OPERATOR_EMAILS` (= that service account's email) and `KS_SPIKE_OIDC_AUDIENCE` (= `api_origin`) on the API; `enable_spike_failure_hooks` (requires job ops) sets `KS_ENABLE_SPIKE_FAILURE_HOOKS`, for the isolated spike environment only. No new secrets. Your Google account email belongs only in the git-ignored `terraform.tfvars`.
- **Scaling:** both Cloud Run services use `min_instance_count = 0` and `max_instance_count = 2` to cap cost.
- **Deployer minimal roles:** `run.developer` on each service, `artifactregistry.writer` on the repo, `serviceAccountUser` on the two runtime accounts only, impersonable only by the single WIF subject `repo:<owner>/<repo>:environment:production`. The provider accepts a token only if the numeric repository and owner IDs, the repository name, `refs/heads/main`, the `production` environment, that exact `sub` and the `deploy.yml` workflow path all match (`docs/contracts/ci-and-branch-protection.md`).

## M1 additions (task M1-07; authored and validated locally only, nothing planned or applied)

> **Every step under "Owner-only cloud actions" below needs the Owner's separate, explicit approval.** `terraform fmt -check` and `terraform validate` (after `init -backend=false`) are the only Terraform commands run for this work.

### Migration job (OPEN-26 D2, INFRA-07, M1-AC11)
`gcp_migration_job.tf` adds:

| Resource | Purpose |
|---|---|
| `google_cloud_run_v2_job.migrate` (`knowserve-migrate`) | Runs the **API image** with `alembic -c packages/backend_core/alembic.ini upgrade head`. One task, no retries, 600 s timeout. Env: `KS_ENV`, `KS_LOG_LEVEL`, and `KS_DATABASE_URL` from the secret below. The image is in `ignore_changes`: the deploy workflow points the job at the deployed digest, as it does for the services |
| `google_service_account.migrate` (`ks-migrate-runtime`) | The job's own identity |
| secret container `migration-database-url` (in `gcp_foundation.tf`) | The DDL role's connection string. **Terraform creates no version.** Its only accessor is `ks-migrate-runtime`; the API, the Worker and the deployer have no binding on it |
| `google_cloud_run_v2_job_iam_member.deployer_migrate` | The deployer gets `roles/run.developer` on this one job (update the image, execute, read executions for `--wait`) |
| `google_service_account_iam_member.deployer_acts_as_migrate` | The deployer may act as `ks-migrate-runtime` (needed to update a job that runs as it) |
| `google_cloud_run_v2_job.admin_seed` (optional) | See "Admin provisioning" |

The Dockerfile needed no change. `apps/api/Dockerfile` already puts `alembic` (a dependency of `knowserve-core`) on the venv `PATH` and copies `alembic.ini` and `migrations/` to `/app/packages/backend_core/`, with `WORKDIR /app`. The job overrides `command` and `args`, so the uvicorn `CMD` is not used. `migrations/env.py` reads only `KS_DATABASE_URL`, so no other setting is needed.

**Deploy flow** (`.github/workflows/deploy.yml`). Build and push the images; `gcloud run jobs update knowserve-migrate --image <api digest>`; `gcloud run jobs execute knowserve-migrate --wait`; only then roll `knowserve-api` and `knowserve-worker`. A failed execution fails the step, so the rollout steps are skipped and the old revisions keep serving. The deployer reads no secret.

`RUN_MIGRATIONS` (a GitHub Environment variable) is now **on unless it is exactly `false`**. Before M1 it was off unless `true`. `false` is the explicit skip for an environment whose job is not applied. Migrations must stay backward compatible with the previous API revision, because that revision keeps serving while the new schema is applied (expand, then contract).

`auth-check` mode now also asserts that the deployer is **denied** `migration-database-url`, and reports whether it can describe the job (a warning, not a failure, before the job exists).

**What the deployer grants allow.** The deployer cannot read the migration secret. It can run the job and change the job's image, command and args, so a compromised deploy workflow could run arbitrary code with the DDL credential. That is inherent to letting CI run migrations. The deployer also keeps `roles/run.developer` on the API and Worker services and `actAs` on their service accounts (as in M0), so a compromised deploy could in principle run code with those credentials too; the claim "cannot read the database secret" means direct secret reads only, which is what `auth-check` tests. The controls are the WIF conditions (repository ids, `refs/heads/main`, the `deploy.yml` path, one environment), the CI gate and the environment's protection rules (a required reviewer is recommended). `roles/run.developer` on the job also allows deleting it. A tighter custom role (`run.jobs.get`, `run.jobs.update`, `run.jobs.run`, `run.executions.get`) was not authored, because whether it is enough for `jobs update` and `--wait` cannot be verified without a cloud run. Swapping the role is a small change in `gcp_migration_job.tf`.

#### Owner steps for the migration job (all Owner-only, in this order)
1. **Neon roles (done 2026-11-06, see `infra/neon/runtime-roles.sql`).** `neondb_owner` owns every table, so it is the DDL/migration role. The runtime role `ks_runtime` was created **by SQL as `NOLOGIN` with no password** (a console-created role would have been a member of `neon_superuser` with `CREATEROLE`, `CREATEDB`, `REPLICATION` and `BYPASSRLS`, and Neon rejects a pre-hashed password), then granted DML only on `jobs`, `outbox` and `spike_vector_probe`, `USAGE, SELECT` on sequences, and default privileges `FOR ROLE neondb_owner` so the tables created by migration 0002 are visible to it. It has no role memberships, no DDL and no access to `alembic_version` (verified read-only). **Still to do at the `database-url` cutover:** `ALTER ROLE ks_runtime LOGIN PASSWORD '<fresh>'`, the real pooled-login test (SELECT and INSERT with ROLLBACK, DDL denied), then publish the URLs.
2. **Secret values.** `migration-database-url` is the DDL role's **direct** (non-pooler) host URL. `database-url` gets a new version with the **pooled** DML role URL (Cloud Run reads `latest`). Enter both with `gcloud secrets versions add <id> --data-file=-` from stdin, never from a file in the repo or from CI. **Before adding the new `database-url` version** (and after `ALTER ROLE ks_runtime LOGIN PASSWORD ...` with a freshly generated password that is never printed or stored elsewhere), connect with exactly the new URL and run a SELECT, an INSERT and a ROLLBACK against a table; services read `latest` at instance start, so a role with missing grants would break cold starts later. Do not disable the previous version until M1-AC11 has passed, so you can roll back.
3. **Apply order.** `terraform apply -target=google_project_service.apis -target=google_secret_manager_secret.secrets` (creates the new container), enter the values, then the full apply. `firebase_project_id` must be in `terraform.tfvars` first. Review `terraform plan` before any apply: no secret value may appear, and the API gets a new revision for the new env.
4. **The first execution belongs to the deploy workflow.** The job is created with the bootstrap image; do not execute it by hand before a deploy has set the image. Run the deploy workflow in `auth-check` mode first (it checks the denial and the job), then in `deploy` mode.
5. **Evidence for M1-AC11.** The plan review; the job execution log (`gcloud run jobs executions list --job knowserve-migrate`, Cloud Logging); revision `0002` in `alembic_version` on the spike database; `gcloud secrets get-iam-policy migration-database-url` showing only `ks-migrate-runtime`; and the deployer's `auth-check` denial.

### Admin provisioning (D4, AUTH-04)
The Admin is created by hand in the Firebase Console (Email/Password or Google). **Order and email verification:** the Firebase account must exist first (the seed command promotes its uid to Admin and refuses an unknown or Demo uid). A user created with "Add user" in the console has an **unverified** email, and KnowServe refuses a password session for an unverified email (403 `EMAIL_NOT_VERIFIED`), so verify it before the first sign-in: send the verification mail from the console, or sign in once with Google and bound by an idempotent command, `python -m knowserve_api.admin_seed`. Another agent writes that command; it is not part of this task. It runs through the same mechanism as the migrations: a Cloud Run job in the API image, but with the **runtime DML-only identity** (the API service account and `database-url`), because creating the Admin row needs no DDL (Owner decision, 2026-11-06).

- Terraform: `enable_admin_seed_job = true` creates `knowserve-admin-seed` (command `python`, args `-m knowserve_api.admin_seed`). It is **off by default** and, when enabled, holds only the DML credential. The deployer has no grant on it and CI never runs it.
- The Admin identity is passed at execution time, so it never enters Terraform state or the repository. No password is involved or stored anywhere:
  ```
  gcloud run jobs update knowserve-admin-seed --image <current API digest> --region europe-west1
  gcloud run jobs execute knowserve-admin-seed --wait --region europe-west1 \
    --update-env-vars KS_ADMIN_FIREBASE_UID=<uid from the Firebase Console>,KS_ADMIN_EMAIL=<admin email>
  ```
- After the run, confirm that the log shows counts or an "already provisioned" result only. Then set `enable_admin_seed_job = false` and apply, which removes the job.
- For the command's author: the job sets `KS_ENV=production`, `KS_FIREBASE_PROJECT_ID` and `KS_DATABASE_URL`, and carries no proxy or QStash secrets, so the command must not require the full API settings. It needs only INSERT/UPDATE on `users`, so a DML credential would suffice. The DDL credential is used here only to avoid a third role and secret; tell the Owner if that should change.

### Configuration wiring (no secrets)
| Key | Where | Source |
|---|---|---|
| `KS_FIREBASE_PROJECT_ID` | API (and the admin-seed job) | Required variable `firebase_project_id` (production: `knowserve-m0-spike`; a plain env var, not a secret) |
| `KS_SESSION_COOKIE_NAME`, `KS_SESSION_TTL_SECONDS`, `KS_AUTH_MAX_AGE_SECONDS`, `KS_DEMO_RETENTION_SECONDS`, `KS_DEMO_START_LIMIT`, `KS_DEMO_START_WINDOW_SECONDS`, `KS_QUOTA_*_DAILY`, `KS_AI_GLOBAL_DAILY_QUOTA`, `KS_AI_KILL_SWITCH` | API | Optional map `api_m1_settings`. **Empty by default, so the application defaults apply.** Keys are allow-listed; a secret key name fails validation |
| `KS_DEMO_RETENTION_SECONDS`, `KS_DEMO_CLEANUP_BATCH_SIZE` | Worker | Optional map `worker_m1_settings`, same rules |
| `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID` | Frontend build | **Not created by Terraform.** The page is built in the deploy workflow, not by Cloudflare, so these are public **GitHub Environment variables** (not secrets) that the "Build frontend" step passes to `pnpm build`; the step fails if one is empty. Cloudflare Pages build variables would have no effect on this pipeline. The values come from the Firebase web app config (Project settings, General, Your apps) |

The Worker does not get `KS_FIREBASE_PROJECT_ID`, because the contract lists it for the API only. If an M1 settings validator later requires it for the Worker, add it to `gcp_cloud_run.tf`.

### Demo cleanup schedule (N4)
Prepared, not created: `infra/qstash/README.md` and `infra/qstash/demo-cleanup-schedule.sh` (a dry run unless told otherwise). It needs the Owner's approval and a prior check of schedule availability and quotas. No Cloud Scheduler and no Terraform resource.

### Firebase setup checklist (OPEN-26 D3, N2, N3; the Owner performs it in the console of `knowserve-m0-spike`)
Terraform does not manage Firebase (coverage unverified), so these steps are manual. Use the **standard** Firebase Authentication. Do **not** upgrade to Identity Platform. If any step seems to need an upgrade, stop and report.

1. **Sign-in providers** (Authentication, Sign-in method): enable **Email/Password** (leave "Email link (passwordless)" off), **Google** (set the project support email) and **Anonymous**.
2. **Email enumeration protection:** enabled (Authentication, Settings, User actions).
3. **One account per email address:** selected (Settings, User account linking).
4. **Authorized domains:** `knowserve-m0-spike.pages.dev` is listed. Keep the default `firebaseapp.com` entries; keep `localhost` only if testing locally against the real project.
5. **Email templates:** for both **Email address verification** and **Password reset**, set the action URL to `https://knowserve-m0-spike.pages.dev/auth/action`. Keep the default sender (no custom domain in M1; spam placement is a known risk).
6. **Password policy** (Settings, Password policy): minimum length **8**, no uppercase, lowercase, numeric or special-character requirements, enforcement mode **Require**. **VERIFY first** that this is configurable on the standard (non Identity Platform) project, by opening the page and confirming that the policy can be saved in `Require` mode. **If it is unavailable or the console asks for an upgrade, stop, do not upgrade, and report to the Owner** (AUTH-03, N3).
7. **Register a web app** (Project settings) and copy the public config into the three `VITE_FIREBASE_*` GitHub Environment variables. The default auth domain is `knowserve-m0-spike.firebaseapp.com`; confirm with the frontend docs which value `VITE_FIREBASE_AUTH_DOMAIN` should hold.
8. **Admin account** (D4): create the one Admin user (Authentication, Users) and note its uid. Provisioning is the separate step above.
9. **Pre-verified smoke account:** create one Email/Password test user with a verified email for the deployed smoke (M1-AC12). Its credentials are a test secret for the smoke and are not committed.

**Evidence export (M1-AC02, the real-Firebase smoke, M1-08).** The console cannot export everything, so collect the following, dated, with nothing secret visible beyond the public web config:
- A screenshot of Sign-in method (Email/Password, Google and Anonymous enabled; passwordless link off).
- Screenshots of Settings: email enumeration protection on, one account per email, and the password policy (minimum 8, no composition rules, `Require`), or the report that it could not be enforced and why.
- A screenshot of Authorized domains.
- Screenshots of the two email templates showing the action URL.
- A screenshot of the registered web app config (public values only).
- If available, the project config read from the Identity Toolkit admin API: `GET https://identitytoolkit.googleapis.com/admin/v2/projects/knowserve-m0-spike/config` with the Owner's gcloud access token, saved as JSON (the response holds no secrets). UNVERIFIED: the field names, and whether the standard project returns the password policy. `firebase auth:export` exports users and is not wanted.
- The result of one real signup with verification and reset mail delivery, one Google sign-in, and Try Demo on the deployed site.

### Owner-only cloud actions for M1-07 (none has been run)
1. Neon: create or assign the DDL role and a DML-only runtime role, and fix ownership and grants (SQL above).
2. Secret Manager: add the `migration-database-url` value (direct URL, `neondb_owner`) and, after the cutover login test, a new `database-url` version (pooled `ks_runtime`). The Neon role itself already exists (`NOLOGIN`, no password).
3. Terraform: review `terraform plan`, then `terraform apply` (targeted for the new secret container first, full after the values exist). Add `firebase_project_id` to `terraform.tfvars`.
4. GitHub (settings, not code): environment variables `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`; keep `RUN_MIGRATIONS` unset or `true`; consider required reviewers on the environment; remove the obsolete `GCP_DATABASE_URL_SECRET_NAME` variable (no longer read).
5. Run the deploy workflow: `auth-check`, then `deploy` (this executes the migration job against the spike database for the first time).
6. Firebase Console setup and the evidence export (checklist above).
7. Create the Admin in the Firebase Console; set `enable_admin_seed_job = true`, apply, run the job with the uid and email, then set it back to `false` and apply.
8. QStash: confirm schedule availability and quotas, then create the schedule (`infra/qstash/README.md`).
9. Any billing, budget or quota change.

## Bootstrap (the USER does this once, outside Terraform)
1. Create the GCP project, link billing.
2. Create a GCS bucket for state (versioning on, uniform access, restricted IAM) and note its name.
3. Enable the APIs Terraform itself needs: `serviceusage.googleapis.com`, `cloudresourcemanager.googleapis.com`, `iam.googleapis.com` (Terraform enables the rest).
4. Provide an identity for the first apply with enough rights to create the above resources (user account via `gcloud auth application-default login`, or a short-lived impersonated account). Do not create JSON keys.
5. Create a Cloudflare API token scoped to Pages; export it as `CLOUDFLARE_API_TOKEN` in the shell, never in files.
6. Manual third-party setup (see below): Neon, Upstash QStash, Cloudflare R2, Firebase Authentication (M1, manual until planned).
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
- **Firebase Authentication**: manual in the Firebase console for M1; the checklist and the evidence list are under "M1 additions" above (see also `docs/milestones/M1/plan.md`). Resend is no longer planned (OPEN-24).
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
8. The WIF claim names (`repository_id`, `repository_owner_id`, `environment`, `workflow_ref`, `sub`) are taken from GitHub's documentation and are unverified until a real GitHub Actions run; a wrong claim fails closed (no deployer token). (Migrations no longer need the deployer to read a database secret: M1 moves them into the `knowserve-migrate` job, see "M1 additions". That job, its IAM and the `jobs update` and `--wait` permissions of `roles/run.developer` are unverified until the first real run.)
9. Public Cloud Run may be blocked by an organization policy (domain restricted sharing); then the design needs revisiting.
10. Neon and QStash have no authored provider resources; their Terraform coverage is for M0-09 to assess.

## First-apply findings (2026-10-31)
- Cloudflare rejected the Pages project with error 8000066 ("`fail_open` must be equal for production and preview"). `cloudflare.tf` now sets `fail_open = false` in both environments (fail closed).
- Cloud Run returns a service-level `scaling` block (`min 0`, `manual 0`) that the provider planned to remove on every run; both services now ignore that block (scaling is set only on the template: min 0, max 2).
- Each Cloud Run service answers on two hostnames: the hash form (`https://<service>-<hash>-ew.a.run.app`, shown as `status.url`) and the project-number form (`https://<service>-<project number>.<region>.run.app`). Both were verified to reach the service. The configuration uses the project-number form.
- `enable_spike_endpoints` (default false) sets `KS_ENABLE_SPIKE_ENDPOINTS` on the API: the public test routes `/v1/spike/cookie|echo|stream` (reachable through the Pages proxy; `stream` can hold a connection up to 600 s). `/v1/spike/echo` also returns the client IP the Pages Function forwarded (M0-AC11). Enable only briefly, then re-apply with it false. Changing it creates a new Cloud Run revision but does not change the image (image is in `ignore_changes`; roll images with `gcloud run deploy`).
- **Pages secret and Terraform:** `PROXY_SHARED_SECRET` is set with `wrangler pages secret put`; Cloudflare then reports it back as a production env var (`secret_text`, empty value), which the provider planned to strip. `cloudflare_pages_project.app` therefore has `ignore_changes` on `deployment_configs.production.env_vars["PROXY_SHARED_SECRET"]`. Never apply a plan that shows that variable being changed or removed; if the ignore does not take effect, widen it to the whole production `env_vars` and manage `API_ORIGIN` by hand.
- `github_environment` (default `production`; the spike sets `spike`) is the GitHub Environment name the Workload Identity condition and the single impersonation subject trust. Changing it updates the provider in place and replaces the `deployer_wif` binding (preview: 1 add, 1 change, 1 destroy); apply it before the first deploy that uses the new name.
