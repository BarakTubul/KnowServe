# CI and branch protection (M0-10, M0-06)

Requirements: INFRA-04, INFRA-06, INFRA-07, WF-06, WF-13. Workflows: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`.

Status: workflows are authored and linted locally (actionlint). They have **not** been run on GitHub. Branch protection and the `production` environment are **not** configured; the user applies them.

## Required checks
Only one check is required: **`ci-required`** (aggregate job of `ci.yml`). It fails if any of these jobs failed, was cancelled or was skipped:

| Job | What it runs |
|---|---|
| `python` | `uv sync --frozen`, `ruff format --check`, `ruff check`, `pyright`, `pytest -q` against a `pgvector/pgvector:pg16` service container (database `knowserve_test`, `KS_TEST_DATABASE_URL`) |
| `openapi-drift` | regenerates the OpenAPI document and fails on any diff against `docs/contracts/openapi.json` |
| `frontend` | frozen pnpm install, lint, format:check, typecheck, test, build, `check:api` (Node 22) |
| `docker-build` (api, worker) | builds both images from the repository root, no push |
| `terraform-validate` | `fmt -check -recursive`, `init -backend=false`, `validate` in `infra/terraform` (skipped cleanly when no `.tf` files exist) |
| `secret-scan` | gitleaks (pinned image) over the full history |

Triggers: pull requests, pushes to `main`, pushes to `m0/**`. Permissions: `contents: read`. Superseded runs are cancelled.

## Deploy gating (INFRA-04)
`deploy.yml` runs on push to `main` and on manual `workflow_dispatch` (input `confirm_spike_deploy` must equal `yes`). Its `gate` job requires the `ci-required` check run of the same commit to be `success` and the ref to be `main`; the `deploy` job `needs` the gate and runs in the `production` environment. Under the A3 spike exception, use manual dispatch only until the user approves the push trigger. Merging to `main` requires the human-approved milestone PR (branch protection below).

## `production` environment (user configures)
Settings, Environments, `production`:
- Required reviewers: the user (so every deploy needs an explicit approval click).
- Deployment branches: selected branches, `main` only.
- Prevent self-review: on if a second reviewer exists; otherwise leave off.
- Put `CLOUDFLARE_API_TOKEN` as an environment secret here if preferred over a repository secret (the name is identical).

## Repository variables (names only; Settings, Secrets and variables, Variables)
| Name | Meaning |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | full resource name of the Workload Identity provider |
| `GCP_SERVICE_ACCOUNT` | deployer service account email |
| `GCP_PROJECT_ID` | GCP project id |
| `GCP_REGION` | Artifact Registry and Cloud Run region |
| `GAR_REPOSITORY` | Artifact Registry repository name |
| `GCP_DATABASE_URL_SECRET_NAME` | Secret Manager secret id holding the migration database URL |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account id |
| `CLOUDFLARE_PAGES_PROJECT` | Pages project name |
| `VITE_API_BASE_URL` | optional; build-time API base URL (defaults to the deployed API URL) |
| `E2E_BASE_URL` | URL the Playwright smoke targets (the deployed frontend) |
| `WORKER_REQUIRES_IAM` | `true` if the worker service is private and the smoke must send an identity token |

## Repository secrets (names only)
| Name | Meaning |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token limited to Pages edit on the one project |

No Google key file and no database URL is stored in GitHub; the database URL is read from Secret Manager at deploy time and masked.

## Branch protection (user runs; not run by the agent)
Replace `OWNER/REPO`. This requires a PR with one approving review, the `ci-required` check up to date, conversation resolution, no force pushes, no deletions, and applies to admins.

```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["ci-required"] },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
```

If the user is the only maintainer, GitHub does not allow approving one's own PR; either set `required_approving_review_count` to `0` (the PR plus `ci-required` still gates the merge) or add a second reviewer. Decide this explicitly, it is the user's approval point for WF-13.

**Required before any deployment (security review H1/M2):** the `production` environment must have required reviewers and be restricted to `main`, and `main` must be protected. The Workload Identity condition in Terraform only trusts runs on `refs/heads/main` that declare `environment: production`, so these GitHub settings are part of the security boundary, not optional hardening. The automatic `push: main` deploy trigger stays disabled in `deploy.yml` until the user approves enabling it.

Restrict the `production` environment to `main`:

```bash
gh api -X PUT repos/OWNER/REPO/environments/production \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST repos/OWNER/REPO/environments/production/deployment-branch-policies -f name=main
```

## Known gaps
- Actions are pinned by major tag, not SHA. SHA pinning is recommended once real SHAs can be looked up with network or `gh` access.
- The workflows were not executed remotely. The deployed Playwright smoke needs `tests/e2e/smoke.spec.ts` and a Playwright config and dependency resolvable from the repository root (not present yet).
- Frontend jobs depend on `apps/frontend` scripts (`lint`, `format:check`, `typecheck`, `test`, `build`, `check:api`) and the Docker jobs on `apps/api/Dockerfile` and `apps/worker/Dockerfile`, written by other streams.
