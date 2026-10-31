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

variable "github_repository" {
  type        = string
  description = "GitHub repository (owner/name) trusted by Workload Identity Federation."
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
