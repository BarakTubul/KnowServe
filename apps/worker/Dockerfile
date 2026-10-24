# Worker image. Build from the repository root:
#   docker build -f apps/worker/Dockerfile -t knowserve-worker .
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Workspace manifests first so dependency layers cache.
COPY pyproject.toml uv.lock ./
COPY packages/backend_core/pyproject.toml packages/backend_core/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml

COPY packages/backend_core packages/backend_core
COPY apps/worker apps/worker
RUN mkdir -p apps/api/src/knowserve_api \
    && uv sync --frozen --no-dev --package knowserve-worker

FROM python:3.11-slim
RUN useradd --system --uid 10001 --create-home worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8001
USER worker
EXPOSE 8001
CMD ["sh", "-c", "exec uvicorn knowserve_worker.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8001}"]
