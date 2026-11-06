# M0 handoff (WF-12)

**Status (2026-10-31):** M0 local implementation is complete, and a temporary, isolated cloud spike was built, tested live and cleaned up. **Update 2026-11-06:** PR #21 and PR #22 are merged, branch protection is on, `auth-check` and `deploy` ran on GitHub and passed (M0-AC07, AC08 and the OIDC part of AC12). **Formal M0 completion is still not claimed**: M0-AC09 has no measured costs yet. A full `terraform plan` after the Workload Identity rename shows no changes, and the negative auth runs for the branch cases passed. Everything is on `main`. Specs and contracts: `docs/contracts/`, `plan.md`, `test-plan.md`, `tasks.md`, `bootstrap-plan.md`, `spike-report.md`, `hosting-comparison.md`.

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
- GitHub Actions negative cases not isolated: a run on `main` without the environment and another workflow file on `main`. The branch cases and the positive path are proven (2026-11-06, see `test-plan.md`).
- Costs: nothing measured. Check the billing report after a day or two of the idle project (Cloud Run, Artifact Registry, Secret Manager, logging) and Neon compute hours.
- Pages Function behaviour beyond 120 s and its free quota fit; Cloudflare preview deployments (no `API_ORIGIN` in the preview environment).
- Duplicate delivery against live QStash (covered locally only); batch dispatcher (optional, disabled, known lease gap documented).

## Decisions and open items for the owner
1. **GitHub setup: done (2026-11-06).** Branch protection with `ci-required`, the `spike` environment (required reviewer, `main` only) and its variables are in place; `CLOUDFLARE_API_TOKEN` is an environment secret; Terraform `github_environment = "spike"` is applied; `auth-check` and `deploy` ran and passed. Still to decide later: a `production` environment (not needed for the spike), and OPEN-22 (CI/CD efficiency).
2. **M1 migration permissions:** the deployer cannot read `database-url` on purpose, but `deploy.yml` reads it to migrate. Recommended: a Cloud Run job with its own account and a separate migration secret; not needed until the first schema change (Neon is at revision 0001).
3. **Default Compute service account has `roles/editor`** on the project (created by Google when APIs were enabled). Nothing uses it; removing the binding is an IAM change that needs approval.
4. **Remaining security-review items:** pin third-party GitHub Actions and Wrangler by digest; outbox max-attempts dead state and a sweeper for jobs QStash never finishes (M3); lease heartbeat (before M3); `last_error` content, certificate-fetch amplification, `KS_ENV` guard on Cloud Run (low).
5. **Local housekeeping:** committed legacy binaries (`backend/app/chroma_data`, sample PDFs) and `.gitattributes` line endings; `allowBuilds` in `pnpm-workspace.yaml`; `OPEN-02/03/05/06/08/09/10` remain open in `docs/open-decisions.md`.
6. **Spike teardown / pause:** `terraform destroy` then deleting the state bucket and project is destructive and needs separate approval; the Neon, Upstash and Cloudflare projects are separate and manual. Credentials to revoke afterwards: `gcloud auth application-default revoke`, the Cloudflare API token, and QStash/Neon keys.
7. **Terraform notes:** the Pages secret is protected by `ignore_changes`; Cloud Run images roll with `gcloud run services update` (image is ignored by Terraform, state is refreshed on every plan: never use `-refresh=false`); Pages `fail_open=false`.

## Incidents worth knowing
A Worker revision failed its startup probe because of a settings validator I had added (traffic stayed on the previous revision; fixed with a regression test). A saved plan once proposed removing the Pages secret (not applied; fixed). The gcloud impersonation shortcut for ID tokens needs a wider role than the one granted; the direct IAM Credentials call is used instead.
