# CI and branch protection (M0-10, M0-06)

Requirements: INFRA-04, INFRA-06, INFRA-07, WF-06, WF-13. Workflows: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`.

Status: workflows are authored and linted locally (actionlint, third-party actions pinned by commit SHA, local gitleaks over the full history: no findings). They have **not** been run on GitHub. Branch protection and the GitHub Environment are **not** configured; the user applies them. This repository is public.

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
`deploy.yml` runs only on manual `workflow_dispatch` from `main`; the `push: main` trigger is deliberately disabled. Inputs: `target` (the GitHub Environment; today only `spike`), `mode` (`auth-check` or `deploy`), `debug_claims` and `confirm` (must equal `yes`). The `gate` job requires the `ci-required` check run of the same commit to be `success`; the `deploy` job `needs` the gate and runs in the chosen environment, so the environment's required reviewer must approve it. Merging to `main` requires the human-approved PR (branch protection below). `workflow_dispatch` is available only after `deploy.yml` exists on `main`.

What each mode does (all values come from the environment's variables and secrets, so the same workflow can serve a future `production` environment by adding it to the `target` options):
- **`auth-check`**: project consistency guard, optional claim print, WIF login, then read-only calls (list Cloud Run services and registry images) and two checks that MUST be denied (listing secrets, reading the project IAM policy). No build, no push, no deploy.
- **`deploy`**: the same login, then build and push both images (deployed by digest), optional migration, `gcloud run deploy` for API and Worker (image only; environment variables, flags and secrets untouched), Cloudflare Pages deployment, smoke checks (Pages proxy status, direct API 403, Worker readiness, deployed Playwright smoke).
- A guard step fails early if `GCP_SERVICE_ACCOUNT` does not end with `@<GCP_PROJECT_ID>.iam.gserviceaccount.com`, so a mismatched project cannot be targeted by accident (the deployer also exists, and holds roles, only in its own project).
- Migrations run only if the environment variable `RUN_MIGRATIONS` is `true`; leave it unset in M0 (the deployer cannot read the database secret by design; a separate migration job is an M1 decision).

## Target environments (user configures)
One GitHub Environment per deployment target, with the **same variable names** and different values: `spike` now (project `knowserve-m0-spike`) and `production` later (project `knowserve-prod`). The name must equal Terraform's `github_environment` for that project, because the Workload Identity condition and subject include it. Settings, Environments, `spike`:
- Required reviewers: the user (so every deploy needs an explicit approval click).
- Deployment branches: selected branches, `main` only.
- Prevent self-review: on if a second reviewer exists; otherwise leave off.
- Put `CLOUDFLARE_API_TOKEN` here as an **environment secret**, using a new token limited to Pages edit (not your local token).

## Environment variables (names only; Settings, Environments, <name>, Environment variables)
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
| `RUN_MIGRATIONS` | optional; `true` runs `alembic upgrade head` (needs a deployer that may read the database secret; leave unset in M0) |

## Environment secrets (names only)
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

**Required before any deployment (security review H1/M2):** the target environment (`spike`) must have required reviewers and be restricted to `main`, and `main` must be protected. The Workload Identity condition in Terraform only trusts runs on `refs/heads/main` that declare the matching environment (`environment: spike` for the spike project), so these GitHub settings are part of the security boundary, not optional hardening. The automatic `push: main` deploy trigger stays disabled in `deploy.yml` until the user approves enabling it.

Restrict the environment to `main`:

```bash
gh api -X PUT repos/OWNER/REPO/environments/spike \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
gh api -X POST repos/OWNER/REPO/environments/spike/deployment-branch-policies -f name=main
```

## Known gaps
- Actions are pinned by commit SHA (comment = release line); updating one is a manual, reviewed change. Pages deploys use the Wrangler version pinned in `apps/frontend`.
- The workflows were not executed remotely. The deployed Playwright smoke runs from `apps/frontend` (where Playwright and its config live) against the computed Pages URL; it has never run.
- Frontend jobs depend on `apps/frontend` scripts (`lint`, `format:check`, `typecheck`, `test`, `build`, `check:api`) and the Docker jobs on `apps/api/Dockerfile` and `apps/worker/Dockerfile`, written by other streams.

## Workload Identity trust (Terraform: `infra/terraform/gcp_github_wif.tf`)
GitHub Actions gets Google credentials only through Workload Identity Federation (no key file). A token is accepted only if **all** of these hold (the provider's attribute condition, checked at token exchange; any mismatch is rejected):

| Claim | Required value |
|---|---|
| `repository_id` | `1074746051` (immutable, not secret) |
| `repository_owner_id` | `168983818` (immutable, not secret) |
| `repository` | `BarakTubul/KnowServe` |
| `ref` | `refs/heads/main` |
| `environment` | the project's `github_environment`: `spike` for `knowserve-m0-spike` |
| `sub` | `repo:BarakTubul/KnowServe:environment:<github_environment>` (spike: `...:environment:spike`) |
| `workflow_ref` | `BarakTubul/KnowServe/.github/workflows/deploy.yml@refs/heads/main` |

Issuer `https://token.actions.githubusercontent.com`; the audience is the provider default (the provider's resource URL, which `google-github-actions/auth` sets). `google.subject` is mapped from `sub`, and the one impersonation grant is `roles/iam.workloadIdentityUser` on `ks-github-deployer` for `principal://iam.googleapis.com/projects/<project number>/locations/global/workloadIdentityPools/github/subject/repo:BarakTubul/KnowServe:environment:<github_environment>`. It is a single subject, not a `principalSet`.

The deployer holds only: `run.developer` on `knowserve-api` and `knowserve-worker` (service scope), `artifactregistry.writer` on the `knowserve` repository, and `serviceAccountUser` on `ks-api-runtime` and `ks-worker-runtime`. No project-level role, no Secret Manager access, no IAM administration, no Owner or Editor.

`workflow_ref` is used instead of `job_workflow_ref`: GitHub documents `job_workflow_ref` only for jobs that call a reusable workflow, and says nothing about regular workflows, so it is not relied on. `workflow_ref` is documented for every workflow.

Limitations (honest scope): `workflow_ref` pins the top-level workflow file, not its content, so anyone who can merge to `main` can change what `deploy.yml` does (hence branch protection below). Someone approved to deploy can deploy any image, which can read the runtime accounts' secrets; the environment reviewer is the control. Repository admins can change environment rules. Claim names and values are UNVERIFIED until a real run.

## GitHub-side prerequisites (user configures before the first deploy; nothing here has been configured)
As of the last check the repository is public, has no GitHub Environment (`spike`) and no confirmed branch protection on `main`. Until the environment exists, no workflow can authenticate (fail closed).
1. Settings, Environments, `spike`: required reviewer (you), deployment branches limited to `main`, no wildcard branch rules.
2. Settings, Branches, rule for `main`: require a pull request, require the `ci-required` status check, block force pushes and deletion, include administrators if practical.
3. `.github/CODEOWNERS` exists (owner `@BarakTubul` for `.github/`, `infra/`, `docs/contracts/`, ADRs, migrations, `AGENTS.md`); enable "Require review from Code Owners" on `main`.
4. Settings, Actions, General: workflow permissions read-only by default; require approval for workflows from outside collaborators and for fork pull requests.
5. Keep the `push: main` trigger of `deploy.yml` disabled; deploy by manual dispatch only.
6. Set the environment variables and secret listed above (`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT` from Terraform's outputs, ...).
7. Apply the Terraform environment rename (`github_environment = "spike"`) **before** the first dispatch; until then the cloud still trusts `production` and the `spike` environment cannot authenticate.

## Verifying the claims at the first real run
Before trusting the setup, confirm on the first approved run (and keep the negative checks):
1. **Positive:** run `deploy` with `mode=auth-check`; the `google-github-actions/auth` step succeeds from `main`, environment `spike`, `deploy.yml`, and the two denial checks pass.
2. **If it is rejected** ("credential is rejected by the attribute condition"): re-run with `debug_claims=true`, which runs a step before the auth step that requests an ID token from `ACTIONS_ID_TOKEN_REQUEST_URL` (the job already has `id-token: write`), decodes it and prints only these claims: `sub`, `repository`, `repository_id`, `repository_owner_id`, `ref`, `environment`, `workflow_ref`, `job_workflow_ref`. Never print or log the token. Compare each value with the table, fix the Terraform in the matching claim, and remove the step.
3. **Negative:** a run from another branch, a job without the matching environment, and a different workflow file must all fail to authenticate (they fail at token exchange).
4. **Least privilege:** with the deployer identity, `gcloud secrets versions access` on any secret and any project-level change must be denied.
5. Record the evidence in `docs/milestones/M0/test-plan.md` (M0-AC08).

## Safe first-run procedure
1. Push `m0/integration` as a branch (account `BarakTubul`): CI runs on GitHub runners only; no secrets, no cloud. Fix any CI failure locally.
2. Open the PR to `main`, let `ci-required` pass, then enable branch protection (the required check name exists only after the first run) and merge.
3. Create the `spike` environment, its variables and the Pages-scoped secret; apply the Terraform rename (user).
4. Dispatch `deploy` with `target=spike`, `mode=auth-check`, `confirm=yes`; approve it as reviewer. It must pass.
5. Dispatch `mode=deploy`; approve; afterwards verify revisions, the Pages deployment and the endpoints. Rollback: route Cloud Run traffic to the previous revision; roll back the Pages deployment.
6. Record the evidence in `docs/milestones/M0/test-plan.md` (M0-AC07, AC08, AC12).

## Reusing this setup for a production project
Create GCP project `knowserve-prod` with its own state bucket, its own tfvars and backend file (git-ignored), `github_environment = "production"`, and a GitHub Environment `production` with the same variable names, a reviewer and `main`-only deployment. Add `production` to the `target` options of `deploy.yml`. Each project has its own Workload Identity pool, deployer, registry and Pages project, and uses separate Neon, QStash and Cloudflare resources.
