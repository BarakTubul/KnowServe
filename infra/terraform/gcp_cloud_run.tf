locals {
  api_secret_env    = ["database-url", "qstash-token"]
  worker_secret_env = ["database-url", "qstash-token", "qstash-current-signing-key", "qstash-next-signing-key"]

  # Secret id -> environment variable name (names fixed by docs/contracts/config-and-deploy.md).
  secret_env_names = {
    "database-url"               = "KS_DATABASE_URL"
    "qstash-token"               = "KS_QSTASH_TOKEN"
    "qstash-current-signing-key" = "KS_QSTASH_CURRENT_SIGNING_KEY"
    "qstash-next-signing-key"    = "KS_QSTASH_NEXT_SIGNING_KEY"
  }
}

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = "knowserve-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email

    containers {
      # Bootstrap image only; the deploy workflow rolls real revisions.
      image = var.api_image

      env {
        name  = "KS_ENV"
        value = "production"
      }
      env {
        name  = "KS_LOG_LEVEL"
        value = var.log_level
      }
      env {
        name  = "KS_API_ALLOWED_ORIGINS"
        value = join(",", var.api_allowed_origins)
      }
      env {
        name  = "KS_ENABLE_SPIKE_ENDPOINTS"
        value = "false"
      }
      env {
        name  = "KS_QSTASH_URL"
        value = var.qstash_url
      }
      env {
        name  = "KS_WORKER_PUBLIC_URL"
        value = google_cloud_run_v2_service.worker.uri
      }

      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name = local.secret_env_names[env.value]
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health/live"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.api_access,
  ]
}

resource "google_cloud_run_v2_service" "worker" {
  project  = var.project_id
  name     = "knowserve-worker"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.worker.email

    containers {
      image = var.worker_image

      env {
        name  = "KS_ENV"
        value = "production"
      }
      env {
        name  = "KS_LOG_LEVEL"
        value = var.log_level
      }
      env {
        name  = "KS_QSTASH_URL"
        value = var.qstash_url
      }
      env {
        name  = "KS_DISPATCHER_OIDC_AUDIENCE"
        value = var.dispatcher_oidc_audience
      }
      env {
        name  = "KS_DISPATCHER_OIDC_SERVICE_ACCOUNT"
        value = google_service_account.scheduler.email
      }

      dynamic "env" {
        for_each = local.worker_secret_env
        content {
          name = local.secret_env_names[env.value]
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health/live"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.worker_access,
  ]
}

# Public invoker is REQUIRED for both services: browsers and QStash cannot present Google
# credentials. Each service authenticates its own routes (session cookie for the API;
# QStash signature and Scheduler OIDC for the Worker, see docs/contracts/jobs-outbox.md).
# Network reachability is not authentication.
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "worker_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Optional custom-domain mapping for the API host (INFRA-11). Disabled when the variable is empty.
resource "google_cloud_run_domain_mapping" "api" {
  count    = var.api_custom_domain == "" ? 0 : 1
  location = var.region
  name     = var.api_custom_domain

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.api.name
  }
}

# Outbox recovery: Scheduler calls the Worker with a Google OIDC token.
resource "google_cloud_scheduler_job" "outbox_dispatch" {
  project   = var.project_id
  region    = var.region
  name      = "knowserve-outbox-dispatch"
  schedule  = var.scheduler_cron
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker.uri}/internal/outbox/dispatch"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = var.dispatcher_oidc_audience != "" ? var.dispatcher_oidc_audience : google_cloud_run_v2_service.worker.uri
    }
  }

  depends_on = [google_project_service.apis]
}
