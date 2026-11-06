# M1 handoff (WF-12), draft

**Status (2026-11-06):** all M1 code is implemented and integrated **locally** on `m1/integration`. Nothing is pushed, deployed or applied to the cloud, and the milestone PR is not opened. M1 is **not** complete: the final independent review (M1-08), the cloud setup and the real-Firebase smoke are open (see sections 3 and 4). Specs: `../../backend/auth.md`, `../../frontend/auth.md`, `../../contracts/auth-session.md`, `plan.md`, `tasks.md`, ADRs 0004 to 0006, decisions OPEN-24 to OPEN-26.

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
- AC07 CSRF and Origin on every unsafe route (route-walk test); deploy smoke still needed.
- AC09 Admin guard, no escalation from email, provider or request fields; one Admin only.
- AC10 error envelope; AC13 24 h absolute sessions, no extension, revoke-all and disable.
- AC15 dependents: preservation of representative dependent rows in two departments, idempotence, lost-call recovery, conversion versus cleanup race.
- AC16 cleanup logic, endpoint signature rules and the foreign-key cascade guard (the QStash schedule does not exist).
- AC17 quotas, global guard and kill switch as a mechanism; **chat-level evidence is an M4 criterion** (CHAT-18, CHAT-19), as is real chat-history preservation.
- Time-dependent cases (expired Demo, stale sign-in window) are intentionally not in e2e.

**Remaining real-Firebase / cloud checks (not done; need the Owner)**
- AC02 Firebase password policy (minimum 8, no composition rules, `Require` mode) verified in the real console (N3); if it needs Identity Platform, report and ask.
- AC03 real Google OAuth; AC05 verification and reset mail delivery and the "account exists" linking path on real Firebase; behavior of `/v1/auth/convert` after real credential linking (emulator showed the provider becomes `password`).
- AC11 migration job applied and run (needs the second Neon role and secrets); AC12 deployed smoke through the Pages proxy; AC16 QStash schedule creation after confirming availability and quotas; Admin account creation and provisioning; the first production deploy through the `production` environment.

## 4. Unresolved failures and risks
- No failing check at the time of writing. The earlier real-API e2e failures were caused by a stale API process on port 8000 and the persistent 5-per-hour Demo counters, not by product defects; the e2e README records the isolation rules.
- **M1-08 final independent cross-cutting review has not been run.** Independent reviews done: M1-02a, M1-02b, M1-07 and M1-11 (no Critical or High findings; fixes applied).
- **Owner decisions (2026-11-06):** the deployer runs the migration job under the GitHub `production` approval gate and the restricted WIF trust, accepted as proportionate on the condition that the production cutover is completed and verified; the Admin seed job uses the DML-only runtime identity (API service account, `database-url`), not the DDL credential (done in `gcp_migration_job.tf`). Still open: React Hook Form and Zod are not used in the frontend (FE-ARCH-09).
- **Known gaps (documented):** sessions are not ended by an external Firebase password reset or disable; signup reveals an existing email; the password blocklist is dropped; `/v1/auth/session` converts a Demo row past 24 h until cleanup; `users.email` is not refreshed from a changed Firebase email; `display_name` is not length-capped; audit IP differs slightly between auth and demo routes; keep Firebase's "link accounts that use the same email" setting off or document it.
- Docker's engine did not start on this machine, so tests ran on a local PostgreSQL with pgvector and the emulator through `npx`; compose services are unexercised here. CI runs the repo's own database service.
- The production cutover (spike to production Environment) runs in its own session; this handoff does not depend on it.

## 5. Next steps
1. Run the M1-08 independent review on the integrated branch; fix findings.
2. Owner actions in order: Firebase console setup and the password-policy check, `production` Environment secrets, migration job apply and Neon roles, Admin account, QStash schedule, first deploy.
3. Real-Firebase smoke (Google, mail, convert), then fill the evidence into the traceability table.
4. Open the milestone PR as a Draft (needs push approval), mark ready for approval after step 3.
