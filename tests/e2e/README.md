# Auth e2e against the real API

The default `pnpm --filter @knowserve/frontend e2e:auth` run uses a contract-faithful fake API. To run the same flows against the real API and the Firebase Auth Emulator:

1. Auth Emulator on `localhost:9099` (`infra/local/firebase`, project `demo-knowserve`).
2. A **fresh** database (the Demo rate-limit counters persist, so reuse breaks later runs):
   `DROP DATABASE IF EXISTS knowserve_e2e; CREATE DATABASE knowserve_e2e;` then
   `KS_DATABASE_URL=postgresql+asyncpg://…/knowserve_e2e uv run alembic -c packages/backend_core/alembic.ini upgrade head`.
3. The real API, with the emulator host and a Demo limit high enough for the whole run:
   `KS_ENV=local KS_FIREBASE_PROJECT_ID=demo-knowserve KS_FIREBASE_AUTH_EMULATOR_HOST=localhost:9099 KS_DEMO_START_LIMIT=1000 KS_API_ALLOWED_ORIGINS=http://localhost:5199 uv run uvicorn knowserve_api.main:create_app --factory --port 8000`
4. `E2E_REAL_API=1 pnpm --filter @knowserve/frontend e2e:auth`

Two flows stay `fixme` in real mode on purpose: an expired Demo (needs clock control) and the late-verification window (needs a 2-second `KS_AUTH_MAX_AGE_SECONDS`, which would break the other flows). Both are covered by backend integration tests (AUTH-16, AUTH-30).

# Library flow (M2), mocked API

`pnpm --filter @knowserve/frontend e2e:library` runs `library.mocked.spec.ts` in Chromium against a `page.route` fake of the documents API, with a committed seed PDF rendered by the real pdf.js. It needs no Firebase Emulator, no Java and no database. It is not backend evidence and does not test sign-in: real authentication is covered by the M1 auth flows (above) and the backend tests. It stays out of the PR gate (`ci-cd-proposals.md`); run it locally and before the milestone PR.
