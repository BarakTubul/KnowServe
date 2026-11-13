# M3-09 infrastructure apply runbook

Status: prepared, not run. Nothing here has been planned or applied. Every step below needs the Owner's separate approval (plan section 12.3). The commands are for the Owner to run with their own credentials. No agent runs them.

Scope: the Terraform change in `infra/terraform/` for M3-09. Related: `docs/milestones/M3/plan.md` sections 12.3, 13 and 15, OPEN-31 (D2, D3, D6), `docs/contracts/config-and-deploy.md`, `docs/architecture/infrastructure.md` ("M3 credential and infrastructure ownership").

## What the change contains

| Item | Resource or setting | Reader |
|---|---|---|
| Worker read-only R2 token | secret containers `r2-worker-access-key-id`, `r2-worker-secret-access-key` | Worker only |
| OpenAI key | secret container `openai-api-key` | Worker only |
| API R2 token (read, write, delete) | existing containers `r2-access-key-id`, `r2-secret-access-key`, unchanged | API, and the seed job when enabled |
| Worker env | `KS_OBJECT_STORE=r2`, `KS_R2_ENDPOINT`, `KS_R2_BUCKET`, `KS_EMBEDDING_PROVIDER=openai`, plus the three secrets above under `KS_R2_ACCESS_KEY_ID`, `KS_R2_SECRET_ACCESS_KEY`, `KS_OPENAI_API_KEY` | Worker |
| API env | `KS_UPLOADS_ENABLED=true` | API |
| Optional non-secret keys | `api_m3_settings`, `worker_m3_settings`, empty by default (application defaults apply) | API, Worker |
| Worker sizing | `worker_memory`, `worker_cpu`, `worker_concurrency`, `worker_request_timeout_seconds`, all `null`: unmanaged, platform defaults stay | Worker |
| Alerts | log-based metrics, alert policies and an email channel, only with `enable_m3_alerts = true` (default false) | none |

Terraform creates no secret version. The API gets no binding on any of the three new containers. The Worker gets no binding on `r2-access-key-id` or `r2-secret-access-key`, so it has no write credential.

Sizing follows `docs/milestones/M3/measurements.md` (M3-00b, D2):

- Concurrency is 1 (`worker_concurrency`, default 1). The platform default of 80 would put up to 10 in-flight jobs on one 512 MiB instance. This only lowers a limit. With `max_instance_count` 2, at most two jobs run at once. A delivery that finds no free instance waits or is rejected by Cloud Run, and QStash retries it. A rejected delivery uses no processing attempt, so the cap of 4 is not spent.
- Memory stays 512 MiB, CPU stays unmanaged and the request timeout stays 300 s (all null).
- The application defaults are `KS_JOB_HANDLER_TIMEOUT_SECONDS=240` and `KS_PDF_EXTRACTION_TIMEOUT_SECONDS=120`. They need no Terraform value. The request timeout must stay above the handler timeout (300 > 240), and Terraform checks it.
- The measurements are local, on one fast machine and synthetic text PDFs, with no embedding, database or Worker baseline. The first real large-document run on Cloud Run (M3-AC23) must confirm memory and time. If it shows the instance near 512 MiB or a document above about 200 s, stop and bring numbers to the Owner before raising `worker_memory` or `worker_request_timeout_seconds` (a further plan and a separate approval).

## Preconditions

1. The Owner has reviewed the M3-09 diff and the independent review of secrets, IAM and Worker resources is done.
2. `terraform.tfvars` holds the values already used for M2 (`r2_endpoint`, `r2_bucket`, `worker_public_url`, and the rest). New variables all have defaults, so no new required value exists. Real addresses such as `alert_email` go only in the git-ignored `terraform.tfvars`.
3. The Owner has working remote state access (`backend.hcl`) and application default credentials. No JSON key is created.

## Step order (Owner only)

The order follows plan section 12.3. A Cloud Run revision that references a secret with no version cannot start, so the containers go first, the values second, the Cloud Run change last.

| Step | Action | Effect | Rollback |
|---|---|---|---|
| 1 | Verify OpenAI pricing and budget controls. Create the dedicated project with the 5 USD monthly budget and a key (12.3 item 1). No Google Cloud change yet. | An OpenAI project and key exist. No spend until the Worker embeds. | Delete the key in OpenAI. |
| 2 | In Cloudflare create the two bucket-scoped R2 tokens: API read, write and delete; Worker read only (12.3 item 2). | Two tokens exist. | Revoke them in Cloudflare. |
| 3 | Confirm the QStash plan limits against the expected ingestion message count (12.3 item 3). | Nothing changes. | None needed. |
| 4a | Targeted apply of the new secret containers and the Worker bindings (command below). Expected: 6 adds. | Three empty containers and three accessor bindings for `ks-worker-runtime`. Nothing reads them yet. | Leave them in place. Destroying a container deletes its versions, and an empty container costs almost nothing. |
| 4b | Enter the secret versions from stdin, never from a file in the repo and never in shell history: `r2-worker-access-key-id`, `r2-worker-secret-access-key`, `openai-api-key`. Enter a new version of `r2-access-key-id` and `r2-secret-access-key` only if the existing API token cannot delete. | Versions exist. Secret values never enter Terraform state. | `gcloud secrets versions disable <version> --secret <id>`; re-enable if needed. |
| 4c | Before the first deployed upload, check with a test object that the API token can delete and that the Worker token can read but not write or delete (D6). Cloudflare's documentation does not list delete per permission level. | Evidence for D6. | Replace the token and add a new version. |
| 5 | Full plan, review it against the expectation below, then full apply (command below). Expected: 2 changes, 0 adds, 0 destroys after step 4a. | New revisions of `knowserve-api` (one env added) and `knowserve-worker` (four plain envs and three secret references added, concurrency lowered to 1). The image does not change. | Return Cloud Run traffic to the previous revision first (immediate). To roll the Terraform back, remove only the service references (the entries in `worker_secret_env` and the new env blocks), keep `secret_ids` and `secret_readers`, plan and check that nothing is destroyed. Do not revert the whole commit: see the warning under Rollback. |
| 6 | Migration `0004` and the first `deploy.yml` run (`auth-check` first), the seed reindex, the real upload, and the D15 experiment each follow their own approval (12.3 items 5 to 9, section 13). | Not part of this change. | See plan section 15. |

Do not roll an M3 image to the Worker before step 5, and do not run step 5 before step 4b: the Worker revision would fail to start.

## Commands

Run from `infra/terraform` after `terraform init -backend-config=backend.hcl`.

Checks that need no cloud access (already run for this change):

```
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate
python check_no_secrets.py
```

Step 4a plan and apply:

```
terraform plan -out=tfplan \
  -target='google_secret_manager_secret.secrets' \
  -target='google_secret_manager_secret_iam_member.worker_access'
terraform show tfplan
terraform apply tfplan
```

Step 5 plan and apply:

```
terraform plan -out=tfplan
terraform show tfplan
terraform apply tfplan
```

`tfplan` is git-ignored because saved plans can contain resolved values. Delete it after the apply.

## Expected diff (flags at their defaults, sizing unset)

Step 4a (targeted), 6 to add, 0 to change, 0 to destroy:

- `google_secret_manager_secret.secrets["openai-api-key"]`
- `google_secret_manager_secret.secrets["r2-worker-access-key-id"]`
- `google_secret_manager_secret.secrets["r2-worker-secret-access-key"]`
- `google_secret_manager_secret_iam_member.worker_access["openai-api-key"]`
- `google_secret_manager_secret_iam_member.worker_access["r2-worker-access-key-id"]`
- `google_secret_manager_secret_iam_member.worker_access["r2-worker-secret-access-key"]`

The targeted plan may also list dependencies it needs (`google_project_service.apis`, the Worker service account). Those should show no change.

Step 5 (full), 0 to add, 2 to change, 0 to destroy:

- `google_cloud_run_v2_service.api`, in place: env `KS_UPLOADS_ENABLED = "true"` added.
- `google_cloud_run_v2_service.worker`, in place: env `KS_OBJECT_STORE`, `KS_R2_ENDPOINT`, `KS_R2_BUCKET`, `KS_EMBEDDING_PROVIDER` added, and `KS_R2_ACCESS_KEY_ID`, `KS_R2_SECRET_ACCESS_KEY`, `KS_OPENAI_API_KEY` added as secret references to the three new containers at version `latest`. Also `template.max_instance_request_concurrency` set to `1` (the current value is expected to read as the platform default of 80; UNVERIFIED until the first real plan).

Existing env blocks may appear reordered inside the same in-place update. That is cosmetic.

Run as one plan from the current state (skipping the targeted step) the totals are 6 to add, 2 to change, 0 to destroy. With `enable_m3_alerts = true` and `alert_email` set, add 5: two `google_logging_metric.app_errors`, one `google_monitoring_notification_channel.m3_email`, two `google_monitoring_alert_policy.app_errors`.

Stop and do not apply if the plan shows any of these:

- a destroy or replace of any existing resource (the migration job, the seed job, the services, the service accounts, any secret container, the WIF provider)
- any secret value, any `secret_data` or `google_secret_manager_secret_version`
- a change to `timeout` or `resources` on the Worker, or any `max_instance_request_concurrency` value other than 1 (memory, CPU and the request timeout are unset on purpose, so a change there would mean the provider reads the platform default as drift; UNVERIFIED until the first real plan)
- a binding of `ks-api-runtime` on a Worker secret, or of `ks-worker-runtime` on `r2-access-key-id` or `r2-secret-access-key`
- `KS_EMBEDDING_PROVIDER` with any value other than `openai`

After the apply, these read-only checks confirm the result without showing values:

```
gcloud secrets get-iam-policy r2-worker-access-key-id --project <project>
gcloud secrets get-iam-policy r2-worker-secret-access-key --project <project>
gcloud secrets get-iam-policy openai-api-key --project <project>
gcloud secrets get-iam-policy r2-access-key-id --project <project>
```

The first three list only `ks-worker-runtime`. The last lists `ks-api-runtime` and, only while the seed job exists, `ks-seed-runtime`.

If alerts are enabled, the email notification channel may need verification before it delivers: open it in Cloud Monitoring (Alerting, Notification channels) and confirm its status, and send a test notification. `alert_email` is an input of the channel, so it is stored in Terraform state even though the variable is marked sensitive. State is protected (restricted GCS bucket); use an address you are happy to have there, or leave the flag off and set the alert up by hand in the console.

## Cost

- Secret Manager: three more containers and up to five more versions. Pricing is unverified here; the amount is expected to be negligible.
- Cloud Run: concurrency 1 starts more instances under load (at most two) and adds no fixed cost; scale to zero stays. A later memory or CPU increase raises the price of every Worker second; it needs measured numbers from M3-AC23 and a separate approval (D2).
- Alerts: nothing is created with the flag off. With it on, the metrics, policies and channel follow Cloud Logging and Cloud Monitoring pricing, which is unverified for this project.
- OpenAI: capped by the 5 USD monthly project budget (D3). Whether OpenAI enforces the budget as a hard limit is checked in step 1. `KS_UPLOADS_ENABLED=false` and revoking the key are the stops (plan section 15).

## Rollback

- Warning: a plain `git revert` of the M3-09 commit removes the three new ids from `secret_ids`, and the next plan would destroy those containers and every version in them (the OpenAI key and both R2 tokens). R2 tokens cannot be read back from Cloudflare, so they would have to be created again. Secrets do not survive a plain revert.
- Terraform rollback, safe form: edit only the references. Remove the secret ids from `worker_secret_env`, remove the new env blocks and variables if wanted, and keep `secret_ids` and `secret_readers` unchanged. Run a plan and stop if it shows any `destroy` of a `google_secret_manager_secret` or a binding you did not intend. There is deliberately no `prevent_destroy` on the shared `for_each`, so the plan review is the guard.
- To retire a secret for good, disable its versions first, wait until M3 is accepted, and destroy the container by hand with the Owner's approval.
- Fast stop for spend: set `uploads_enabled = false` and apply, or revoke the OpenAI key. The daily and in-flight caps bound the damage before either.
- A bad Worker revision: return traffic to the previous revision with Cloud Run, as in `docs/architecture/rollback.md`.
- Disabled secret versions can be re-enabled. Do not delete versions until M3 is accepted.

## D15 note

The D15 experiment (plan 12.2) needs nothing from Terraform. It uses a tagged, no-traffic Worker revision created with gcloud, so no permanent flag, handler or fault-injection resource is added. One caution for the infra side: do not run `terraform apply` while the `d15` tag exists, so the apply cannot move traffic or replace the tagged revision. Remove the tag first.

## Open points for the lead

- Alert coverage: stuck outbox rows and stuck jobs are derived from database state and are not logged, so no log-based metric can alert on them. The Terraform alert covers application ERROR logs only. A distinct log event for permanent job failure (M3-00a) would let the filter be narrower.
- The seed reindex (M3-02c): if the seed command publishes to QStash from the `knowserve-document-seed` job, that job also needs the QStash token and the QStash and Worker URLs. This change does not add them. Tell the infra owner what the command needs.
- Sizing: waiting on `docs/milestones/M3/measurements.md`.
