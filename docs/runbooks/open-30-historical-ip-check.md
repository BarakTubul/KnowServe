# OPEN-30: check production for historical client IPs

Status: prepared, **not run**. No production query, count or scrub has been authorized yet.
Related: OPEN-30 in `docs/open-decisions.md`, `docs/milestones/M2/handoff.md`, M2-PRIV in
`docs/milestones/M2/tasks.md`, and the earlier proposal in
`docs/milestones/M2/priv-production-scrub-proposal.md` (this runbook supersedes its commands).

## Why this exists
Before M2-PRIV the code wrote client addresses in two places:

| Place | What was written | Written by |
|---|---|---|
| `audit_events.ip` (text, nullable) | the client address | `audit.record(..., ip=...)` in the auth and Demo routes |
| `rate_limit_counters.key` (text, part of the primary key) | `demo:ip:<address>` | the Demo start rate limit |

M2-PRIV (deployed with M2) stopped both. `audit.record` has no `ip` parameter, so `audit_events.ip`
stays NULL, and the limiter key is now `demo:client:<HMAC-SHA256 hex>`. Rows written by older
revisions may still hold addresses. Two things limit how much is left:

- `audit_events.ip` is never cleaned up automatically, so any old value is still there.
- Old `demo:ip:` counters may already be gone: the daily Demo cleanup deletes counter rows whose
  window ended more than 15 minutes ago. Expect the counter count to be 0 or small.

Cloudflare and Google Cloud may process addresses under their own policies. This runbook covers
only the application database. Old Cloud Logging lines are out of scope.

## Rules for running it
- Each stage below needs its own explicit yes from the user. Count first, scrub only after the user
  has seen the counts.
- Never print row contents or address values. The count SQL returns only integers.
- Never print, echo or save the connection string. Do not use `set -x`, do not echo the URL
  variable, and do not write psql output that could include the URL into a file in the repo.
- Nothing in this runbook puts a value into Terraform state or the repo.

## Stage 1: read-only count (needs the user's yes)

### SQL
Save as `count.sql` in a scratch directory outside the repo, or pass it with `-c`. It runs in a
read-only transaction and returns three integers.

```sql
BEGIN READ ONLY;
SELECT count(*) AS audit_rows_with_ip
  FROM audit_events WHERE ip IS NOT NULL;
SELECT count(*) AS legacy_counter_rows
  FROM rate_limit_counters WHERE key LIKE 'demo:ip:%';
SELECT count(*) AS audit_details_with_ip_key
  FROM audit_events WHERE details ?| ARRAY['ip', 'client_ip'];
ROLLBACK;
```

The third query is a safety check that no address ended up inside the JSON `details` column under
an obvious key. `details` goes through log redaction before it is stored, so 0 is expected. It
counts rows only and never selects the value.

`ks_runtime` has SELECT on both tables, so it is enough. `neondb_owner` also works but is not
needed for the count. Prefer `ks_runtime`.

### How to connect without printing credentials
The pooled `ks_runtime` URL is the Secret Manager secret `database-url` in project
`knowserve-m0-spike` (version 2 at the M1 cutover). The `neondb_owner` direct URL is
`migration-database-url`. Run from a shell where the user is logged in to `gcloud`. The URL is
held only in a shell variable.

```bash
# Read the secret into a variable. Nothing is printed.
DB_URL="$(gcloud secrets versions access latest --secret=database-url --project=knowserve-m0-spike)"
# The app URL may carry an async driver prefix that psql does not accept; strip it.
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql://}"

# Run the count. -X skips psqlrc, -A -t gives plain values, errors stop the run.
psql "$DB_URL" -X -A -t -v ON_ERROR_STOP=1 -f count.sql

unset DB_URL
```

If the URL uses `ssl=require` instead of `sslmode=require`, change that query parameter in the
variable before running psql. Do not echo the variable to check it.

If `psql` is not installed, run the same SQL with a throwaway `uv run python` snippet using
`asyncpg` that reads the URL from the environment and prints only the three integers.

To use `neondb_owner` instead, replace `database-url` with `migration-database-url`.

### Expected result shape
Three integers, in this order (with `-A -t` the `BEGIN` and `ROLLBACK` tags are also printed):

```
<audit_rows_with_ip>
<legacy_counter_rows>
<audit_details_with_ip_key>
```

| Result | Meaning | Next step |
|---|---|---|
| all `0` | nothing to scrub; OPEN-30 can be closed with these counts as evidence | update `open-decisions.md` and the M2 handoff |
| first or second above `0` | historical addresses exist | report the counts to the user and ask about Stage 2 |
| third above `0` | an address-like key exists in `details` | stop and escalate to the Owner; the scrub below does not cover it |

Record the three numbers and the UTC time in the M2 handoff. Do not record any address.

## Stage 2: scrub (NOT APPROVED, proposal only)

**Do not run any of this until the user has seen the Stage 1 counts and given a separate, explicit
yes.** It changes production data.

What would change:
- `audit_events.ip` set to NULL on rows that have a value. No audit row is deleted and no other
  column changes.
- `rate_limit_counters` rows with a key starting `demo:ip:` are deleted. They are short rate
  windows; the next Demo start from each address gets a fresh window and nothing else changes.

Preconditions:
1. The new image (M2-PRIV) serves 100 percent of traffic. An old revision would write addresses
   again. Check the live revision first.
2. Run as `neondb_owner` (`migration-database-url`), so the runtime role is not used for one-off
   data fixes.
3. The Stage 1 counts are recorded.

### Backup (before the scrub)
Create a Neon branch (point-in-time copy) of the production branch from the Neon console or CLI
and note its name and time. This keeps the old addresses in a second place, so delete that branch
as soon as the scrub is verified, or after a short window the user agrees to. Do not export the
rows to a file.

### SQL (single transaction)
```sql
BEGIN;
-- Expect UPDATE <audit_rows_with_ip> and DELETE <legacy_counter_rows>.
UPDATE audit_events SET ip = NULL WHERE ip IS NOT NULL;
DELETE FROM rate_limit_counters WHERE key LIKE 'demo:ip:%';
-- Check inside the transaction before committing; both must be 0.
SELECT count(*) FROM audit_events WHERE ip IS NOT NULL;
SELECT count(*) FROM rate_limit_counters WHERE key LIKE 'demo:ip:%';
-- If the row counts match Stage 1 and both checks are 0: COMMIT; otherwise ROLLBACK;
```
Run it interactively so the checks can be read before typing `COMMIT;`. If the UPDATE or DELETE
row counts differ from Stage 1, run `ROLLBACK;` and report.

### Rollback
- Before COMMIT: `ROLLBACK;` undoes everything.
- After COMMIT: the old values exist only in the Neon backup branch. Restoring them puts the
  addresses back, so do it only if the scrub changed something it should not have. Copy the
  affected rows from the backup branch in a new reviewed transaction; do not restore the whole
  database over newer data.

### Verify
Re-run Stage 1. All three numbers must be 0. Then delete the backup branch and record the date,
the counts and the branch deletion in the M2 handoff. The Stage 2 approval is separate from the
Stage 1 approval and covers only this SQL.

### Not covered
- Dropping the `audit_events.ip` column (a contract migration owned by the Owner).
- Cloud Logging and Cloudflare or Google Cloud platform logs.
