# M1 handoff (WF-12), draft

**Resolved (2026-11-08): Demo Cleanup signature defect.** The first scheduled cleanup (2026-11-07 03:00 UTC) was rejected with 401 on all four deliveries; the cause was a schedule destination host that did not match the Worker's `KS_WORKER_PUBLIC_URL` (section 3, "Demo Cleanup defect"). After the schedule was corrected, the scheduled run on 2026-11-08 03:00 UTC authenticated and cleaned up (evidence in section 3). The block is lifted.

**Status (2026-11-06):** M1 is merged (PR #28, `045f463`), deployed to production (`knowserve-m0-spike`) through the `production` GitHub Environment, and closed by the Owner with **one accepted gap**: the Demo to Registered conversion was not run on real Firebase (section 3). The migration ran, the Admin is provisioned, the daily Demo-cleanup schedule exists, and the other real-Firebase checks passed. Specs: `../../backend/auth.md`, `../../frontend/auth.md`, `../../contracts/auth-session.md`, `plan.md`, `tasks.md`, ADRs 0004 to 0006, decisions OPEN-24 to OPEN-26.

## 1. What exists locally
| Area | State |
|---|---|
| Schema | Migration `0002` (users, sessions, departments seed, audit, counters), no password column |
| Session core and exchange | Firebase Admin SDK verifier (emulator-aware, refused in production), 24 h absolute sessions, CSRF + Origin, `POST /v1/auth/session`, `/convert`, `/logout`, `/sessions/revoke-all`, `GET /v1/auth/me`, `disable_user` |
| Demo and departments | `POST /v1/demo/start` (5/h/IP), departments list and switch, last department persisted and restored, Admin guard, idempotent `admin_seed` command |
| Limits | Quota service and global AI guard (20/100/100 per user, 100 global, kill switch), `Retry-After` on 429; chat applies them in M4 |
| Cleanup | `demo_cleanup` and the signed Worker endpoint `POST /internal/maintenance/demo-cleanup`; independent review done and findings fixed |
| Frontend | Login screen (password, Google, Forgot password, Sign up, Try Demo), action pages, reauthentication, linking, Demo to Registered conversion, departments |
| Infra (authored only) | Migration Cloud Run job and secret container, `deploy.yml` migration step, Admin seed job (off), QStash schedule script (dry run), Firebase console checklist; independent review done and findings fixed |

## 2. Evidence run once at the end (local, 2026-11-06)
`ruff format --check` and `ruff check` clean; `pyright` 0 errors; `pytest` **430 passed** (against local PostgreSQL 5433 with pgvector); OpenAPI snapshot in sync; `pnpm -r lint`, `format:check`, `typecheck`, `build` pass; frontend tests **146 passed**; `check:api` in sync; `check_no_secrets` OK; `terraform fmt -check` and `validate` pass. Real-API e2e (`tests/e2e/README.md`): **5 passed, 2 skipped on purpose**, stable on two consecutive runs against the real API, the Firebase Auth Emulator and a fresh database.

## 3. Acceptance criteria by evidence level
**Verified end to end locally (real frontend + real API + Auth Emulator, plus backend tests)**
- AC01 password signup, verification in a fresh browser, login, logout; unverified gets no session.
- AC03 Google sign-in through the emulator popup produces the same session type.
- AC08 department selection and restore at the next login (first-login 409 and isolation by integration tests).
- AC14 Try Demo through Firebase Anonymous Authentication, Demo mode and reload.
- AC15 Demo to Registered conversion through the real UI and API: same internal user id, now Registered, same department. A Demo cannot take an email that already has an account (no merge, history not moved).

**Covered by backend integration tests only (emulator-style tokens through the real verifier, real PostgreSQL)**
- AC04 token rules (forged, expired, audience, stale, wrong provider, key outage fails closed, emulator refused in production).
- AC05 account-conflict rules (second uid with a used email refused, no merge); reset and Google-on-existing-password-account linking are component-tested only.
- AC06 no tokens, cookies or CSRF values in logs or audit.
- AC07 CSRF and Origin on every unsafe route (route-walk test over the auth, demo and department unsafe routes; spike routes are off by default); deploy smoke still needed.
- AC09 Admin guard, no escalation from email, provider or request fields; one Admin only.
- AC10 error envelope; AC13 24 h absolute sessions, no extension, revoke-all and disable.
- AC15 dependents: preservation of representative dependent rows in two departments, idempotence, lost-call recovery, conversion versus cleanup race.
- AC16 cleanup logic, endpoint signature rules and the foreign-key cascade guard (the QStash schedule does not exist).
- AC17 quotas, global guard and kill switch as a mechanism; **chat-level evidence is an M4 criterion** (CHAT-18, CHAT-19), as is real chat-history preservation.
- Time-dependent cases (expired Demo, stale sign-in window) are intentionally not in e2e.

**Verified on production (2026-11-06)**
- Cutover and deploy: the deploy workflow targets the `production` Environment (PR #27); `auth-check` passed (run 42255581776: login works, the deployer cannot read secrets, the IAM policy or `migration-database-url`, and can see the migration job); `deploy` passed every step (run 42257551803): images built and pushed, **migration job run**, Cloud Run rolled, frontend deployed, API status through the Pages proxy, direct Cloud Run access denied, worker readiness and the deployed Playwright smoke (AC11, AC12).
- Database: `alembic_version` is `0002`; the new tables exist; the five departments are seeded; `neondb_owner` owns every table. The runtime role `ks_runtime` (created by SQL, no privileged memberships) has SELECT/INSERT/UPDATE/DELETE on all tables except `alembic_version`, no TRUNCATE, and was tested by a real pooled login: DML in a rolled-back transaction passed; CREATE TABLE, ALTER and reading `alembic_version` were denied. `database-url` version 2 is the pooled `ks_runtime` URL (version 1, `neondb_owner`, is preserved); `migration-database-url` holds the direct `neondb_owner` URL. The live API revision `knowserve-api-00007` runs on the runtime credential, and `/health/live` and `/health/ready` return 200.
- Admin (AC09): one `admin` row bound to the Firebase uid, provisioned once through the Cloud Run job `knowserve-admin-seed` under the runtime identity (outcome `promoted`, audit event `admin.provisioned`). The Owner confirmed `/v1/admin/ping` returns 200 for the Admin and 403 for another account.
- Firebase (configuration read through the Identity Toolkit API): Email/Password, Google and Anonymous enabled; password policy enforced (minimum 8, no composition rules) and confirmed by the Owner's rejection of a short password (AC02); email enumeration protection on; `knowserve-m0-spike.pages.dev` is an authorized domain; Firebase's default mail handler and sender are in use. The Owner confirmed Try Demo, Google sign-in, password sign-in and sign-out, signup verification mail and password reset on the live site (AC01, AC03, AC14).
- Finding: Firebase replaced the Admin's unverified console-created password credential when the same email signed in with Google (its built-in protection), so the Admin account is Google-only and verified. This is allowed (O1); password sign-in for the Admin can be added later.
- Cleanup endpoint: unsigned requests to `/internal/maintenance/demo-cleanup` are rejected with 401, with and without a body (AC16, SEC-14). The daily QStash schedule `knowserve-demo-cleanup` (`CRON_TZ=UTC 0 3 * * *`, POST, no body, 3 retries) was created on 2026-11-06 and read back; the first scheduled delivery (03:00 UTC) has not been observed yet. The one-time Admin seed job was removed after use (Terraform apply: 1 destroyed), and Terraform matches the configuration.

**Demo Cleanup defect (2026-11-07), resolved 2026-11-08**
- Verification (2026-11-08): the scheduled run at 03:00 UTC authenticated. The Worker log shows the first attempt (03:00:05) aborted with 500 by Cloud Run after waiting for an instance during a cold start, so the app never ran. QStash retried, and the retry returned 200 at 03:00:27 with the log lines `audit event` and `demo cleanup run` at 03:00:28. The audit row `demo.cleanup.run` records `batches: 0`, `deleted_users: 0`, `failed_batches: 0`. No Demo account had reached its limit yet. The same evidence is in `../M2/handoff.md`.
- Symptom: four QStash deliveries (03:00:00, 03:00:22, 03:02:54, 03:30:14 UTC) reached the Worker and all returned 401, log line `rejected maintenance delivery with invalid signature`. No cleanup ran.
- Root cause: the schedule destination was `https://knowserve-worker-ql7pu53csa-ew.a.run.app/internal/maintenance/demo-cleanup`, but the Worker's `KS_WORKER_PUBLIC_URL` (revision `knowserve-worker-00006-sk8`) is `https://knowserve-worker-866929656529.europe-west1.run.app`. QStash signs the destination it called into the `sub` claim; the Worker requires `sub` to equal its configured URL plus the path, so the destination check failed. Both hosts are aliases of the same Cloud Run service, which is why requests still arrived. The signing keys were not the cause: they have one enabled version each (created 2026-10-31), and the corrected delivery verified with them. The error log does not say which check failed (deferred improvement below).
- Fix (cloud only, Owner approved in chat, 2026-11-07 ~09:06 UTC): `infra/qstash/demo-cleanup-schedule.sh create` was re-run with `WORKER_PUBLIC_URL=https://knowserve-worker-866929656529.europe-west1.run.app` and the same schedule id, which updates the schedule in place (no delete, so no gap and no duplicate). The listing afterwards shows exactly one schedule `knowserve-demo-cleanup`, the corrected destination, `CRON_TZ=UTC 0 3 * * *`, POST, 3 retries, not paused. No secret, Worker configuration or application code changed.
- Manual verification: one test message published through QStash to the corrected destination (09:07:03 UTC, no retries) returned 200 at 09:07:04; the Worker logged `demo cleanup run` with `deleted_users` 0, `failed_batches` 0, `batches` 0 (nothing was expired, so this proves authentication and a clean run, not a deletion).
- Still required before closing: the next scheduled run (2026-11-08 03:00 UTC) accepted with 200 and a `demo cleanup run` log line, recorded here.
- Deferred follow-ups (Owner asked to wait): distinct signature failure reasons in the Worker log (destination mismatch, bad signature, body hash), regression tests for a validly signed but wrong-host delivery, and a check in the script and README that the destination equals the deployed `KS_WORKER_PUBLIC_URL` (use the Cloud Run env value, not the service URL).

**Real-Firebase checks run by the Owner on the live site (2026-11-06)**
- Passed: sign out everywhere (sessions revoked, the other browser signed out), Google sign-in on an email that already has a password account (link prompt, no silent merge), and the Continue button on Firebase's hosted verification and reset pages returning to `/login` (AC05, AC07).

**Accepted gap (Owner decision, 2026-11-06)**
- AC15 Demo to Registered conversion was **not run on real Firebase**. The Owner closed M1 without it. What covers it instead: the backend integration tests (same `users.id` and uid, fixture records in two departments, lost-call recovery, the cleanup race) and the real-API end-to-end flow against the Firebase Auth Emulator. What stays unproven on real Firebase is that the token's provider claim becomes `password` after linking, as it did on the emulator. If conversion fails on production, `/v1/auth/convert` fails closed (401) and the Demo session stays valid; the lost-call path (a normal sign-in completes the conversion) still works.

**Still to observe**
- The first successful scheduled Demo cleanup is evidenced (2026-11-08 03:00 UTC, see "Demo Cleanup defect").

## 4. Unresolved failures and risks
- No failing check at the time of writing. The earlier real-API e2e failures were caused by a stale API process on port 8000 and the persistent 5-per-hour Demo counters, not by product defects; the e2e README records the isolation rules.
- **Independent reviews done, none with Critical or High findings:** M1-02a, M1-02b, M1-07, M1-11 and the final cross-cutting pass M1-08 (go for opening the Draft PR). M1-08 Mediums fixed: a database outage now returns 503 (SEC-13, tests added); the false 429 on `/v1/auth/session` was removed from the contract; static tests for AUTH-18 and AUTH-29 added; the Admin provisioning order and the unverified-email pitfall are in the infra README. Still open from that review: AUTH-19 (deploy smoke) and real Google OAuth for AUTH-31; `POST /v1/demo/start` does not revoke a session carried by the incoming cookie (not an escalation); audit rows store client IPs (confirm the retention policy); the review checked requirement ids by file-level search, not test by test.
- **Email action URL (unresolved Firebase Console restriction):** the Console rejected the custom Action URL `https://knowserve-m0-spike.pages.dev/auth/action` ("An error occurred updating action URL"; the cause is unknown). Workaround implemented locally: Firebase's default action handler stays in use, and every verification and reset email is sent with a continue URL built from the running origin (`<origin>/login`), covered by `firebase-gateway.test.ts`. The KnowServe `/auth/action` page is kept but unused in production. **The real-Firebase smoke must verify:** the verification email completes successfully; the password reset completes successfully; the Continue action returns the user to KnowServe's login page. If Firebase's hosted page does not show Continue or does not honor the continue URL, report it; do not add infrastructure.
- **Admin first sign-in:** an Admin created with "Add user" in the Firebase console has an unverified email, and KnowServe returns 403 `EMAIL_NOT_VERIFIED` for it. Verify the email (console mail or a Google sign-in) before the first sign-in.
- **Owner decisions (2026-11-06):** the deployer runs the migration job under the GitHub `production` approval gate and the restricted WIF trust, accepted as proportionate on the condition that the production cutover is completed and verified; the Admin seed job uses the DML-only runtime identity (API service account, `database-url`), not the DDL credential (done in `gcp_migration_job.tf`). Still open: React Hook Form and Zod are not used in the frontend (FE-ARCH-09).
- **Known gaps (documented):** sessions are not ended by an external Firebase password reset or disable; signup reveals an existing email; the password blocklist is dropped; `/v1/auth/session` converts a Demo row past 24 h until cleanup; `users.email` is not refreshed from a changed Firebase email; `display_name` is not length-capped; audit IP differs slightly between auth and demo routes; keep Firebase's "link accounts that use the same email" setting off or document it.
- Docker's engine did not start on this machine, so tests ran on a local PostgreSQL with pgvector and the emulator through `npx`; compose services are unexercised here. CI runs the repo's own database service.
- The production cutover (spike to production Environment) runs in its own session; this handoff does not depend on it.

## 5. Next steps
1. Done (2026-11-08): the scheduled Demo cleanup succeeded and the BLOCKED banner is removed.
2. Run the Demo to Registered conversion on real Firebase when convenient, to close the accepted gap.
3. Decide whether to add password sign-in for the Admin, and close PR #26 (superseded by #28).
4. Carry the M4 criteria that complete M1 evidence (CHAT-18, CHAT-19) into the M4 plan.
