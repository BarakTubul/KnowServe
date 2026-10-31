# The app is served from the default https://<name>.pages.dev host and proxies /api/* to the
# Cloud Run API through a Pages Function (docs/contracts/proxy.md). No custom domain is used.
resource "cloudflare_pages_project" "app" {
  account_id        = var.cloudflare_account_id
  name              = var.pages_project_name
  production_branch = var.pages_production_branch

  deployment_configs = {
    # Cloudflare requires `fail_open` to be identical for production and preview (the first apply
    # was rejected with error 8000066 when it was left unset). It is false (fail closed) so that,
    # if the Function cannot run (for example the free request quota is exhausted), /api/* returns
    # an error instead of silently serving the static single-page app in place of an API response.
    preview = {
      fail_open = false
    }
    production = {
      fail_open = false
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

  lifecycle {
    # PROXY_SHARED_SECRET is a Pages secret set out of band with `wrangler pages secret put` (its
    # value comes from Secret Manager and must never enter Terraform state). Cloudflare reports
    # it back as an env var with an empty value, so without this Terraform plans to strip it
    # (observed in the first full plan after the secret was set: applying that plan could have
    # removed the secret and broken the proxy). API_ORIGIN stays managed.
    ignore_changes = [
      deployment_configs.production.env_vars["PROXY_SHARED_SECRET"],
    ]
  }
}
