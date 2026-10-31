# M0 handoff (WF-12)

**Status (2026-10-31):** M0 local implementation is complete, and a temporary, isolated cloud spike was built, tested live and cleaned up. **Formal M0 completion is not claimed**: the GitHub-dependent criteria have not run (M0-AC07 branch protection, M0-AC08 deploy workflow, the rest of M0-AC12) and M0-AC09 has no measured costs yet. Branch `m0/integration` holds everything; nothing was pushed or merged. Specs and contracts: `docs/contracts/`, `plan.md`, `test-plan.md`, `tasks.md`, `bootstrap-plan.md`, `spike-report.md`, `hosting-comparison.md`.

## What exists now
| Layer | State |
|---|---|
| Repository | Monorepo (`apps/api`, `apps/worker`, `apps/frontend`, `packages/backend_core`, `infra/terraform`), legacy `backend/` and `frontend/` untouched (ADR 0001). 206 Python tests, 56 frontend tests, `check:api`, actionlint, Terraform validate: all passing locally. |
| Cloud (project `knowserve-m0-spike`, `europe-west1`) | Cloud Run `knowserve-api` and `knowserve-worker` (0 to 2 instances, scale to zero, public invoker by design), Artifact Registry `knowserve`, Secret Manager (5 secrets, one version each, entered by the owner), service accounts (runtime x2, deployer), Workload Identity pool `github` (idle until a GitHub run), Terraform state bucket (versioned, EU). |
| Cloudflare | Pages project `knowserve-m0-spike` serving the SPA and the `/api/*` proxy Function (`pages.dev`), Pages secret `PROXY_SHARED_SECRET`. |
| Data and queue | Neon (eu-central-1, PostgreSQL 18.6, pgvector 0.8.6, migration 0001); QStash EU. The dead-letter queue is empty. |
| Spike surface | **Off.** API and Worker revisions 00004 carry no spike flags; the operator service account was deleted; routes return 404. |

## Live evidence (see `test-plan.md`)
Proxy route on the real edge (SSE 30 s and 120 s incremental, cookie flags, real client IP, direct access 403, spoofed headers ignored); Google ID-token access control (6 cases); immediate QStash publish (done in 3.4 s); crash-after-commit recovery; QStash retries (4 deliveries over about 33 minutes), terminal failure with 500, DLQ, manual retry and recovery; retry rejections (409, 404).

## Not verified (do not claim)
- GitHub Actions: CI and `deploy.yml` have never run; the Workload Identity claims (`repository_id`, `repository_owner_id`, `environment`, `workflow_ref`, `sub`) are unproven until a real run; GitHub `production` environment and branch protection do not exist yet.
- Costs: nothing measured. Check the billing report after a day or two of the idle project (Cloud Run, Artifact Registry, Secret Manager, logging) and Neon compute hours.
- Pages Function behaviour beyond 120 s and its free quota fit; Cloudflare preview deployments (no `API_ORIGIN` in the preview environment).
- Duplicate delivery against live QStash (covered locally only); batch dispatcher (optional, disabled, known lease gap documented).

## Decisions and open items for the owner
1. **GitHub setup** (before any deploy workflow; the pre-push review, hardened workflows, `CODEOWNERS` and the first-run procedure are in `ci-and-branch-protection.md`; the GitHub Environment for this project is now `spike`, which needs the Terraform `github_environment` change applied first): push approval, `production` environment (required reviewer, `main` only), branch protection with the `ci-required` check, CODEOWNERS, Actions settings (`ci-and-branch-protection.md`). Then the first run verifies the Workload Identity claims; the debug step to use if it is rejected is documented there.
2. **M1 migration permissions:** the deployer cannot read `database-url` on purpose, but `deploy.yml` reads it to migrate. Recommended: a Cloud Run job with its own account and a separate migration secret; not needed until the first schema change (Neon is at revision 0001).
3. **Default Compute service account has `roles/editor`** on the project (created by Google when APIs were enabled). Nothing uses it; removing the binding is an IAM change that needs approval.
4. **Remaining security-review items:** pin third-party GitHub Actions and Wrangler by digest; outbox max-attempts dead state and a sweeper for jobs QStash never finishes (M3); lease heartbeat (before M3); `last_error` content, certificate-fetch amplification, `KS_ENV` guard on Cloud Run (low).
5. **Local housekeeping:** committed legacy binaries (`backend/app/chroma_data`, sample PDFs) and `.gitattributes` line endings; `allowBuilds` in `pnpm-workspace.yaml`; `OPEN-02/03/05/06/08/09/10` remain open in `docs/open-decisions.md`.
6. **Spike teardown / pause:** `terraform destroy` then deleting the state bucket and project is destructive and needs separate approval; the Neon, Upstash and Cloudflare projects are separate and manual. Credentials to revoke afterwards: `gcloud auth application-default revoke`, the Cloudflare API token, and QStash/Neon keys.
7. **Terraform notes:** the Pages secret is protected by `ignore_changes`; Cloud Run images roll with `gcloud run services update` (image is ignored by Terraform, state is refreshed on every plan: never use `-refresh=false`); Pages `fail_open=false`.

## Incidents worth knowing
A Worker revision failed its startup probe because of a settings validator I had added (traffic stayed on the previous revision; fixed with a regression test). A saved plan once proposed removing the Pages secret (not applied; fixed). The gcloud impersonation shortcut for ID tokens needs a wider role than the one granted; the direct IAM Credentials call is used instead.
