# Shared contracts (M0)

These are the interfaces that more than one workstream depends on. The Planning & Integration Owner approves every change and coordinates it with the dependent workstreams **before** implementation (WF-03, OPEN-01). Behavior requirements live in the specs; these files fix only the concrete shapes M0 needs.

| Contract | File | Used by |
|---|---|---|
| API surface, error envelope, request ids, OpenAPI baseline | `api.md` | API, Frontend, CI |
| Config keys, local conventions, deployment interface | `config-and-deploy.md` | all services, Infrastructure, CI |
| Job envelope, jobs/outbox schema, Worker and dispatcher endpoints | `jobs-outbox.md` | API, Worker, Infrastructure |
| Log fields and correlation ids | `logging.md` | API, Worker |
| Same-origin API proxy (Pages Function), direct-access guard | `proxy.md` | Frontend, API, Infrastructure |
| OpenAPI baseline (generated, approved) | `openapi.json` | CI drift check, Frontend client |

Code that implements the shared parts lives in `packages/backend_core/src/knowserve_core/`:
`settings.py`, `db.py`, `models.py`, `logging.py`, `request_context.py`, `web.py` (Owner), and `jobs.py`, `outbox.py`, `qstash.py` (Worker workstream, under `jobs-outbox.md`). Migrations are in `packages/backend_core/migrations/` and are written only by the backend workstream.
