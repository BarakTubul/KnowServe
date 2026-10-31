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
`deploy.yml` currently runs only on manual `workflow_dispatch` (input `confirm_spike_deploy` must equal `yes`); the `push: main` trigger is deliberately disabled until the user approves it. Its `gate` job requires the `ci-required` check run of the same commit to be `success` and the ref to be `main`; the `deploy` job `needs` the gate and runs in the `production` environment. Under the A3 spike exception, use manual dispatch only until the user approves the push trigger. Merging to `main` requires the human-approved milestone PR (branch protection below).

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
| `E2E_BASE_URL` | the app's `https://<project>.pages.dev` URL; the Playwright smoke and the proxy smoke target it (default: `https://<CLOUDFLARE_PAGES_PROJECT>.pages.dev`) |
| `WORKER_REQUIRES_IAM` | `true` if the worker service is private and the smoke must send an identity token |

## Repository secrets (names only)
| Name | Meaning |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token limited to Pages edit on the one project |

`VITE_API_BASE_URL` is no longer a repository variable: the workflow builds with `/api` (same-origin proxy, `docs/contracts/proxy.md`). The proxy secret is never stored in GitHub and CI never needs it.

## Secrets the user sets outside GitHub (names only)
| Name | Where | Meaning |
|---|---|---|
| `PROXY_SHARED_SECRET` | Cloudflare Pages secret, set manually with `wrangler pages secret put PROXY_SHARED_SECRET --project-name <name>` | value sent by the Pages Function as `X-KS-Proxy-Secret` |
| `proxy-shared-secret` | Google Secret Manager (container created by Terraform, value added by the user) | same value; exposed to the API as `KS_PROXY_SHARED_SECRET` |

The post-deploy smoke calls `<pages-url>/api/v1/status` and asserts that the direct Cloud Run API URL without the secret returns 403. No custom domain is required.

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

## Workload Identity trust (Terraform: `infra/terraform/gcp_github_wif.tf`)
GitHub Actions gets Google credentials only through Workload Identity Federation (no key file). A token is accepted only if **all** of these hold (the provider's attribute condition, checked at token exchange; any mismatch is rejected):

| Claim | Required value |
|---|---|
| `repository_id` | `1074746051` (immutable, not secret) |
| `repository_owner_id` | `168983818` (immutable, not secret) |
| `repository` | `BarakTubul/KnowServe` |
| `ref` | `refs/heads/main` |
| `environment` | `production` |
| `sub` | `repo:BarakTubul/KnowServe:environment:production` |
| `workflow_ref` | `BarakTubul/KnowServe/.github/workflows/deploy.yml@refs/heads/main` |

Issuer `https://token.actions.githubusercontent.com`; the audience is the provider default (the provider's resource URL, which `google-github-actions/auth` sets). `google.subject` is mapped from `sub`, and the one impersonation grant is `roles/iam.workloadIdentityUser` on `ks-github-deployer` for `principal://iam.googleapis.com/projects/<project number>/locations/global/workloadIdentityPools/github/subject/repo:BarakTubul/KnowServe:environment:production`. It is a single subject, not a `principalSet`.

The deployer holds only: `run.developer` on `knowserve-api` and `knowserve-worker` (service scope), `artifactregistry.writer` on the `knowserve` repository, and `serviceAccountUser` on `ks-api-runtime` and `ks-worker-runtime`. No project-level role, no Secret Manager access, no IAM administration, no Owner or Editor.

`workflow_ref` is used instead of `job_workflow_ref`: GitHub documents `job_workflow_ref` only for jobs that call a reusable workflow, and says nothing about regular workflows, so it is not relied on. `workflow_ref` is documented for every workflow.

Limitations (honest scope): `workflow_ref` pins the top-level workflow file, not its content, so anyone who can merge to `main` can change what `deploy.yml` does (hence branch protection below). Someone approved to deploy can deploy any image, which can read the runtime accounts' secrets; the environment reviewer is the control. Repository admins can change environment rules. Claim names and values are UNVERIFIED until a real run.

## GitHub-side prerequisites (user configures before the first deploy; nothing here has been configured)
As of the last check the repository is public, has no `production` environment and no confirmed branch protection on `main`. Until the environment exists, no workflow can authenticate (fail closed).
1. Settings, Environments, `production`: required reviewer (you), deployment branches limited to `main`, no wildcard branch rules.
2. Settings, Branches, rule for `main`: require a pull request, require the `ci-required` status check, block force pushes and deletion, include administrators if practical.
3. Add a `CODEOWNERS` entry for `.github/workflows/`, `infra/` and `docs/contracts/ci-and-branch-protection.md` and require code-owner review on `main`.
4. Settings, Actions, General: workflow permissions read-only by default; require approval for workflows from outside collaborators and for fork pull requests.
5. Keep the `push: main` trigger of `deploy.yml` disabled; deploy by manual dispatch only.
6. Set the repository variables listed above (`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, ...), using Terraform's outputs.

## Verifying the claims at the first real run
Before trusting the setup, confirm on the first approved run (and keep the negative checks):
1. **Positive:** the `google-github-actions/auth` step succeeds from `main`, environment `production`, `deploy.yml`.
2. **If it is rejected** ("credential is rejected by the attribute condition"): add a temporary step before the auth step that requests an ID token from `ACTIONS_ID_TOKEN_REQUEST_URL` (the job already has `id-token: write`), decodes it and prints only these claims: `sub`, `repository`, `repository_id`, `repository_owner_id`, `ref`, `environment`, `workflow_ref`, `job_workflow_ref`. Never print or log the token. Compare each value with the table, fix the Terraform in the matching claim, and remove the step.
3. **Negative:** a run from another branch, a job without `environment: production`, and a different workflow file must all fail to authenticate (they fail at token exchange).
4. **Least privilege:** with the deployer identity, `gcloud secrets versions access` on any secret and any project-level change must be denied.
5. Record the evidence in `docs/milestones/M0/test-plan.md` (M0-AC08).
