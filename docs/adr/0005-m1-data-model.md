# ADR 0005: M1 data model, dependents of a user, counters

Status: accepted (M1-01). Date: 2026-11-06.

## Decision
- One migration (`0002`), written by the Owner, creates `departments` (seeded, stable uuid5 ids), `users`, `sessions`, `audit_events`, `rate_limit_counters`, `usage_counters`, `ai_usage_daily`. Slices request schema changes through the Owner.
- `users` is keyed by the Firebase uid (`firebase_uid` unique) and has a `kind` of `demo`, `registered` or `admin`, a unique nullable `email`, `last_active_department_id`, `disabled_at` and `converted_at`. There is no password column anywhere.
- **Dependents rule:** every later table that belongs to a user (conversations, messages, ...) references `users.id` with `ON DELETE CASCADE`, stores the department as a column, and never stores the Firebase uid or email. Conversion keeps `users.id`, so history stays attached. Demo cleanup deletes the `users` row and everything cascades. Cleanup re-checks `kind = 'demo'` inside the delete transaction, so a race with conversion never deletes converted data.
- Rate limits and quotas use PostgreSQL counters with atomic upserts: fixed-window rows in `rate_limit_counters` (Demo creation per IP) and per-UTC-day rows in `usage_counters` and `ai_usage_daily`. There is no Redis, and Cloud Run may run two instances.
- Session rows store only `sha256(token)` and a per-session CSRF secret; `expires_at` is absolute.
- Disabling a user through KnowServe sets `users.disabled_at` and revokes that user's sessions (an internal operation, not an endpoint).

## Consequences
- A `ON DELETE CASCADE` dependent can be deleted by cleanup without extra code. Tests use a fixture table with that shape until M2/M4 add the real ones.
- Counters grow slowly; purging old rows is part of the daily maintenance run.
