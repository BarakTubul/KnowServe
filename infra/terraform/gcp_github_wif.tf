# GitHub Actions authenticates through Workload Identity Federation: no JSON keys (INFRA-07).

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.apis]
}

locals {
  # The only identity allowed to deploy: the deploy workflow, on main, in the `production`
  # environment of one repository. Every value below must match for a token to be accepted.
  github_environment  = "production"
  github_deploy_ref   = "refs/heads/main"
  github_deploy_sub   = "repo:${var.github_repository}:environment:${local.github_environment}"
  github_workflow_ref = "${var.github_repository}/.github/workflows/deploy.yml@${local.github_deploy_ref}"

  # Checked at token exchange (fail closed). Immutable numeric IDs defend against a renamed,
  # deleted or transferred repository whose name is later taken by someone else.
  github_wif_condition = join(" && ", [
    "assertion.repository_id == \"${var.github_repository_id}\"",
    "assertion.repository_owner_id == \"${var.github_repository_owner_id}\"",
    "assertion.repository == \"${var.github_repository}\"",
    "assertion.ref == \"${local.github_deploy_ref}\"",
    "assertion.environment == \"${local.github_environment}\"",
    "assertion.sub == \"${local.github_deploy_sub}\"",
    "assertion.workflow_ref == \"${local.github_workflow_ref}\"",
  ])
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  # google.subject is GitHub's `sub` claim, which for a job that references an environment is
  # exactly `repo:OWNER/REPO:environment:NAME` (docs.github.com, OIDC claims). The impersonation
  # binding below names that same subject, so the two cannot drift apart.
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
    "attribute.environment"         = "assertion.environment"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
  }

  # `workflow_ref` (the path of the running workflow file) is used, not `job_workflow_ref`:
  # GitHub documents job_workflow_ref only for jobs that call a reusable workflow, while
  # workflow_ref is documented for every workflow. Claim names are unverified until a real run
  # (docs/contracts/ci-and-branch-protection.md, "Verifying the claims").
  attribute_condition = local.github_wif_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Exactly one subject may impersonate the deployer (a principal, not a principalSet): the
# `production` environment of this repository. The branch, workflow and ID checks are enforced by
# the provider condition above.
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/${local.github_deploy_sub}"
}

# Deployer minimal roles: deploy the two services, push images, act as the runtime accounts only.
resource "google_cloud_run_v2_service_iam_member" "deployer_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_worker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_acts_as_api" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_acts_as_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
