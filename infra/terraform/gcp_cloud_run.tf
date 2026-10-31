locals {
  api_secret_env    = ["database-url", "qstash-token", "proxy-shared-secret"]
  worker_secret_env = ["database-url", "qstash-token", "qstash-current-signing-key", "qstash-next-signing-key"]

  # Secret id -> environment variable name (names fixed by docs/contracts/config-and-deploy.md).
  secret_env_names = {
    "database-url"               = "KS_DATABASE_URL"
    "qstash-token"               = "KS_QSTASH_TOKEN"
    "qstash-current-signing-key" = "KS_QSTASH_CURRENT_SIGNING_KEY"
    "qstash-next-signing-key"    = "KS_QSTASH_NEXT_SIGNING_KEY"
    "proxy-shared-secret"        = "KS_PROXY_SHARED_SECRET"
  }
}

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = "knowserve-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email

    # Cost cap: scale to zero, at most 2 instances.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

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
        value = var.worker_public_url
      }

      # Spike operator job surface: plain non-secret settings, only when enabled.
      dynamic "env" {
        for_each = var.enable_spike_job_ops ? {
          KS_ENABLE_SPIKE_JOB_OPS  = "true"
          KS_SPIKE_OPERATOR_EMAILS = google_service_account.spike_operator[0].email
          KS_SPIKE_OIDC_AUDIENCE   = var.api_origin
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.enable_spike_failure_hooks ? { KS_ENABLE_SPIKE_FAILURE_HOOKS = "true" } : {}
        content {
          name  = env.key
          value = env.value
        }
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

    # Cost cap: scale to zero, at most 2 instances.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

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
        name  = "KS_WORKER_PUBLIC_URL"
        value = var.worker_public_url
      }

      # The Worker registers the test-only always_fail handler only for the isolated spike.
      dynamic "env" {
        for_each = var.enable_spike_failure_hooks ? { KS_ENABLE_SPIKE_FAILURE_HOOKS = "true" } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.enable_recovery_scheduler ? {
          KS_ENABLE_RECOVERY_DISPATCHER      = "true"
          KS_DISPATCHER_OIDC_AUDIENCE        = var.dispatcher_oidc_audience
          KS_DISPATCHER_OIDC_SERVICE_ACCOUNT = google_service_account.scheduler[0].email
        } : {}
        content {
          name  = env.key
          value = env.value
        }
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
# QStash signature for the Worker, plus Scheduler OIDC only if the optional recovery dispatcher is enabled, see docs/contracts/jobs-outbox.md).
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

# Optional scheduled outbox recovery (disabled by default; M0 has no Scheduler job).
# Recovery in M0 is an admin-initiated manual retry. Enable only after a user decision.
resource "google_cloud_scheduler_job" "outbox_dispatch" {
  count     = var.enable_recovery_scheduler ? 1 : 0
  project   = var.project_id
  region    = var.region
  name      = "knowserve-outbox-dispatch"
  schedule  = var.scheduler_cron
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker.uri}/internal/outbox/dispatch"

    oidc_token {
      service_account_email = google_service_account.scheduler[0].email
      audience              = var.dispatcher_oidc_audience
    }
  }

  depends_on = [google_project_service.apis]
}
