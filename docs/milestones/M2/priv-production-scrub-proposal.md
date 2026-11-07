# M2-PRIV: proposed production count and scrub (NOT executed)

Status: proposal for the Owner's approval (plan Q14). Nothing here has been run. No production
database was read or changed by M2-PRIV.

## Why
Before M2-PRIV the code wrote `audit_events.ip` and used the rate-limit key `demo:ip:<address>`.
Production may therefore hold addresses (SEC-18, OPEN-28 Q9). The code no longer writes either.

## Step 1: read-only count (needs approval to run)
Run through the migration job or an owner psql session, in a read-only transaction.

```sql
BEGIN READ ONLY;
SELECT count(*) AS audit_rows_with_ip FROM audit_events WHERE ip IS NOT NULL;
SELECT count(*) AS legacy_counter_rows FROM rate_limit_counters WHERE key LIKE 'demo:ip:%';
ROLLBACK;
```

The result is two counts. Do not print or copy any address.

## Step 2: scrub (needs a separate approval, only if either count is above zero)
Run once in one transaction through the migration job. It deletes no audit rows, only blanks the
column. The old counter rows are short-lived rate windows and are deleted; the new hashed keys
start fresh.

```sql
BEGIN;
UPDATE audit_events SET ip = NULL WHERE ip IS NOT NULL;
DELETE FROM rate_limit_counters WHERE key LIKE 'demo:ip:%';
COMMIT;
```

Re-run the Step 1 counts afterwards; both must be 0.

## Notes
- Effect on users: the next Demo start from each address gets a fresh window, nothing else.
- Old log lines (Cloud Logging) are outside this task. Production logging is not changed here.
- Deploy order: the new image can roll out before or after the scrub; the old image still writes
  addresses, so run the scrub after the new revision serves all traffic.
- Dropping `audit_events.ip` stays a later contract migration owned by the Owner.

## Remaining privacy limitations
- Cloudflare (edge, Pages Function) and Google Cloud (Cloud Run, load balancer, platform logs) process
  and may retain client IPs under their own policies. KnowServe does not claim to remove that.
- While a Demo window is open, the keyed hash `demo:client:<hex>` is stored in `rate_limit_counters`
  so the limit can work. It is pseudonymous (HMAC-SHA256 with a secret pepper), lives for the window
  plus 15 minutes, and is never logged, audited or shown. With the default 1 h window a row lives up
  to about 1 h 15 min.
- Anyone holding both the database and the pepper could test a guessed address against a key.
- Rows are removed on the next Demo start after expiry, and by the Demo cleanup sweep, not by a
  timer, so an idle system keeps its last rows until then.
