# M2-05 / M2-00c: the Owner-run production document seed (Cloud Run job `knowserve-document-seed`).
#
# Smallest extension of gcp_migration_job.tf (same pattern as `knowserve-admin-seed`):
#   * ONE optional job, count = enable_document_seed_job (default false: nothing is created).
#   * ONE dedicated service account `ks-seed-runtime` (plan decision 16). The API account is not
#     reused because it can also read the QStash token, the proxy secret and the IP-hash pepper,
#     which the seed does not need.
#   * secretAccessor on exactly three secrets: `database-url` (the DML-only runtime role: the seed
#     only inserts into documents, document_revisions and document_department_access) and the two R2
#     credential secrets. It cannot read the migration (DDL) secret, QStash, proxy or the pepper.
#   * No deployer grants: CI never updates or executes this job, and deploy.yml does not mention
#     it. The Owner updates its image to the deployed API digest and executes it by hand.
#   * It runs `python -m knowserve_api.seed.documents` from the API image (the committed seed PDFs
#     ship in the wheel). The command refuses to run (exit 2, nothing written) until migration
#     0003 has created the document tables, and is idempotent: existing documents and objects are
#     never changed, a partial row is reported as `incomplete` (non-zero exit).
#
# The R2 containers, the pepper and the r2_endpoint / r2_bucket variables come from M2-00c
# (gcp_foundation.tf, variables.tf). Terraform creates containers only, never versions.
#
# Owner steps (each needs your explicit approval):
#   1. Merge PR #32 and run the deploy workflow: it runs migration 0003 and rolls the M2 API image.
#   2. Set enable_document_seed_job = true and apply (service account, three bindings, the job).
#   3. Update the job to the deployed API image digest, then run it once:
#        gcloud run jobs update knowserve-document-seed --image <API_IMAGE_DIGEST> --region <region>
#        gcloud run jobs execute knowserve-document-seed --region <region> --wait
#      Reruns are safe. The job prints counts and slugs only.
#   4. Set enable_document_seed_job back to false and apply (the job and its identity are removed).

variable "enable_document_seed_job" {
  type        = bool
  description = "Create the Cloud Run job knowserve-document-seed (python -m knowserve_api.seed.documents). Default false: enable only for the Owner-run production seed (M2-05), then set back to false and apply."
  default     = false
}

resource "google_service_account" "seed" {
  count        = var.enable_document_seed_job ? 1 : 0
  project      = var.project_id
  account_id   = "ks-seed-runtime"
  display_name = "KnowServe document seed job runtime"
  depends_on   = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "seed_access" {
  for_each  = var.enable_document_seed_job ? toset(["database-url", "r2-access-key-id", "r2-secret-access-key"]) : toset([])
  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.seed[0].email}"
}

resource "google_cloud_run_v2_job" "document_seed" {
  count    = var.enable_document_seed_job ? 1 : 0
  project  = var.project_id
  name     = "knowserve-document-seed"
  location = var.region

  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1

    template {
      service_account = google_service_account.seed[0].email
      max_retries     = 0
      timeout         = "300s"

      containers {
        image   = var.api_image
        command = ["python"]
        args    = ["-m", "knowserve_api.seed.documents"]

        env {
          name  = "KS_ENV"
          value = "production"
        }
        env {
          name  = "KS_LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "KS_OBJECT_STORE"
          value = "r2"
        }
        env {
          name  = "KS_R2_ENDPOINT"
          value = var.r2_endpoint
        }
        env {
          name  = "KS_R2_BUCKET"
          value = var.r2_bucket
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
        env {
          name = "KS_R2_ACCESS_KEY_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["r2-access-key-id"].secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "KS_R2_SECRET_ACCESS_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["r2-secret-access-key"].secret_id
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
    google_secret_manager_secret_iam_member.seed_access,
  ]
}
