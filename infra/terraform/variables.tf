############ Google Cloud ############

variable "project_id" {
  type        = string
  description = "GCP project id created by the user during bootstrap."
}

variable "region" {
  type        = string
  description = "Region for Cloud Run and Artifact Registry (approved: europe-west1). No default on purpose."
}

variable "api_image" {
  type        = string
  description = "API container image. Only the bootstrap value matters: deploys roll revisions outside Terraform (image is in ignore_changes)."
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "worker_image" {
  type        = string
  description = "Worker container image; same bootstrap/ignore_changes semantics as api_image."
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "log_level" {
  type        = string
  description = "Value of KS_LOG_LEVEL for both services."
  default     = "INFO"
}

variable "api_allowed_origins" {
  type        = list(string)
  description = "Browser origins for KS_API_ALLOWED_ORIGINS. Must be exactly the single https://<project>.pages.dev app origin (docs/contracts/proxy.md): the API sees that Origin because the Pages Function forwards it. Wildcards and non-https origins are rejected."

  validation {
    condition     = length(var.api_allowed_origins) == 1 && alltrue([for o in var.api_allowed_origins : startswith(o, "https://") && !strcontains(o, "*")])
    error_message = "api_allowed_origins must contain exactly one https:// origin and no wildcard."
  }
}

variable "qstash_url" {
  type        = string
  description = "Base URL of the QStash publish API for the chosen Upstash region, copied from the Upstash console (KS_QSTASH_URL). Not a secret."
}

variable "worker_public_url" {
  type        = string
  description = "The Worker's public https URL (KS_WORKER_PUBLIC_URL). Required: QStash deliveries are verified against it. Supplied explicitly because a Cloud Run service cannot reference its own URL; after the first apply, read the real URL from the console or the 'worker_url' output and set this."

  validation {
    condition     = startswith(var.worker_public_url, "https://")
    error_message = "worker_public_url must be an https:// URL."
  }
}

variable "enable_recovery_scheduler" {
  type        = bool
  description = "Optional scheduled outbox recovery (Cloud Scheduler job, ks-scheduler service account, Worker dispatcher env). Default false: M0 recovery is an admin-initiated manual retry. Enabling requires a user decision."
  default     = false
}

variable "scheduler_cron" {
  type        = string
  description = "Cron expression for the optional outbox dispatch Scheduler job. Required only when enable_recovery_scheduler is true; no cadence is recommended."
  default     = null

  validation {
    condition     = !var.enable_recovery_scheduler || var.scheduler_cron != null
    error_message = "scheduler_cron is required when enable_recovery_scheduler is true."
  }
}

variable "scheduler_time_zone" {
  type        = string
  description = "Time zone for the optional Scheduler cron. Required only when enable_recovery_scheduler is true."
  default     = null

  validation {
    condition     = !var.enable_recovery_scheduler || var.scheduler_time_zone != null
    error_message = "scheduler_time_zone is required when enable_recovery_scheduler is true."
  }
}

variable "dispatcher_oidc_audience" {
  type        = string
  description = "Audience of the Scheduler OIDC token and KS_DISPATCHER_OIDC_AUDIENCE. Required only when enable_recovery_scheduler is true (the Worker public https URL)."
  default     = null

  validation {
    condition     = !var.enable_recovery_scheduler || (var.dispatcher_oidc_audience != null && startswith(coalesce(var.dispatcher_oidc_audience, "x"), "https://"))
    error_message = "dispatcher_oidc_audience must be an https:// URL when enable_recovery_scheduler is true."
  }
}

variable "enable_spike_endpoints" {
  type        = bool
  description = "Mount the public spike test endpoints /v1/spike/{cookie,echo,stream} (KS_ENABLE_SPIKE_ENDPOINTS). They are reachable through the Pages proxy and /stream can hold a connection for up to 10 minutes, so enable only briefly for the M0 spike checks."
  default     = false
}

variable "enable_spike_job_ops" {
  type        = bool
  description = "Mount the spike-only operator job routes (/internal/spike/jobs) on the API (KS_ENABLE_SPIKE_JOB_OPS). Default false. Not public, not application auth (M1) or admin RBAC (M3)."
  default     = false
}

variable "enable_spike_failure_hooks" {
  type        = bool
  description = "Allow test-only failure hooks (skip_publish, always_fail job type) via KS_ENABLE_SPIKE_FAILURE_HOOKS. Requires enable_spike_job_ops. Only for the isolated spike environment."
  default     = false

  validation {
    condition     = !var.enable_spike_failure_hooks || var.enable_spike_job_ops
    error_message = "enable_spike_failure_hooks requires enable_spike_job_ops."
  }
}

variable "spike_token_creator_emails" {
  type        = list(string)
  description = "Google accounts (plain emails) allowed to impersonate the spike operator service account to mint ID tokens for the job routes. Supply in the git-ignored terraform.tfvars; do not commit real addresses. The API allow-list (KS_SPIKE_OPERATOR_EMAILS) is the operator service account itself, never these human accounts."
  default     = []

  validation {
    condition     = !var.enable_spike_job_ops || length(var.spike_token_creator_emails) > 0
    error_message = "spike_token_creator_emails must be non-empty when enable_spike_job_ops is true."
  }
}

variable "firebase_project_id" {
  type        = string
  description = "Firebase project id (KS_FIREBASE_PROJECT_ID, the audience of verified ID tokens). Not a secret. The permanent production project is knowserve-m0-spike (OPEN-26 D3). Required by the API when KS_ENV=production."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.firebase_project_id))
    error_message = "firebase_project_id must look like a Firebase/GCP project id (6-30 chars, lower-case letters, digits, dashes)."
  }
}

variable "r2_endpoint" {
  type        = string
  description = "S3 endpoint of the Cloudflare R2 account for the document object store (KS_R2_ENDPOINT), https://<account_id>.r2.cloudflarestorage.com. No bucket in the URL, no trailing slash. Not a secret."

  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.r2\\.cloudflarestorage\\.com$", var.r2_endpoint))
    error_message = "r2_endpoint must look like https://<account_id>.r2.cloudflarestorage.com (no path, no trailing slash)."
  }
}

variable "r2_bucket" {
  type        = string
  description = "Name of the private R2 bucket created by hand (KS_R2_BUCKET, Q10). Not a secret."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.r2_bucket))
    error_message = "r2_bucket must be a valid R2 bucket name (3-63 chars, lower-case letters, digits, dashes)."
  }
}

variable "api_m1_settings" {
  type        = map(string)
  description = "Optional non-secret M1 settings for the API, as KEY = \"value\". Leave empty to keep the application defaults (docs/contracts/config-and-deploy.md). Only the keys in the allow-list are accepted; secrets can never be set here."
  default     = {}

  validation {
    condition = alltrue([for k in keys(var.api_m1_settings) : contains([
      "KS_SESSION_COOKIE_NAME", "KS_SESSION_TTL_SECONDS", "KS_AUTH_MAX_AGE_SECONDS",
      "KS_DEMO_RETENTION_SECONDS", "KS_DEMO_START_LIMIT", "KS_DEMO_START_WINDOW_SECONDS",
      "KS_QUOTA_DEMO_DAILY", "KS_QUOTA_REGISTERED_DAILY", "KS_QUOTA_ADMIN_DAILY",
      "KS_AI_GLOBAL_DAILY_QUOTA", "KS_AI_KILL_SWITCH",
    ], k)])
    error_message = "api_m1_settings accepts only the documented non-secret M1 keys (see variables.tf)."
  }
}

variable "worker_m1_settings" {
  type        = map(string)
  description = "Optional non-secret M1 settings for the Worker (Demo cleanup). Leave empty to keep the application defaults."
  default     = {}

  validation {
    condition     = alltrue([for k in keys(var.worker_m1_settings) : contains(["KS_DEMO_RETENTION_SECONDS", "KS_DEMO_CLEANUP_BATCH_SIZE"], k)])
    error_message = "worker_m1_settings accepts only KS_DEMO_RETENTION_SECONDS and KS_DEMO_CLEANUP_BATCH_SIZE."
  }
}

variable "enable_admin_seed_job" {
  type        = bool
  description = "Create the Cloud Run job knowserve-admin-seed that runs the idempotent Admin provisioning command (python -m knowserve_api.admin_seed) with the runtime (DML-only) service account and the `database-url` secret. Default false: enable only for the Owner-run provisioning (D4), then set back to false and apply. KS_ADMIN_FIREBASE_UID / KS_ADMIN_EMAIL are never stored in Terraform; the Owner passes them when executing the job."
  default     = false
}

variable "github_repository" {
  type        = string
  description = "GitHub repository (owner/name) trusted by Workload Identity Federation."

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must look like OWNER/NAME."
  }
}

variable "github_environment" {
  type        = string
  description = "Name of the GitHub Environment whose jobs may authenticate to this project (WIF condition and subject). Use `spike` for the M0 spike project and `production` for the future production project, so each GCP project trusts exactly one environment. Changing it updates the provider condition and replaces the impersonation binding; apply it before the first deploy that uses the new name."
  default     = "production"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,38}$", var.github_environment))
    error_message = "github_environment must be lower-case letters, digits and dashes (it is part of the OIDC subject)."
  }
}

variable "github_repository_id" {
  type        = string
  description = "Immutable numeric GitHub repository ID (not secret): `gh api repos/OWNER/NAME --jq .id`. Required by the WIF condition so a renamed or recreated repo with the same name cannot deploy."

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a number."
  }
}

variable "github_repository_owner_id" {
  type        = string
  description = "Immutable numeric GitHub owner (user or organization) ID (not secret): `gh api repos/OWNER/NAME --jq .owner.id`."

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a number."
  }
}

############ Cloudflare ############

variable "cloudflare_account_id" {
  type        = string
  description = "Cloudflare account id."
}

variable "pages_project_name" {
  type        = string
  description = "Cloudflare Pages project name."
}

variable "pages_production_branch" {
  type        = string
  description = "Production branch name recorded on the Pages project."
}

variable "api_origin" {
  type        = string
  description = "Cloud Run API URL (https, no trailing slash) injected as the plain Pages variable API_ORIGIN for the production deployment. Known only after the first apply (see output api_url): apply once, then set it and apply again."

  validation {
    condition     = startswith(var.api_origin, "https://") && !endswith(var.api_origin, "/")
    error_message = "api_origin must be an https:// URL without a trailing slash."
  }
}
