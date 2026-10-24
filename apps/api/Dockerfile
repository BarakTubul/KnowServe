# KnowServe API image. Build from the repository root:
#   docker build -f apps/api/Dockerfile .
# The same image runs migrations: alembic -c packages/backend_core/alembic.ini upgrade head
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Workspace manifests first so the dependency layer caches.
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY apps apps
RUN uv sync --frozen --no-dev --no-editable --package knowserve-api

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH" PORT=8000
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Alembic config and migrations (not part of the installed wheel).
COPY --chown=app:app packages/backend_core/alembic.ini packages/backend_core/alembic.ini
COPY --chown=app:app packages/backend_core/migrations packages/backend_core/migrations
COPY --chown=app:app apps/api/uvicorn_log.json /app/uvicorn_log.json
USER app
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn knowserve_api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --log-config /app/uvicorn_log.json --no-access-log"]
