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
  secret_ids = ["database-url", "qstash-token", "qstash-current-signing-key", "qstash-next-signing-key", "proxy-shared-secret"]

  # Which runtime account may read which secret.
  secret_readers = {
    "database-url"               = { api = true, worker = true }
    "qstash-token"               = { api = true, worker = true }
    "qstash-current-signing-key" = { api = false, worker = true }
    "qstash-next-signing-key"    = { api = false, worker = true }
    "proxy-shared-secret"        = { api = true, worker = false } # docs/contracts/proxy.md
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
