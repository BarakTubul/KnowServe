# M0 spike bootstrap plan (GCP + Cloudflare)

**Status:** plan only. Prepared from the existing Terraform (`infra/terraform`) by local reading and validation. Nothing here has been run. Every command below is executed by the **user** in their own terminal unless stated otherwise. Requirements: INFRA-02/03/06/07/11, COST-01/04, M0-AC02/04/08/09/11/15.

Project `knowserve-m0-spike` (Free Trial, billing linked, Cloud Run spend cap and all-services budget alert already exist and stay user-managed; Terraform manages no budget). Region `europe-west1`; Pages project `knowserve-m0-spike` (`https://knowserve-m0-spike.pages.dev`; the first apply must confirm the real host equals `api_allowed_origins[0]`). No Cloud Scheduler in M0. Neon is `eu-central-1` (Frankfurt) and QStash is EU (`eu-central-1`).

## 0. Hazards found while reading
| # | Finding | Handling |
|---|---|---|
| H1 | The local `gcloud` default project is **`tradetogod`**, a different project. | Every `gcloud` command uses `--project=knowserve-m0-spike`. Never rely on the default; do not run `gcloud config set project` for this work. |
| H2 | Application Default Credentials already exist on this machine. Any process the agent starts (including Terraform) could use them. | The user runs `terraform plan/apply` and `gcloud` writes themselves. The agent only reads pasted plan text. See section 4. |
| H3 | **First apply would fail the startup probe.** Cloud Run services use a `/health/live` probe, but the default bootstrap image (`us-docker.pkg.dev/cloudrun/container/hello`) does not serve it. | Two-phase apply (section 3): create the registry first, push the real images, then apply with `api_image` / `worker_image` set. |
| H4 | **No `max_instance_count`.** Cloud Run defaults to 100 instances, so a flood of direct requests could scale cost. | RESOLVED in Terraform: `scaling { min 0, max 2 }` on both services. |
| H5 | Terraform's `google_billing_budget` duplicated the budget you already created and needed billing-account rights. | RESOLVED: the resource, its variables and the Billing Budgets API were removed; budgets stay manual. |
| H6 | Chicken-and-egg URLs: `worker_public_url` and `api_origin` are required before the services exist (`dispatcher_oidc_audience` only if the optional scheduler is enabled). | Cloud Run's deterministic URL is `https://<service>-<PROJECT_NUMBER>.<region>.run.app`. The user reads the project number once and fills the tfvars. The `terraform output` URLs are compared afterwards. |
| H7 | Terraform is not installed on this machine. | User installs Terraform >= 1.6, or runs the `hashicorp/terraform` container with the ADC file mounted. |
| H8 | The deploy workflow cannot run yet: the repository is not pushed, WIF trusts only `main` + environment `production` + the `deploy.yml` workflow + immutable repository/owner IDs, and the deployer cannot read `database-url`. | For the spike, images are built and pushed by the user locally (section 3). The CI/WIF path is tested later after push approval. |

## 1. Manual (user) versus Terraform
| Item | Who | Notes |
|---|---|---|
| GCP project, billing link, budget alert, spend cap | user (done); budgets stay manual, not in Terraform | |
| Enable `serviceusage`, `cloudresourcemanager`, `iam` APIs | user | Terraform needs them before it can enable the rest |
| State bucket `gs://knowserve-m0-spike-tfstate` | user | versioning on, uniform access, public access prevention enforced, no public IAM; state is < 1 MB |
| Cloudflare API token (Account, Cloudflare Pages: Edit only) | user | exported as `CLOUDFLARE_API_TOKEN` in the shell only |
| Secret **values** (5) | user | `gcloud secrets versions add ... --data-file=-` |
| Pages secret `PROXY_SHARED_SECRET` | user | `wrangler pages secret put` |
| Local Docker image push | user | `gcloud auth configure-docker <region>-docker.pkg.dev` |
| GitHub repo, environment, branch protection, push | user, later | not needed for the first spike apply |
| Other required APIs (12 total, see below) | Terraform | `google_project_service` |
| Artifact Registry `knowserve`, 3 service accounts (+ `ks-scheduler` only if the optional scheduler is enabled), 5 secret containers, accessor bindings | Terraform | |
| Cloud Run `knowserve-api` / `knowserve-worker`, public invoker | Terraform | |
| Workload Identity pool/provider, deployer SA + roles | Terraform | idle until GitHub push |
| Cloudflare Pages project + plain variable `API_ORIGIN` | Terraform | provider v5 behavior unverified |
| Neon, QStash | manual (done) | |
| R2, Resend | later milestones | |

**APIs Terraform enables:** `run`, `artifactregistry`, `secretmanager`, `iam`, `iamcredentials`, `sts`, `cloudresourcemanager`, `serviceusage`, `logging`, `monitoring` (`*.googleapis.com`); `cloudscheduler` only if `enable_recovery_scheduler` is true.

## 2. Identity and roles
- **Spike operator identity (B2 = option B, only when `enable_spike_job_ops`):** one role-less service account `ks-spike-operator` plus `roles/iam.serviceAccountOpenIdTokenCreator` on it for the Google accounts listed in `spike_token_creator_emails` (git-ignored tfvars). This adds 1 service account and 1 IAM binding to the resource inventory (38 becomes 40 when enabled); the API allow-list holds the service account email.
- **Applying identity:** the project creator already holds `roles/owner` on a Free Trial project. That is acceptable for a throwaway spike. The equivalent least-privilege set is `serviceusage.serviceUsageAdmin`, `run.admin`, `artifactregistry.admin`, `secretmanager.admin`, `iam.serviceAccountAdmin`, `iam.workloadIdentityPoolAdmin`, `iam.serviceAccountUser`, `storage.objectAdmin` on the state bucket (plus `cloudscheduler.admin` only if the optional scheduler is enabled). No billing-account role is needed.
- **Runtime accounts (created by Terraform):** `ks-api-runtime` and `ks-worker-runtime` get only `secretmanager.secretAccessor` on their own secrets (API: `database-url`, `qstash-token`, `proxy-shared-secret`; Worker: `database-url`, `qstash-token`, both signing keys). No project-level roles.
- **`ks-scheduler`:** created only when the optional scheduler is enabled; no roles of its own, used only as the OIDC caller.
- **`ks-github-deployer`:** `run.developer` per service, `artifactregistry.writer` on the repo, `serviceAccountUser` on the two runtime accounts, impersonable only through the single WIF subject `repo:BarakTubul/KnowServe:environment:production`; the provider also pins the numeric repository and owner IDs, `refs/heads/main` and the `deploy.yml` workflow path.
- **Public invoker (`allUsers`)** on both Cloud Run services is required by the design. If an organization policy blocks it, the apply fails and the design needs revisiting (a personal Free Trial project normally has no such policy).

## 3. Ordered steps (all user-run; each gate needs approval)
1. **Decisions** (below), then the agent prepares `terraform.tfvars` and `backend.hcl` as **uncommitted, git-ignored** files with no secrets.
2. Enable the three bootstrap APIs; create the state bucket (`--project=knowserve-m0-spike`).
3. `terraform init -backend-config=backend.hcl`, `fmt -check`, `validate`, `python check_no_secrets.py`.
4. **Phase 1 (image-first):** `terraform apply -target=google_project_service.apis -target=google_artifact_registry_repository.images -target=google_secret_manager_secret.secrets` plus the service accounts. Review the plan text with the agent first. No Cloud Run exists yet.
5. Enter secret values (never in tfvars, shell history or CI variables): `database-url` (the **pooled** Neon URL, runtime), `qstash-token`, both signing keys, and a freshly generated `proxy-shared-secret`.
6. Build and push the two images locally with an immutable tag; set `api_image` and `worker_image` to those tags.
7. **Phase 2:** full `terraform plan -out=tfplan`, agent reviews the text for secret values and unexpected changes, then `terraform apply tfplan`.
8. Compare `terraform output` URLs with the predicted ones; fix `api_origin` if different and re-apply.
9. Set the Pages secret with the same value as `proxy-shared-secret`; deploy the Pages site from `apps/frontend` with wrangler (`wrangler pages deploy`), as an explicit separate approval.
10. Run the spike checks (deployed SSE, cookie, client IP, direct 403, QStash delivery, manual-retry run through the spike operator surface (failure hooks only in this isolated environment; token minted by impersonating `ks-spike-operator` (B2 = option B); acceptance UNVERIFIED until this run), cold start, region latency, free-tier counters).

## 4. Credentials without exposing them to the agent
- The agent never receives tokens, passwords or secret values in chat, files or command lines.
- `CLOUDFLARE_API_TOKEN` is typed into the user's own shell session. `gcloud auth application-default login` is done by the user.
- Secret values are entered by the user with `gcloud secrets versions add <id> --data-file=-` (stdin or a protected temp file that is then deleted).
- Honest limit: while the agent can start processes on this machine it can technically reach files such as the ADC file. The control is procedural: the user runs every cloud-touching command, and the agent only reads non-secret output (plan text, `terraform output`, HTTP statuses). After the spike the user revokes ADC (`gcloud auth application-default revoke`) and deletes the Cloudflare token.
- Plan output must be checked for secrets before pasting (it should contain none; `check_no_secrets.py` and `secret_key_ref` keep values out of state).

## 5. Expected cost (documented values only; nothing measured)
| Service | Expected spike cost | Basis / caveat |
|---|---|---|
| Cloud Run (2 services, scale to zero, max 2 instances) | $0 within the free tier at spike traffic | request/vCPU-second free tier; confirm it applies in the chosen region |
| Artifact Registry | $0 up to 0.5 GB, then about $0.10/GB-month | two small images; add a cleanup policy |
| Secret Manager | $0 to cents | 6 free secret versions per billing account, then per version |
| Terraform state bucket | cents or $0 | tiny object |
| Cloud Logging | $0 at low volume | 50 GiB free per project |
| Cloudflare Pages + Functions | $0 | Free plan; Functions share 100,000 requests/day |
| Neon / QStash | $0 | already created on free plans; no Scheduler means no periodic Neon wake-ups or QStash recovery traffic |
| Free Trial credit | covers all of the above | the budget and spend cap are alerts/limits you control; budgets alone do not stop spend |

Target remains $0 to 5/month (COST-01). Everything above is from provider documentation, not from measurement. **Region (approved):** `europe-west1` (Belgium) is a Tier 1 Cloud Run region close to Neon and QStash in Frankfurt; `europe-west3` (Frankfurt) is closer but Tier 2 priced. The user should confirm free-tier applicability on Google's pricing page.

## 6. Cleanup
| Level | Action | Destructive? |
|---|---|---|
| Pause | Set Cloud Run services to 0 max instances (Scheduler `pause` only if the optional scheduler was enabled) | no |
| Revoke access | Remove the Cloudflare token; `gcloud auth application-default revoke`; delete Secret Manager versions | secrets only |
| Tear down | `terraform destroy` (Cloud Run, registry, SAs, secrets, WIF, Pages); then delete the state bucket | **yes, separate approval** |
| Full reset | Delete GCP project `knowserve-m0-spike` (30-day recovery), delete the Pages project, Neon project and Upstash database | **yes, separate approval** |
Never run any of these against `tradetogod`.

## 7. Blockers and decisions
1. **Migration permission (M1):** the deployer deliberately cannot read `database-url`, but `deploy.yml` reads it to migrate. Recommended: a dedicated Cloud Run **Job** `knowserve-migrate` run by a separate `ks-migrator` account, which alone can read a separate `migration-database-url` secret (direct Neon URL, owner-capable role); the deployer only gets `run.jobs.run` plus `serviceAccountUser` on that account. For the **spike this does not block**: Neon is already at revision `0001`, so the deploy workflow's migration step is not needed until the first schema change.
2. **Image-first order (H3)** is a procedure (section 3); **max instances (H4)** and the **budget removal (H5)** are done in Terraform.
3. **Project number** (user) for the predicted URLs; region is `europe-west1`.
4. **Scheduler cadence:** resolved, there is no Scheduler in M0 (optional, off).
5. **Pages project name** `knowserve-m0-spike` must be globally unique (it forms the `pages.dev` host and `api_allowed_origins[0]`); the first apply must confirm the real host.
6. **GitHub push, WIF, environment reviewers** remain blocked until you approve a push (H8).
7. Unverified: Cloudflare provider v5 `API_ORIGIN` behavior, `_routes.json` honored on deploy, SSE and cookies on the real edge (see `infra/terraform/README.md`).
