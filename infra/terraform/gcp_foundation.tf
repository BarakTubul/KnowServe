locals {
  # APIs Terraform enables. The first ones needed to START Terraform are enabled manually (README).
  required_apis = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
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
  project      = var.project_id
  account_id   = "ks-scheduler"
  display_name = "KnowServe Cloud Scheduler OIDC caller"
  depends_on   = [google_project_service.apis]
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
