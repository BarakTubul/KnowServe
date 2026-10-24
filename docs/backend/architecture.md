# Backend architecture

## Purpose
Conventions every backend change must follow. Read this before touching `backend/`.

## Requirements
| ID | Requirement |
|---|---|
| ARCH-01 | Layering is router (HTTP only) -> controller (optional, thin) -> service (business logic) -> repository -> model. Routers contain no business logic and no DB access. |
| ARCH-02 | DB access goes through `UnitOfWork` (`core/unit_of_work.py`), which commits on clean exit and rolls back on exception. Repositories extend `BaseRepository[T]`. |
| ARCH-03 | Services return plain dicts/lists, never ORM objects, since sessions close when the UoW exits. |
| ARCH-04 | Request/response shapes are Pydantic models in `pydantic_schemas/`. |
| ARCH-05 | Routers map exceptions to HTTP codes: `ValueError` -> 400/404, `PermissionError` -> 403, anything else -> 500 with a generic message. |
| ARCH-06 | Auth is applied in `main.py` via router-level dependencies: `require_user` on `/chat` and `/documents`, `require_admin` on `/admin` and `/monitor`. `/auth` and `/ws` are public. |
| ARCH-07 | Heavy ML imports (LlamaIndex, HuggingFace, OpenAI) stay lazy or singleton (`core/vector_store.py`, `agent/llama_agent.py`). |
| ARCH-08 | Redis caches use the keys `docs:all` and `docs:access:{department_id}`; any write that changes documents or access must invalidate them. |
| ARCH-09 | New code logs with the `logging` module, not `print`. |

## Conventions
- Files are snake_case with suffixes `_service`, `_controller`, `_repository`, `_schema`; table names are plural.
- Each router is a module-level `router = APIRouter()`; prefixes are set in `main.py`; admin sub-routers live in `routers/admin/` and are mounted in `routers/admin/__init__.py`.
- Config comes from `config.py` (pydantic-settings, `.env`): `DB_*`, `REDIS_URL`, `CHROMA_PATH`, `JWT_SECRET_KEY`, `OPENAI_API_KEY`.
- `TESTING=1` makes startup skip DB/Redis init (but it still warms the embedding model, see gaps).

## Files
`backend/app/main.py`, `core/unit_of_work.py`, `repositories/base_repository.py`, `core/redis_client.py`, `config.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| ARCH-02 | unit | UoW block raises inside `with` | session rolled back and closed, nothing committed |
| ARCH-02 | unit | UoW block exits cleanly | commit called once, session closed |
| ARCH-06 | integration | Call each protected prefix without a token | 401 |
| ARCH-06 | integration | Call `/admin/*` and `/monitor/` as employee | 403 |
| ARCH-05 | integration | Trigger `ValueError`/`PermissionError`/unexpected error on a route | 4xx/403/500 with the mapped status and no stack trace in body |
| ARCH-08 | unit | `invalidate_caches` with keys present/absent | present keys removed, absent ones don't raise |

## Known gaps
- `requirements.txt` is unpinned and lacks `llama-index*`, `openai`, HuggingFace, `gdown`, `pytest-asyncio`, though the code imports them.
- Logging uses `print` with emoji everywhere (ARCH-09 is aspirational), except `routers/auth.py`.
- Startup warms the ML models even under `TESTING=1`; tests need those models or a patch.
- `main.py` uses deprecated `@app.on_event`.
- The test directory was deleted; `pytest.ini` exists (`pythonpath = .`, `asyncio_mode = auto`).
- `app/chroma_data/` and `app/static/docs/*.pdf` are committed to git.

## Related docs
`auth.md`, `documents.md`, `admin-docs.md`, `ingestion.md`
