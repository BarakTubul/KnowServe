output "api_url" {
  description = "Default Cloud Run URL of the API."
  value       = google_cloud_run_v2_service.api.uri
}

output "worker_url" {
  description = "Default Cloud Run URL of the Worker (QStash destination base, scheduler audience default)."
  value       = google_cloud_run_v2_service.worker.uri
}

output "artifact_registry_repository" {
  description = "Docker repository path for image pushes."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "deployer_service_account" {
  description = "Value for the GitHub workflow service_account input."
  value       = google_service_account.deployer.email
}

output "workload_identity_provider" {
  description = "Value for the GitHub workflow workload_identity_provider input."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "secret_ids" {
  description = "Secret Manager containers the user must populate (values are never managed by Terraform)."
  value       = sort(keys(google_secret_manager_secret.secrets))
}

output "pages_project_subdomain" {
  description = "Default pages.dev subdomain of the Pages project."
  value       = cloudflare_pages_project.app.subdomain
}
