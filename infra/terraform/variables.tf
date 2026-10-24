############ Google Cloud ############

variable "project_id" {
  type        = string
  description = "GCP project id created by the user during bootstrap."
}

variable "region" {
  type        = string
  description = "Region for Cloud Run, Artifact Registry and Cloud Scheduler. Choice is an open assumption (see README); no default on purpose."
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
  description = "Explicit browser origins for KS_API_ALLOWED_ORIGINS (e.g. the Pages and custom app origins)."
}

variable "qstash_url" {
  type        = string
  description = "Base URL of the QStash publish API for the chosen Upstash region, copied from the Upstash console (KS_QSTASH_URL). Not a secret."
}

variable "dispatcher_oidc_audience" {
  type        = string
  description = "Audience of the Scheduler OIDC token and of KS_DISPATCHER_OIDC_AUDIENCE. Required: the Worker refuses to start in production without it. Use the Worker's public https URL (a service cannot reference its own URL, so this is supplied explicitly)."

  validation {
    condition     = startswith(var.dispatcher_oidc_audience, "https://")
    error_message = "dispatcher_oidc_audience must be an https:// URL (the Worker's public URL)."
  }
}

variable "worker_public_url" {
  type        = string
  description = "The Worker's public https URL (KS_WORKER_PUBLIC_URL). Required: QStash deliveries are verified against it. Supplied explicitly because a Cloud Run service cannot reference its own URL; after the first apply, read the real URL from the console or the 'worker_url' output and set this."

  validation {
    condition     = startswith(var.worker_public_url, "https://")
    error_message = "worker_public_url must be an https:// URL."
  }
}

variable "scheduler_cron" {
  type        = string
  description = "Cron expression for the outbox dispatch Scheduler job. No cadence is recommended here; choose after the M0 spike."
}

variable "scheduler_time_zone" {
  type        = string
  description = "Time zone for the Scheduler cron."
  default     = "Etc/UTC"
}

variable "api_custom_domain" {
  type        = string
  description = "Host to map to the API Cloud Run service (e.g. api.example.com). Empty disables the mapping."
  default     = ""
}

variable "github_repository" {
  type        = string
  description = "GitHub repository (owner/name) trusted by Workload Identity Federation."
}

variable "billing_account_id" {
  type        = string
  description = "Billing account id (XXXXXX-XXXXXX-XXXXXX) for the budget."
  sensitive   = true
}

variable "budget_amount_units" {
  type        = number
  description = "Budget amount in whole units of budget_currency_code. No default: the user decides."
}

variable "budget_currency_code" {
  type        = string
  description = "Currency code of the billing account (e.g. as shown in the billing console)."
}

variable "budget_threshold_percents" {
  type        = list(number)
  description = "Fractions of the budget (0.5 = 50%) at which alerts fire."
}

variable "budget_notification_channel_ids" {
  type        = list(string)
  description = "Optional Cloud Monitoring notification channel resource names for budget alerts. Empty = default billing-admin email only."
  default     = []
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

variable "app_custom_domain" {
  type        = string
  description = "Host for the frontend on Pages (e.g. app.example.com). Empty disables the custom domain."
  default     = ""
}
