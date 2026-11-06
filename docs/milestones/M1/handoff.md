# M1 handoff (WF-12), draft

**Status (2026-11-06):** M1 is merged (PR #28, `045f463`) and **deployed to production** (`knowserve-m0-spike`) through the `production` GitHub Environment. The migration ran, the Admin is provisioned and the main auth flows were checked by the Owner on the live site. M1 is **not yet complete**: the daily Demo-cleanup schedule, removal of the one-time Admin seed job, and part of the real-Firebase smoke are open (section 3, last block). Specs: `../../backend/auth.md`, `../../frontend/auth.md`, `../../contracts/auth-session.md`, `plan.md`, `tasks.md`, ADRs 0004 to 0006, decisions OPEN-24 to OPEN-26.

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
- Cleanup endpoint: unsigned requests to `/internal/maintenance/demo-cleanup` are rejected with 401, with and without a body (AC16, SEC-14). QStash accepts the token in the EU region and lists no schedules yet.

**Remaining real-Firebase / cloud checks (not done)**
- AC15 Demo to Registered conversion on real Firebase (the provider claim after linking was seen only on the emulator), "sign out everywhere", and the Google-on-existing-password-email linking prompt (AC05).
- The Continue button on Firebase's hosted verification and reset pages returning to `/login` (the Owner reported the mail flows work; the return link was not separately confirmed).
- AC16 the daily QStash cleanup schedule: create it (needs approval), then confirm one scheduled delivery is accepted.
- Remove the one-time Admin seed job (set `enable_admin_seed_job = false`, plan, apply). Until then it is a standing job with a DML-only credential and no execution rights for CI.

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
1. Remove the Admin seed job, then create the QStash daily cleanup schedule (each needs Owner approval).
2. Finish the remaining real-Firebase checks above and fill the results into the traceability table.
3. Decide whether to add password sign-in for the Admin, and close PR #26 (superseded).
4. Record the M4 criteria that complete M1 evidence (CHAT-18, CHAT-19) when M4 starts.
