locals {
  # APIs Terraform enables. The first ones needed to START Terraform are enabled manually (README).
  required_apis = concat([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    ],
    # Optional scheduled recovery only (STACK-23: disabled by default).
  var.enable_recovery_scheduler ? ["cloudscheduler.googleapis.com"] : [])
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "knowserve"
  format        = "DOCKER"
  description   = "KnowServe API and Worker images"

  depends_on = [google_project_service.apis]
}

# ---- Service accounts ----

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "ks-api-runtime"
  display_name = "KnowServe API runtime"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "worker" {
  project      = var.project_id
  account_id   = "ks-worker-runtime"
  display_name = "KnowServe Worker runtime"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "ks-github-deployer"
  display_name = "KnowServe GitHub deployer (WIF)"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "scheduler" {
  count        = var.enable_recovery_scheduler ? 1 : 0
  project      = var.project_id
  account_id   = "ks-scheduler"
  display_name = "KnowServe Cloud Scheduler OIDC caller"
  depends_on   = [google_project_service.apis]
}

# Spike operator identity (option B of the audience decision). A personal Google account cannot
# mint an ID token with a custom audience, but it can impersonate this service account:
#   gcloud auth print-identity-token --impersonate-service-account=<email> --audiences=<api url> --include-email
# The service account holds NO roles; it only exists so the API can allow-list its email. Only the
# listed human accounts may impersonate it. Created only for the isolated spike.
resource "google_service_account" "spike_operator" {
  count        = var.enable_spike_job_ops ? 1 : 0
  project      = var.project_id
  account_id   = "ks-spike-operator"
  display_name = "KnowServe spike operator (ID tokens for /internal/spike/jobs)"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account_iam_member" "spike_operator_id_token_creator" {
  for_each           = var.enable_spike_job_ops ? toset(var.spike_token_creator_emails) : toset([])
  service_account_id = google_service_account.spike_operator[0].name
  role               = "roles/iam.serviceAccountOpenIdTokenCreator"
  member             = "user:${each.value}"
}

# Runtime accounts get no project-level roles; Cloud Run writes logs through the platform agent.

# ---- Secret containers (NO versions: values are entered by the user, never by Terraform) ----

locals {
  # `migration-database-url` (M1, OPEN-26 D2) holds the DDL-role connection string used only by the
  # migration job. It has no entry in secret_readers on purpose: the API, the Worker and the deployer
  # never read it. Its single accessor binding is in gcp_migration_job.tf.
  #
  # M3 (OPEN-31 D3, D6): `r2-worker-access-key-id` and `r2-worker-secret-access-key` hold the
  # Worker's READ-ONLY R2 token; `openai-api-key` holds the OpenAI key of the dedicated project.
  # They are separate containers because the Worker reads them as the same KS_R2_* names the API
  # uses for its read/write/delete token (see secret_env_names in gcp_cloud_run.tf).
  #
  # NEVER remove an id from this list (and never revert a commit that adds one) once its container
  # holds a version: the plan would destroy the container and every version in it. R2 tokens
  # cannot be read back from Cloudflare, so a destroyed token has to be created again. To roll
  # back, remove only the service references (worker_secret_env / api_secret_env) and keep the
  # id here. The shared for_each has no prevent_destroy on purpose.
  secret_ids = [
    "database-url", "migration-database-url", "qstash-token", "qstash-current-signing-key",
    "qstash-next-signing-key", "proxy-shared-secret", "r2-access-key-id", "r2-secret-access-key",
    "ip-hash-pepper", "r2-worker-access-key-id", "r2-worker-secret-access-key", "openai-api-key",
  ]

  # Which runtime account may read which secret.
  secret_readers = {
    "database-url"               = { api = true, worker = true }
    "qstash-token"               = { api = true, worker = true }
    "qstash-current-signing-key" = { api = false, worker = true }
    "qstash-next-signing-key"    = { api = false, worker = true }
    "proxy-shared-secret"        = { api = true, worker = false } # docs/contracts/proxy.md
    # M2: R2 credentials for the document object store and the pepper for the keyed hash of the
    # client address in rate-limit keys (SEC-18). API only. From M3 the API's token must also be
    # able to delete (D6); the Worker never reads these two, so it holds no write credential.
    "r2-access-key-id"     = { api = true, worker = false }
    "r2-secret-access-key" = { api = true, worker = false }
    "ip-hash-pepper"       = { api = true, worker = false }
    # M3: the Worker's own read-only R2 token and the OpenAI key. Worker only: the API neither
    # reads objects as the Worker does nor calls OpenAI (docs/contracts/config-and-deploy.md).
    "r2-worker-access-key-id"     = { api = false, worker = true }
    "r2-worker-secret-access-key" = { api = false, worker = true }
    "openai-api-key"              = { api = false, worker = true }
  }
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(local.secret_ids)
  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "api_access" {
  for_each  = { for k, v in local.secret_readers : k => v if v.api }
  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_access" {
  for_each  = { for k, v in local.secret_readers : k => v if v.worker }
  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}
