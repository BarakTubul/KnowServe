# Daily Demo cleanup schedule (QStash)

> **REQUIRES OWNER APPROVAL.** Creating the schedule is a cloud action (OPEN-26 N4, ADR 0006). Nothing in this repository creates it. Do not run `demo-cleanup-schedule.sh` with `QSTASH_SEND=yes` until the Owner has (1) confirmed schedule availability and quotas (below) and (2) approved the creation in chat. No Cloud Scheduler is used.

One QStash schedule calls `POST <worker public url>/internal/maintenance/demo-cleanup` once a day, with no body and no parameters. The Worker verifies the QStash signature, then runs one fixed, bounded, idempotent cleanup (`docs/contracts/jobs-outbox.md`, AUTH-35). The schedule is not Terraform-managed: this repository authors no Upstash provider resource, so the definition is a reviewed script.

Facts about the QStash REST API below are from general knowledge of Upstash's documentation and are **UNVERIFIED** against the current docs and the real account. Check them in step 1 before relying on them.

## What is created
| Item | Value |
|---|---|
| Destination | `${KS_WORKER_PUBLIC_URL}/internal/maintenance/demo-cleanup`, exactly the Terraform variable `worker_public_url`, which is the Worker's `KS_WORKER_PUBLIC_URL` (QStash signs for this URL and the Worker verifies it) |
| Method, body | `POST`, none |
| Cron | `CRON_TZ=UTC 0 3 * * *` (03:00 UTC daily, a quiet hour; change `SCHEDULE_CRON` if the Owner prefers another) |
| Schedule id | `knowserve-demo-cleanup` (`Upstash-Schedule-Id`, so a second `create` updates the same schedule instead of adding another; verify this behaviour in step 3) |
| Retries, timeout | QStash defaults. The operation is idempotent, so a retry is harmless |
| Region | The token and `KS_QSTASH_URL` must be the same region (EU: `https://qstash-eu-central-1.upstash.io`) |

## Runbook (Owner-run, after approval)
The script is a dry run unless `QSTASH_SEND=yes`; `create` and `delete` additionally need `OWNER_APPROVED=yes`. The token is read from `QSTASH_TOKEN` in the environment only (never an argument, never printed, passed to curl on stdin). Do not put it in shell history: `read -rs QSTASH_TOKEN; export QSTASH_TOKEN`.

```bash
export KS_QSTASH_URL=https://qstash-eu-central-1.upstash.io     # your region
export WORKER_PUBLIC_URL=https://<the Worker's KS_WORKER_PUBLIC_URL>   # no trailing slash

# 0. Review exactly what would be sent (nothing leaves the machine).
bash infra/qstash/demo-cleanup-schedule.sh create
```

1. **Confirm availability and quotas first (read only).**
   - In the Upstash console, open the QStash plan page and note: the allowed number of schedules, the daily message limit, and the message retention. One daily schedule costs one message per day plus retries; compare that with the existing M0 job traffic and the plan limit. Record the numbers and the date in the M1 handoff. State "not verified" if the console does not show them.
   - List the existing schedules (expect none for KnowServe): `QSTASH_SEND=yes bash infra/qstash/demo-cleanup-schedule.sh check`
2. **Confirm the endpoint exists on the deployed Worker** (it ships with M1-11). An unsigned call must be rejected, not 404:
   `curl -s -o /dev/null -w '%{http_code}\n' -X POST "$WORKER_PUBLIC_URL/internal/maintenance/demo-cleanup"` should print `401` or `403`. A `404` means the Worker revision does not carry the endpoint yet: stop.
3. **Create** (after approval): `QSTASH_SEND=yes OWNER_APPROVED=yes bash infra/qstash/demo-cleanup-schedule.sh create`. Expect a JSON body with the schedule id. Then `... show` and `... check`: exactly one schedule for this destination, cron as above.
4. **Evidence:** the schedule listing (token not visible), the first delivery in the Upstash log (status 200), and the Worker log line with counts only. A manual first run from the Upstash console is allowed once the schedule exists.
5. **Remove** (only if the Owner asks): `QSTASH_SEND=yes OWNER_APPROVED=yes bash infra/qstash/demo-cleanup-schedule.sh delete`.

## Not in scope
- No Cloud Scheduler job and no Terraform resource for this schedule.
- No other maintenance route and no caller-controlled parameter (ADR 0006).
- The Upstash token is never stored in the repository, Terraform or GitHub. It is the same value as Secret Manager `qstash-token` and is read from the Owner's console when needed.
