# M3-09 / MON-06 / M3-AC24: basic alerting on application ERROR logs. Everything here is behind
# `enable_m3_alerts` (default false): with the flag off, no resource exists and nothing is billed.
#
#   * Two log-based metrics count application log entries of severity ERROR or higher, one per
#     Cloud Run service. The Worker's permanent job failures and the embedding configuration
#     error (OPEN-31 D3: a missing, revoked or over-limit OpenAI key) are logged as errors.
#   * One alert policy per metric opens an incident when at least one such entry appears in a
#     5 minute window, and closes it after 30 quiet minutes.
#   * One email notification channel. The address comes from `alert_email` (git-ignored tfvars).
#
# Limits, stated so nobody assumes more coverage than exists:
#   * Only stdout/stderr application logs are matched (log ids run.googleapis.com/stdout and
#     run.googleapis.com/stderr). Cloud Run's own request log (5xx from cold starts) is not
#     matched, so a rejected delivery that QStash retries does not page anyone.
#   * The Worker also logs an error for every failed attempt that will be retried
#     ("job handler failed"), so a transient failure can alert. Tighten the filter to the
#     permanent-failure event once M3-00a fixes its name (open question for the lead).
#   * Stuck outbox rows and stuck jobs (queued_stuck, unpublished_stuck, ...) are derived from
#     database state when the Admin list is read. Nothing is logged for them, so no log-based
#     metric can see them. They stay visible in the Admin list (the manual step of MON-06).
#   * Billing budgets stay manual (COST-04); an alert policy here is not a spending cap.
#
# Cost: alert policies and email channels are not metered per policy as far as known; log-based
# metrics and the log volume follow Cloud Logging and Cloud Monitoring pricing. UNVERIFIED for this
# project; confirm on the pricing pages before enabling. Nothing has been planned or applied.

locals {
  m3_alert_targets = var.enable_m3_alerts ? {
    worker = { service = google_cloud_run_v2_service.worker.name, label = "Worker" }
    api    = { service = google_cloud_run_v2_service.api.name, label = "API" }
  } : {}
}

resource "google_logging_metric" "app_errors" {
  for_each = local.m3_alert_targets
  project  = var.project_id
  name     = "knowserve_${each.key}_errors"

  description = "Application log entries of severity ERROR or higher from ${each.value.service} (MON-06)."
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${each.value.service}\"",
    "(log_id(\"run.googleapis.com/stdout\") OR log_id(\"run.googleapis.com/stderr\"))",
    "severity>=ERROR",
  ])

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_notification_channel" "m3_email" {
  count        = var.enable_m3_alerts ? 1 : 0
  project      = var.project_id
  display_name = "KnowServe alerts (email)"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "app_errors" {
  for_each     = local.m3_alert_targets
  project      = var.project_id
  display_name = "KnowServe ${each.value.label}: application errors"
  combiner     = "OR"

  conditions {
    display_name = "${each.value.label} logged at least one ERROR in 5 minutes"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.app_errors[each.key].name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  notification_channels = [google_monitoring_notification_channel.m3_email[0].id]

  depends_on = [google_project_service.apis]
}
