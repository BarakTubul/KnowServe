# Database migrations run in a dedicated Cloud Run job (M1, OPEN-26 D2, INFRA-07, M1-AC11).
#
#   * The job runs the API image: `alembic -c packages/backend_core/alembic.ini upgrade head`
#     (the Dockerfile ships alembic in the venv, the ini and the migrations under /app).
#   * It runs as its OWN service account (ks-migrate-runtime) and reads its OWN secret
#     `migration-database-url` (the Neon DDL role, direct host). Terraform creates the secret
#     container only (gcp_foundation.tf); the role and the value are created by the Owner.
#   * The API and Worker keep reading `database-url` (the DML-limited role). They are not bound to
#     the migration secret, and neither is the deployer.
#   * The deployer may update the job's image and execute it, and act as the migration service
#     account (required to update a job). It gets no secretAccessor anywhere: the deploy workflow
#     never sees a database credential.
#   * The image is rolled by the deploy workflow, as for the services (ignore_changes on image).
#
# Nothing in this file has been planned or applied.

resource "google_service_account" "migrate" {
  project      = var.project_id
  account_id   = "ks-migrate-runtime"
  display_name = "KnowServe migration job runtime"
  depends_on   = [google_project_service.apis]
}

# The only binding on the migration secret.
resource "google_secret_manager_secret_iam_member" "migrate_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets["migration-database-url"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrate.email}"
}

resource "google_cloud_run_v2_job" "migrate" {
  project  = var.project_id
  name     = "knowserve-migrate"
  location = var.region

  # Provider 6.x may default this to true (M0 spike report F6); an intentional replace must work.
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1

    template {
      service_account = google_service_account.migrate.email
      # One attempt: a failed migration must stop the deploy, not be retried silently.
      max_retries = 0
      timeout     = "600s"

      containers {
        # Bootstrap image only; the deploy workflow updates the job to the deployed API digest.
        image   = var.api_image
        command = ["alembic"]
        args    = ["-c", "packages/backend_core/alembic.ini", "upgrade", "head"]

        env {
          name  = "KS_ENV"
          value = "production"
        }
        env {
          name  = "KS_LOG_LEVEL"
          value = var.log_level
        }
        env {
          name = "KS_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["migration-database-url"].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.migrate_access,
  ]
}

# Optional second job for the Owner-run Admin provisioning (D4). Same image as the migration job but
# the RUNTIME (DML-only) identity: the API service account and the `database-url` secret. Creating the
# single Admin row needs INSERT/UPDATE on existing tables, never DDL (Owner decision, 2026-11-06). It is created only while
# `enable_admin_seed_job` is true and is never executed by CI (the deployer has no grants on it).
# KS_ADMIN_FIREBASE_UID and KS_ADMIN_EMAIL are passed by the Owner at execution time
# (`--update-env-vars`), so they never enter Terraform state. No password is involved.
resource "google_cloud_run_v2_job" "admin_seed" {
  count    = var.enable_admin_seed_job ? 1 : 0
  project  = var.project_id
  name     = "knowserve-admin-seed"
  location = var.region

  # Removing the job (enable_admin_seed_job=false) must actually delete it; confirm in terraform plan.
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1

    template {
      service_account = google_service_account.api.email
      max_retries     = 0
      timeout         = "300s"

      containers {
        # Bootstrap image; the Owner updates it to the current API digest before executing.
        image   = var.api_image
        command = ["python"]
        args    = ["-m", "knowserve_api.admin_seed"]

        env {
          name  = "KS_ENV"
          value = "production"
        }
        env {
          name  = "KS_LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "KS_FIREBASE_PROJECT_ID"
          value = var.firebase_project_id
        }
        env {
          name = "KS_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["database-url"].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  # `env` is NOT ignored, so a change to the database secret reference shows up as drift.
  # KS_ADMIN_* are passed per execution (`--update-env-vars`), not stored on the job.
  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
  ]
}

# ---- Deployer grants for the migration job (least privilege; no secretAccessor) ----

# Update the job image and execute it (and read executions for `--wait`). roles/run.developer on
# THIS job only, the same role the deployer has on each service. It also allows deleting the job;
# see infra/terraform/README.md ("Deployer grants for the migration job") for the trade-off.
resource "google_cloud_run_v2_job_iam_member" "deployer_migrate" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migrate.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# Updating a job that runs as the migration account requires acting as that account.
resource "google_service_account_iam_member" "deployer_acts_as_migrate" {
  service_account_id = google_service_account.migrate.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
