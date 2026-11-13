# CI/CD proposals (M2-CI)

Requirements: OPEN-22, OPEN-27, TEST-13, M2-AC18. This note recommends. Where the user has already decided something (OPEN-22 partly, OPEN-27 in principle, both 2026-11-07), it says so. No workflow, branch protection, `ci-required`, Terraform or cloud change is made. Any of those needs the user's separate approval.

## OPEN-22: CI efficiency and change policy

Status: **partly decided by the user on 2026-11-07.** Optimize CI for docs-only pull requests only. Every existing gate stays for code changes. Any change to GitHub Actions or branch protection needs separate approval. This section is the design for that decision. Nothing here is implemented.

### What is fixed today
- Branch protection requires one check, `ci-required` (GitHub Actions, `strict: true`). Nothing else is required, so a job skipped inside `ci.yml` does not block a merge by itself.
- `ci-required` has `if: always()` and `needs` all six jobs. It fails on `failure`, `cancelled` and `skipped`.
- Recent `ci` runs finish in about 1.5 to 2 minutes. The saving per docs-only PR is small: fewer runner minutes, not a faster merge. The user can decide it is not worth a workflow change (D1).

### Why not a workflow-level path filter
`paths-ignore` on `on.pull_request` in `ci.yml` stops the whole workflow, so `ci-required` never reports and the PR is blocked. A second workflow that reports a `ci-required` of its own on docs paths would work, but two workflows would then own one required check name, and a PR touching both gets two results. Rejected.

### Design: a `changes` job and a stricter `ci-required`
`ci-required` keeps running on every PR. A new first job decides whether the PR is docs-only, and only the heavy jobs honour that.

**Docs-only means every changed file matches one of these, and nothing else changed:**

| Pattern | Why it is safe |
|---|---|
| `docs/**/*.md` | Prose. Not read by code, build or tests. |
| `README.md`, `AGENTS.md`, `CLAUDE.md` at the repository root | Prose. |

Deliberately **not** docs-only, so they get the full run:
- `docs/contracts/openapi.json` and any other non-`.md` file under `docs/`. `openapi-drift` and `check:api` read the OpenAPI snapshot, and `gen:api` builds the frontend types from it.
- Anything under `.github/` (including `CODEOWNERS` and `ci.yml` itself), `infra/`, `apps/`, `packages/`, `tests/`, lockfiles, Dockerfiles and config files.
- Markdown outside the table, for example under `infra/` or `apps/`.
- Any PR that mixes docs and code.

**The `changes` job**
- Uses plain `git`, so no new third-party action needs a SHA pin. For `pull_request` it fetches the base commit and runs `git diff --name-only --no-renames <base.sha> HEAD`. `--no-renames` lists both sides of a rename, so moving a code file into `docs/` is not hidden.
- Sets `docs_only=true` only if the list is non-empty and every line matches the allowlist. An error, an empty list or any unmatched file gives `false`. The classifier should be a small script under `scripts/ci/` with fixture tests, so the rule is tested like code and not buried in YAML.
- On `push` to `main` it always outputs `false`. Pushes to `main` run everything. This matches "docs-only pull requests only" and keeps the deploy gate looking at a full run.

**Jobs**
- `python`, `openapi-drift`, `frontend`, `docker-build` and `terraform-validate` get `needs: changes` and `if: needs.changes.outputs.docs_only != 'true'`.
- `secret-scan` is **not** skipped. It is the quick job, and a docs PR can still leak a key.
- `ci-required` gets `needs: [changes, <the six jobs>]` and keeps `if: always()`. Its rule changes from "nothing skipped" to:
  1. `changes` must be `success`; otherwise fail.
  2. Any `failure` or `cancelled` result fails the check, always.
  3. `skipped` is accepted only for the five heavy jobs, and only when `docs_only == 'true'`.
  4. `secret-scan` must be `success` in every case.
  5. When `docs_only` is not `true`, every job must be `success`, exactly as today.

**Which checks still report on a docs-only PR:** `changes`, `secret-scan` and `ci-required` run and report. The five heavy jobs show as skipped. Branch protection looks only at `ci-required`, so the merge is not blocked. `strict: true` (branch up to date) is unaffected.

### Risks
| Risk | Effect | Mitigation |
|---|---|---|
| A required check that never runs | PR stuck on "Expected, waiting for status" | Avoided: no workflow-level `paths`, and `ci-required` has `if: always()`. |
| The filter marks a code change as docs-only | Code merges without tests | Allowlist only (default is the full run), `--no-renames`, fixture tests for the classifier, and a full run on every push to `main`. |
| `ci-required` accepts a skip it should not | Silent gap | Skips accepted only for named jobs, only with `docs_only=true`, and `changes` must be `success`. Proved by the test PRs below. |
| A docs file starts to matter to the build | A docs-only PR skips a check it needed | Keep the allowlist at `.md`. Re-check it when a doc becomes an input, for example generated docs. |
| A PR edits `ci.yml` or the classifier | The change tests itself | `.github/**` and `scripts/ci/**` are never docs-only, so they always get the full gate. |
| Deploy gate | None expected | `gate` reads the `ci-required` run of the deployed commit. On `main` that run is always full. |

### Verification before it is trusted
After approval and implementation, open three throw-away PRs and read the results before relying on it: (1) one `.md` file, expect five skips and `ci-required` green; (2) one `.md` plus one `.py` file, expect a full run; (3) a code PR with a deliberately failing test, expect `ci-required` red. Record the run ids in the PR.

### Still-undecided parts of the original OPEN-22
- (a) Drop the `m0/**` push trigger. Low risk, but a workflow change, so it needs the same approval. Independent of the docs-only design (D6).
- (c) Interim rule: batch docs-only edits into one PR per work step or milestone. Unchanged until D1 is decided.
- (d) Push identity: use the `BarakTubul` credential. If `git push` returns 403 as `Barak-Horizon`, push with `git -c credential.helper= -c credential.helper='!gh auth git-credential' push`.

### Changes this would need: NOT APPROVED
1. `.github/workflows/ci.yml`: add the `changes` job, add `needs: changes` and the `if` to five jobs, rewrite `ci-required` (its `needs` and its check step). **NOT APPROVED.**
2. New `scripts/ci/` classifier with fixture tests, run by an existing job. **NOT APPROVED.**
3. Branch protection: **no change needed.** The required check stays `ci-required`.
4. `docs/contracts/ci-and-branch-protection.md`: update the `ci-required` semantics in the same change. **NOT APPROVED.**

## OPEN-27: approval-gated deploy workflow

Status: **approved in principle by the user on 2026-11-07, design only.** An approval-gated deploy workflow, the migration job runs before deployment, dependent jobs are enforced with `needs`, and the Workload Identity Federation (WIF) conditions stay as they are. No workflow change is authorized. The original idea of a `push: main` trigger for ordinary roll-outs is **not** part of this design and stays a later decision (D5).

### What exists today
`deploy.yml` runs by `workflow_dispatch` from `main` (`target`, `mode`, `confirm`). A `gate` job waits for `ci-required` on the commit. One `deploy` job bound to the `production` Environment then does everything as ordered steps: WIF login, build and push, migration (Cloud Run job `knowserve-migrate`, `--wait`), Cloud Run rollout, Pages deploy and smoke checks. The reviewer approves that one job once. Ordering depends on step order inside the job, not on `needs`.

### Design: split the one job into a `needs` chain
The order and the approval point are enforced by `needs`, and a failure stops everything after it.

```
gate        ci-required success for this commit, confirm = yes, ref = main   (no approval, no cloud login)
  |
  v
release     environment: production   <== approval click 1
  |         WIF login, build and push api + worker, output both image digests,
  |         point knowserve-migrate at the API digest, execute with --wait
  v
rollout     needs: release            environment: production   <== approval click 2
            gcloud run deploy api, then worker, by digest; build and deploy Pages;
            smoke: proxy status, direct API 403, worker ready, Playwright
```

- **Approval point.** The `production` Environment with its required reviewer, as today. Each job that names the environment asks for approval separately, so two jobs mean two clicks. WIF's subject includes the environment name, so every job that logs in to Google must run in `production`. That is why the design does not add a third, unapproved job that authenticates.
- **Migration before deployment.** `rollout` has `needs: release`. If the migration fails, is rejected or times out, `rollout` never starts and the old revisions keep serving. Today this holds only because a failed step skips later steps.
- **No bypass.** Nothing that deploys is reachable without passing `release`. If `RUN_MIGRATIONS=false`, the migration step inside `release` is skipped with a visible warning and `release` still ends `success`. A skipped job would make `rollout` skip as well, so the skip must stay a step, not a job.
- **Digests.** `release` passes the two image digests to `rollout` as job outputs. `rollout` never rebuilds.
- **`auth-check` mode** stays a single read-only job.
- **WIF is unchanged.** Repository, `refs/heads/main`, this workflow file and the `production` environment stay as in Terraform. The subject uses the environment and the workflow file, not the job name. No Terraform change is part of this.
- **Concurrency** (`deploy-<target>`, no cancel), the inputs, `confirm` and the `gate` stay as they are.

### Rollback
- Automation never rolls back (TEST-16). A failed `release` leaves the old revisions serving. A failed `rollout` or smoke leaves whatever already rolled out serving and the run red.
- A person follows `docs/architecture/rollback.md`: pick the last healthy revision, check it against the current schema, route traffic with `gcloud run services update-traffic`, check `/health/ready`.
- The frontend is rolled back as a separate Cloudflare Pages deployment rollback.
- Database rollback (`alembic downgrade`) stays a separate decision under the same `production` approval, after a Neon branch or backup.
- No automatic revert after a failed smoke. That would need its own approval and a rule for migrations that are not backward compatible.

### What stays manual
- Starting the workflow (`workflow_dispatch`) and typing `yes`.
- The `production` approval clicks.
- Terraform apply, secret values, the Pages `PROXY_SHARED_SECRET`, Neon roles.
- Rollback and database downgrade.
- Merging the milestone PR (INFRA-04).

### Risks
| Risk | Effect | Mitigation |
|---|---|---|
| Two approval clicks | Slower, and a second wait if the reviewer is away | Accepted, or collapse to one job (D3). |
| Skipped dependency | `rollout` skips silently and the run looks finished | Keep `release` ending `success` or `failure`, never skipped. Check the run summary shows both jobs. |
| Digests lost between jobs | `rollout` deploys the wrong image | Job outputs only; `rollout` has no build step. |
| An authenticated job without the environment | Login rejected by WIF, or a run without approval | Every job that authenticates uses `environment: production`. |
| The split changes the WIF subject | Login rejected | Run `auth-check` first after the change. Use `debug_claims` if rejected. |
| A bug in the new file | Broken deploy path | `auth-check`, then one supervised `deploy` before relying on it. |

### Changes this would need: NOT APPROVED
1. `.github/workflows/deploy.yml`: split `deploy` into `release` and `rollout` with `needs`, job outputs for the digests, `environment: production` on both, `gate` unchanged. **NOT APPROVED.**
2. GitHub Environment `production`: no change planned (required reviewer, `main` only). **NOT APPROVED** to change.
3. Terraform and the WIF conditions: **no change.**
4. `docs/contracts/ci-and-branch-protection.md` and `docs/workflow/testing.md` ("Deployment today vs the policy"): update in the same change. **NOT APPROVED.**
5. After merge: one `auth-check` and one supervised `deploy`, with the run ids recorded in the handoff. Both need the user's approval.

## Decisions the user must make
| Id | Question | Recommendation |
|---|---|---|
| D1 | Is the docs-only saving (about 2 minutes per PR) worth changing `ci.yml`? | Yes, but low priority. If not, keep the batching rule and close OPEN-22(b). |
| D2 | Docs-only allowlist: `docs/**/*.md` plus root `README.md`, `AGENTS.md`, `CLAUDE.md`, with `openapi.json` always full? | Yes. |
| D3 | Deploy job split: two jobs (`release`, `rollout`, two clicks) or one job as today (one click, order by step)? | Two jobs. It gives the `needs` enforcement you approved. |
| D4 | With `RUN_MIGRATIONS=false`, should the migration step be skipped with a warning while `release` still succeeds? | Yes. |
| D5 | Keep automatic `push: main` deploy out of scope? | Yes. Revisit after several clean supervised deploys. |
| D6 | Drop the `m0/**` push trigger in the same `ci.yml` change (original OPEN-22 (a))? | Yes. |

## E2E placement for the library flow (TEST-13)
Recommendation:
- Keep the Playwright flows (auth and the library) **out of the PR gate**. They need the Firebase Auth Emulator and a seeded database, and the suite is meant to stay small.
- Run them **locally and at release time**, in the trial worktree before the milestone PR, with the result recorded in the traceability table.
- The library flow joins the smoke suite in M2: sign in with the emulator, switch department, list, open a document, `?page=N`, and the forbidden view.
- The deployed smoke (M2-AC16) is a separate, owner-run check and needs the R2 wiring (M2-00c).
- Revisit the PR gate only if a UI regression slips past the component tests.
