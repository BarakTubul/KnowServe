# M3 local real-API trial (CP6)

One browser run of the Admin screens against the real API, the real Worker, a real PostgreSQL and the Firebase Auth Emulator. Only the queue is replaced: `local_qstash.py` accepts the API's publish call and delivers the signed request to the Worker. Object storage is a local folder and embeddings come from the fake provider, so nothing leaves the machine. It checks the wiring (Vite proxy, cookies and CSRF, multipart and `Idempotency-Key`, the status stream, the Admin screens). The behaviour is covered by the backend tests.

Run it once before the milestone PR. Local only.

1. Database: `docker exec knowserve-db-1 psql -U knowserve -d postgres -c "CREATE DATABASE knowserve_trial"`, then `uv run alembic -c packages/backend_core/alembic.ini upgrade head` with `KS_DATABASE_URL` pointing at it.
2. Auth Emulator on `localhost:9099` (project `demo-knowserve`). If `docker compose up -d firebase-auth` exits with "Unable to obtain permissions for firebase-debug.log", the read-only mount is the cause: run the same image with a writable copy of `infra/local/firebase`.
3. Create the Admin account in the emulator (email and password, verified), then provision it with `KS_ADMIN_FIREBASE_UID=<uid> KS_ADMIN_EMAIL=<email> uv run python -m knowserve_api.admin_seed`. Sign-in alone makes a regular user.
4. Environment for the three Python processes (local-only values): `KS_ENV=local`, `KS_DATABASE_URL`, `KS_OBJECT_STORE=filesystem` with one `KS_OBJECT_STORE_PATH`, `KS_EMBEDDING_PROVIDER=fake`, `KS_QSTASH_URL=http://127.0.0.1:8090`, `KS_QSTASH_TOKEN=local`, the two `KS_QSTASH_*_SIGNING_KEY` values from `.env.example`, `KS_WORKER_PUBLIC_URL=http://localhost:8001`, `KS_FIREBASE_PROJECT_ID=demo-knowserve`, `KS_FIREBASE_AUTH_EMULATOR_HOST=localhost:9099`, `KS_API_ALLOWED_ORIGINS=http://localhost:5199`, `KS_DEMO_START_LIMIT=1000`, `KS_IP_HASH_PEPPER`.
5. Start `uv run python tests/trial/local_qstash.py` (8090), `uv run uvicorn knowserve_worker.main:create_app --factory --port 8001` and `uv run uvicorn knowserve_api.main:create_app --factory --port 8000`.
6. `E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... pnpm --filter @knowserve/frontend e2e:trial` (Vite starts on 5199 through the Playwright config).

Result of the M3 run: `docs/milestones/M3/tasks.md`.
