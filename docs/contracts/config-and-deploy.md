# Configuration and deployment interface (M0)

Requirements: ARCH-12, INFRA-01, INFRA-04..07, STACK-35, STACK-36.

## Configuration keys
All keys use the `KS_` prefix, are read by `knowserve_core.settings.Settings`, and appear in `.env.example` with placeholders. `.env` is git-ignored. Local test secrets contain `local-only` and `not-a-secret` so they cannot be mistaken for real ones.

| Key | Used by | Notes |
|---|---|---|
| `KS_ENV` | all | `local`, `ci` or `production` |
| `KS_LOG_LEVEL` | all | default `INFO` |
| `KS_DATABASE_URL` | API, Worker, migrations | `postgresql+asyncpg://…`. A plain `postgresql://…?sslmode=require&channel_binding=require` URL (Neon style) is normalized automatically (`sslmode`→`ssl`, `channel_binding` dropped). Use Neon's **direct** host for migrations and the **pooled** (`-pooler`) host for API/Worker runtime; the engine then disables asyncpg's prepared-statement cache. Only `KS_`-prefixed keys are read: plain `DATABASE_URL` / `DATABASE_URL_POOLED` in a local `.env` are ignored until copied into `KS_DATABASE_URL`. |
| `KS_TEST_DATABASE_URL` | tests only | disposable database whose schema is dropped and recreated |
| `KS_API_ALLOWED_ORIGINS` | API | comma-separated explicit origins; in production the single `pages.dev` app origin (used by the Origin check) |
| `KS_PROXY_SHARED_SECRET` | API | secret shared with the Pages Function; required when `KS_ENV=production`; when set the API rejects requests without `X-KS-Proxy-Secret` except `/health/*` (`proxy.md`) |
| `KS_ENABLE_SPIKE_ENDPOINTS` | API | default `false` (M0-08 only) |
| `KS_QSTASH_URL`, `KS_QSTASH_TOKEN` | API, Worker (publish) | token is a secret. The URL is region specific (EU: `https://qstash-eu-central-1.upstash.io`); the default is the US endpoint and rejects EU tokens. Upstash console names `QSTASH_*` are not read: copy them into the `KS_` keys. |
| `KS_QSTASH_CURRENT_SIGNING_KEY`, `KS_QSTASH_NEXT_SIGNING_KEY` | Worker (verify) | secrets |
| `KS_WORKER_PUBLIC_URL` | publisher | destination QStash calls, path `/internal/jobs/run` is appended |
| `KS_ENABLE_RECOVERY_DISPATCHER` | Worker | default `false`: `/internal/outbox/dispatch` is not mounted (404). Optional scheduled recovery only; not required in M0 |
| `KS_DISPATCHER_OIDC_AUDIENCE`, `KS_DISPATCHER_OIDC_SERVICE_ACCOUNT` | Worker | production dispatcher authentication; required **only** when `KS_ENABLE_RECOVERY_DISPATCHER=true`. No longer required for the Worker to start in production |
| `KS_DISPATCHER_LOCAL_TOKEN` | Worker | local/ci only; the settings validator rejects it when `KS_ENV=production` |
| `KS_OUTBOX_LEASE_SECONDS`, `KS_OUTBOX_BATCH_SIZE`, `KS_JOB_LEASE_SECONDS` | Worker/core | defaults 60 / 20 / 120 (`KS_OUTBOX_BATCH_SIZE` matters only for the optional batch dispatcher) |
| `KS_JOB_MAX_ATTEMPTS` | Worker | default `4` total processing attempts; the job is then `failed` (ING-16). Reconciliation with QStash retry behaviour is UNVERIFIED |
| `KS_STUCK_AFTER_SECONDS` | API/core | default `900`: a published `queued` job older than this is `queued_stuck` |
| `KS_PUBLISH_GRACE_SECONDS` | API/core | default `120`: a `pending` outbox row without error older than this is `unpublished_stuck` |
| `KS_ENABLE_SPIKE_JOB_OPS` | API | default `false`. Mounts the spike-only operator routes `/internal/spike/jobs` only when `KS_SPIKE_OPERATOR_EMAILS` and `KS_SPIKE_OIDC_AUDIENCE` are also set; otherwise 404 |
| `KS_SPIKE_OPERATOR_EMAILS` | API | comma list of operator Google account emails (non-secret allow-list); supplied in git-ignored local config, never committed |
| `KS_SPIKE_OIDC_AUDIENCE` | API | audience the operator's Google OIDC ID token must carry (Terraform sets it to the API origin) |
| `KS_ENABLE_SPIKE_FAILURE_HOOKS` | API | default `false`; test-only `skip_publish` and job type `always_fail`, additionally require `KS_ENABLE_SPIKE_JOB_OPS=true`. Set only in the isolated spike environment |
| `VITE_API_BASE_URL` | Frontend | optional; defaults to `/api` (same-origin proxy); no secrets in `VITE_*` |

Production values come from Google Secret Manager through per-service service accounts. Terraform creates secret *containers* and access bindings only; values are entered by the user and never enter Terraform state.

## Local conventions
- Python: `uv sync --frozen`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pyright`, `uv run pytest`.
- Frontend: `pnpm install --frozen-lockfile`, then `pnpm -r lint`, `pnpm -r typecheck`, `pnpm -r test`, `pnpm -r build`.
- Database for tests and local runs: `docker compose up -d db` (host port 5433, local-only credentials). The full stack: `docker compose up --build`.
- Ports: frontend 5173, API 8000, Worker 8001, database 5433.
- Lockfiles `uv.lock` and `pnpm-lock.yaml` are committed. Dependency additions are announced to the Owner, who re-locks at integration.

## Deployment interface
| Item | Value |
|---|---|
| Images | `api` built from `apps/api/Dockerfile`, `worker` from `apps/worker/Dockerfile`; build context is the repository root; both run as non-root and listen on `$PORT` (default 8000 / 8001) |
| Cloud Run services | `knowserve-api`, `knowserve-worker` (region `europe-west1`; min instances 0, max instances 2 each) |
| Migrations | run by the deploy workflow with `alembic -c packages/backend_core/alembic.ini upgrade head` before traffic shifts; never at service start |
| Health | liveness `/health/live`, readiness `/health/ready` on both services |
| Smoke entry points | `GET <pages-url>/api/v1/status` (through the proxy), a direct `GET <api>/v1/status` that must return 403, `GET <worker>/health/ready`, and the Playwright deployed specs in `tests/e2e/` |
| Secrets | mounted from Secret Manager as env vars named exactly as the keys above |
| Frontend | static build of `apps/frontend` plus its Pages Function (`functions/`, `_routes.json`) deployed with wrangler to Cloudflare Pages; Pages project `knowserve-m0-spike` (origin `https://knowserve-m0-spike.pages.dev`; the first apply must confirm the real pages.dev host equals `api_allowed_origins[0]`), Pages variable `API_ORIGIN` and Pages secret `PROXY_SHARED_SECRET` (`proxy.md`) |

No cloud resource is created or changed by any file in this repository until the user authorizes it (M0 plan, approvals A3/A4).
