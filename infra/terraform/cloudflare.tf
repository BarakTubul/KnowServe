# The app is served from the default https://<name>.pages.dev host and proxies /api/* to the
# Cloud Run API through a Pages Function (docs/contracts/proxy.md). No custom domain is used.
resource "cloudflare_pages_project" "app" {
  account_id        = var.cloudflare_account_id
  name              = var.pages_project_name
  production_branch = var.pages_production_branch

  deployment_configs = {
    production = {
      # Plain (non-secret) variable only. The Pages secret PROXY_SHARED_SECRET is set manually
      # with `wrangler pages secret put` and is deliberately NOT managed here (it would enter state).
      env_vars = {
        API_ORIGIN = {
          type  = "plain_text"
          value = var.api_origin
        }
      }
    }
  }
}
