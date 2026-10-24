# ADR 0003: Environments and cloud bootstrap

Status: proposed by the Owner; **takes effect only after user approvals A3 and A4** (`docs/milestones/M0/plan.md`). Date: 2026-10-24.

## Decision (proposal)
- One environment: Production (INFRA-01). Local and ephemeral CI environments exist; there is no permanent staging.
- Terraform code is prepared locally and validated without cloud access (`terraform fmt`, `validate`). `terraform plan` and `apply` need credentials and the user's explicit authorization.
- The **bootstrap** the user performs once (outside Terraform): the GCP project with billing, the Terraform state bucket, and Workload Identity Federation trust for the GitHub repository. Everything after that is Terraform.
- Terraform creates secret containers and IAM bindings only; the user enters secret values. No secret value is written in Terraform files, variables files that are committed, or state.
- Image release is independent of `terraform apply`: the deploy workflow builds and pushes images and rolls a new Cloud Run revision.

## Consequences
- Until the user provides the bootstrap, all cloud-dependent acceptance criteria are `BLOCKED — requires approved cloud access/deployment`.
