resource "google_billing_budget" "project" {
  billing_account = var.billing_account_id
  display_name    = "knowserve-${var.project_id}"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = tostring(var.budget_amount_units)
    }
  }

  dynamic "threshold_rules" {
    for_each = var.budget_threshold_percents
    content {
      threshold_percent = threshold_rules.value
    }
  }

  dynamic "all_updates_rule" {
    for_each = length(var.budget_notification_channel_ids) > 0 ? [1] : []
    content {
      monitoring_notification_channels = var.budget_notification_channel_ids
    }
  }

  depends_on = [google_project_service.apis]
}
