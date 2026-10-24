resource "cloudflare_pages_project" "app" {
  account_id        = var.cloudflare_account_id
  name              = var.pages_project_name
  production_branch = var.pages_production_branch
}

# Optional custom domain for the app host. Disabled when app_custom_domain is empty.
resource "cloudflare_pages_domain" "app" {
  count        = var.app_custom_domain == "" ? 0 : 1
  account_id   = var.cloudflare_account_id
  project_name = cloudflare_pages_project.app.name
  name         = var.app_custom_domain
}
