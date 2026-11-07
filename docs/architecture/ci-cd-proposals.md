# CI/CD proposals (M2-CI)

Requirements: OPEN-22, OPEN-27, TEST-13, M2-AC18. This note recommends; it decides nothing. No workflow, branch protection or `ci-required` change is made. Any of those needs the user's approval.

## OPEN-22: CI efficiency and change policy
Recommended option:
- **Triggers.** Run `ci` on `pull_request` and on push to `main`. Drop the `m0/**` push trigger, which duplicates the PR run. A branch without a pull request then gets no CI, so a draft PR is how to get checks. This already matches how M2 got its first PostgreSQL 18 run.
- **Docs-only changes.** Keep the full `ci` for every PR. Path-ignoring the workflow cannot work, because a required check that never reports blocks the merge, and `ci-required` treats skipped jobs as failure. If run time matters later, add a `changes` job and let `ci-required` accept the skips that job explains, but only after the user approves the change to `ci-required`.
- **Interim rule.** Batch docs-only edits into one PR per work step or milestone.
- **Push identity.** Use the `BarakTubul` credential. If `git push` returns 403 as `Barak-Horizon`, push with `git -c credential.helper= -c credential.helper='!gh auth git-credential' push`.

What stays unchanged: the six check categories, the `ci-required` aggregate (fails on any failed or cancelled job), and branch protection.

## OPEN-27: automatic deploy after merge
Proposal, for the user to accept, change or reject.

| Part | Proposal |
|---|---|
| Trigger | Keep `workflow_dispatch` as the only trigger until M2 is deployed once and its smoke passes. Then enable `push: main` for the ordinary roll-out job only. |
| Ordinary jobs | Build and roll out the API, Worker and Pages frontend when the commit has a `success` `ci-required`. No approval step. |
| Approval-gated jobs | Production migrations, infrastructure or security configuration, and the document seed stay in jobs bound to the `production` Environment with its required reviewer. |
| WIF conditions | Unchanged: repository, `refs/heads/main`, this workflow file and the Environment named in Terraform. |
| `needs` chain | The ordinary roll-out `needs` the migration job. If the migration job is waiting for approval, the roll-out waits too, so a dependent deploy cannot bypass the gate. A new schema never goes live without the approved migration. |
| Rollback | Revision rollback per `rollback.md`. Automation never rolls back. |

Open point: with `needs` on an approval-gated job, every push that includes a migration waits for the reviewer. Pushes without a migration skip that job and roll out directly. The `RUN_MIGRATIONS` variable in `deploy.yml` already separates the two cases.

## E2E placement for the library flow (TEST-13)
Recommendation:
- Keep the Playwright flows (auth and the library) **out of the PR gate**. They need the Firebase Auth Emulator and a seeded database, and the suite is meant to stay small.
- Run them **locally and at release time**, in the trial worktree before the milestone PR, with the result recorded in the traceability table.
- The library flow joins the smoke suite in M2: sign in with the emulator, switch department, list, open a document, `?page=N`, and the forbidden view.
- The deployed smoke (M2-AC16) is a separate, owner-run check and needs the R2 wiring (M2-00c).
- Revisit the PR gate only if a UI regression slips past the component tests.
