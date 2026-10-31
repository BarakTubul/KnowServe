"""Worker application factory (contract: docs/contracts/jobs-outbox.md).

Every non-health route authenticates itself (SEC-14): QStash deliveries by signature, the outbox
dispatcher by Google OIDC (production) or a local token (local/ci). Live QStash and live Google
token verification are NOT verified here (BLOCKED until an approved cloud account exists).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core import request_context
from knowserve_core.db import check_database, create_engine, create_session_factory
from knowserve_core.logging import configure_logging
from knowserve_core.oidc import OidcVerifier, google_oidc_verifier
from knowserve_core.outbox import dispatch_pending
from knowserve_core.qstash import (
    ENVELOPE_SCHEMA_VERSION,
    SIGNATURE_HEADER,
    Publisher,
    SignatureError,
    build_publisher,
    verify_signature,
)
from knowserve_core.settings import Settings, get_settings
from knowserve_core.web import AppError, install_web

logger = logging.getLogger("knowserve.worker")


@dataclass(frozen=True)
class JobContext:
    job_id: uuid.UUID
    job_type: str
    correlation_id: str
    attempts: int


Handler = Callable[[JobContext], Awaitable[None]]
RUN_PATH = "/internal/jobs/run"


async def noop_handler(ctx: JobContext) -> None:
    """The M0 no-op job: proves claim, execute and complete. Real ingestion arrives in M3."""
    logger.info("noop job executed", extra={"job_id": str(ctx.job_id)})


def _missing_production_settings(settings: Settings) -> list[str]:
    required = {
        "KS_WORKER_PUBLIC_URL": settings.worker_public_url,
        "KS_QSTASH_TOKEN": settings.qstash_token,
        "KS_QSTASH_CURRENT_SIGNING_KEY": settings.qstash_current_signing_key,
        "KS_QSTASH_NEXT_SIGNING_KEY": settings.qstash_next_signing_key,
    }
    if settings.enable_recovery_dispatcher:
        required["KS_DISPATCHER_OIDC_AUDIENCE"] = settings.dispatcher_oidc_audience
        required["KS_DISPATCHER_OIDC_SERVICE_ACCOUNT"] = settings.dispatcher_oidc_service_account
    return [name for name, value in required.items() if not value]


def _insecure_production_urls(settings: Settings) -> list[str]:
    """Production must use https for the destination and the QStash API (review L5)."""
    urls = {
        "KS_WORKER_PUBLIC_URL": settings.worker_public_url,
        "KS_QSTASH_URL": settings.qstash_url,
    }
    return [name for name, value in urls.items() if value and not value.startswith("https://")]


MAX_DELIVERY_BODY_BYTES = 4096


async def _read_capped_body(request: Request) -> bytes | None:
    """Read the body but give up above the cap, before authentication (review L2)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_DELIVERY_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_DELIVERY_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _build_publisher(settings: Settings) -> Publisher:
    token = settings.qstash_token.get_secret_value() if settings.qstash_token else None
    return build_publisher(
        settings.qstash_url, token, settings.worker_public_url, settings.publish_timeout_seconds
    )


_UNAUTHENTICATED = ("UNAUTHENTICATED", "Authentication required")


def _unauthenticated() -> AppError:
    return AppError(401, *_UNAUTHENTICATED)


def _signing_keys(settings: Settings) -> list[str]:
    keys = (settings.qstash_current_signing_key, settings.qstash_next_signing_key)
    return [k.get_secret_value() for k in keys if k is not None]


def _expected_url(settings: Settings) -> str | None:
    if settings.worker_public_url:
        return settings.worker_public_url.rstrip("/") + RUN_PATH
    return None


router = APIRouter()


@router.get("/health/live", tags=["health"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
async def health_ready(request: Request) -> dict[str, str]:
    if not await check_database(request.app.state.engine):
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable")
    return {"status": "ready"}


_CLAIM = text(
    """
    UPDATE jobs SET status = 'processing', attempts = attempts + 1, claimed_by = :me,
                    lease_expires_at = now() + make_interval(secs => :lease), updated_at = now()
    WHERE id = :id AND (status = 'queued'
                        OR (status = 'processing'
                            AND (lease_expires_at IS NULL OR lease_expires_at < now())))
    RETURNING job_type, correlation_id, attempts
    """
)
_COMPLETE = text(
    """
    UPDATE jobs SET status = 'done', completed_at = now(), updated_at = now(),
                    lease_expires_at = NULL, last_error = NULL
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    """
)
_RELEASE = text(
    """
    UPDATE jobs SET status = :status, last_error = :error, lease_expires_at = NULL,
                    claimed_by = NULL, updated_at = now()
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    """
)


def _parse_envelope(body: bytes) -> uuid.UUID:
    try:
        data = json.loads(body)
    except ValueError:
        raise AppError(422, "VALIDATION_ERROR", "Body must be a JSON object") from None
    if not isinstance(data, dict):
        raise AppError(422, "VALIDATION_ERROR", "Body must be a JSON object")
    if data.get("schema_version") != ENVELOPE_SCHEMA_VERSION:
        raise AppError(422, "UNSUPPORTED_SCHEMA_VERSION", "Unsupported envelope schema_version")
    try:
        return uuid.UUID(str(data.get("job_id")))
    except ValueError:
        raise AppError(422, "VALIDATION_ERROR", "job_id must be a UUID") from None


@router.post(RUN_PATH, tags=["internal"])
async def run_job(request: Request) -> JSONResponse:
    state = request.app.state
    settings: Settings = state.settings
    body = await _read_capped_body(request)
    if body is None:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Request body too large")
    # Signature first: nothing else (parsing, DB) happens before this passes.
    try:
        verify_signature(
            token=request.headers.get(SIGNATURE_HEADER),
            body=body,
            signing_keys=_signing_keys(settings),
            expected_url=_expected_url(settings),
        )
    except SignatureError:
        logger.warning("rejected delivery with invalid signature")
        raise _unauthenticated() from None

    job_id = _parse_envelope(body)
    factory: async_sessionmaker[AsyncSession] = state.session_factory
    async with factory() as session, session.begin():
        row = (
            await session.execute(
                text("SELECT status, correlation_id FROM jobs WHERE id = :id"), {"id": job_id}
            )
        ).first()
    if row is None:
        logger.info("delivery for unknown job", extra={"job_id": str(job_id)})
        return JSONResponse({"result": "unknown_job"})
    request_context.set_correlation_id(row.correlation_id)
    if row.status == "done":
        return JSONResponse({"result": "already_done"})
    if row.status == "failed":
        return JSONResponse({"result": "failed"})

    me = f"{state.instance_id}:{uuid.uuid4().hex[:8]}"
    async with factory() as session, session.begin():
        claimed = (
            await session.execute(
                _CLAIM, {"id": job_id, "me": me, "lease": settings.job_lease_seconds}
            )
        ).first()
    if claimed is None:
        async with factory() as session, session.begin():
            current = (
                await session.execute(
                    text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id}
                )
            ).scalar_one_or_none()
        if current == "done":
            return JSONResponse({"result": "already_done"})
        if current == "failed":
            return JSONResponse({"result": "failed"})
        raise AppError(409, "JOB_IN_PROGRESS", "Job is being processed by another worker")

    ctx = JobContext(job_id, claimed.job_type, claimed.correlation_id, claimed.attempts)
    handler: Handler | None = state.handlers.get(ctx.job_type)
    if handler is None:
        await _finish(factory, _RELEASE, job_id, me, status="failed", error="no handler")
        logger.error("no handler for job type", extra={"job_type": ctx.job_type})
        return JSONResponse({"result": "failed"})
    logger.info("job claimed", extra={"job_id": str(job_id), "attempts": ctx.attempts})
    try:
        await asyncio.wait_for(handler(ctx), settings.job_handler_timeout_seconds)
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            error = "handler timed out"
        else:
            error = f"{type(exc).__name__}: {exc}"[:500]
        if ctx.attempts >= settings.job_max_attempts:
            # Attempts exhausted: the job is terminally failed and visible for a manual retry.
            # No further automatic retry is needed, so QStash is told to stop (2xx) only now.
            await _finish(factory, _RELEASE, job_id, me, status="failed", error=error)
            logger.error(
                "job failed permanently",
                extra={"job_id": str(job_id), "attempts": ctx.attempts},
                exc_info=True,
            )
            return JSONResponse({"result": "failed"})
        await _finish(factory, _RELEASE, job_id, me, status="queued", error=error)
        logger.error("job handler failed", extra={"job_id": str(job_id)}, exc_info=True)
        raise AppError(500, "JOB_FAILED", "Job failed; delivery will be retried") from None
    await _finish(factory, _COMPLETE, job_id, me)
    logger.info("job done", extra={"job_id": str(job_id)})
    return JSONResponse({"result": "done"})


async def _finish(
    factory: async_sessionmaker[AsyncSession], stmt: Any, job_id: uuid.UUID, me: str, **extra: Any
) -> None:
    async with factory() as session, session.begin():
        await session.execute(stmt, {"id": job_id, "me": me, **extra})


async def _require_dispatcher(request: Request) -> None:
    state = request.app.state
    settings: Settings = state.settings
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthenticated()
    if settings.env == "production":
        audience = settings.dispatcher_oidc_audience
        account = settings.dispatcher_oidc_service_account
        if not audience or not account:
            raise _unauthenticated()
        try:
            claims = await asyncio.to_thread(state.oidc_verifier, token, audience)
        except Exception:
            raise _unauthenticated() from None
        email = claims.get("email")
        if (
            not isinstance(email, str)
            or not hmac.compare_digest(email.encode(), account.encode())
            or claims.get("email_verified") is not True
        ):
            raise _unauthenticated()
        return
    local = settings.dispatcher_local_token
    if local is None or not hmac.compare_digest(token.encode(), local.get_secret_value().encode()):
        raise _unauthenticated()


# Optional scheduled-recovery endpoint: mounted only when KS_ENABLE_RECOVERY_DISPATCHER is true.
# It is the only caller of the multi-row dispatch_pending (see its known gap).
dispatcher_router = APIRouter()


@dispatcher_router.post("/internal/outbox/dispatch", tags=["internal"])
async def dispatch(request: Request) -> dict[str, int]:
    await _require_dispatcher(request)
    state = request.app.state
    settings: Settings = state.settings
    result = await dispatch_pending(
        state.session_factory,
        state.publisher,
        batch_size=settings.outbox_batch_size,
        lease_seconds=settings.outbox_lease_seconds,
    )
    logger.info(
        "outbox dispatch run", extra={"published": result.published, "failed": result.failed}
    )
    return {"published": result.published, "failed": result.failed}


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    publisher: Publisher | None = None,
    handlers: dict[str, Handler] | None = None,
    oidc_verifier: OidcVerifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.env == "production":
        missing = _missing_production_settings(settings)
        if missing:
            raise RuntimeError(
                "Worker refuses to start in production; missing: " + ", ".join(missing)
            )
        insecure = _insecure_production_urls(settings)
        if insecure:
            raise RuntimeError(
                "Worker refuses to start in production; https required for: " + ", ".join(insecure)
            )
    configure_logging("worker", settings.log_level)
    engine = engine or create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="KnowServe Worker", version=version("knowserve-worker"), lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.publisher = publisher or _build_publisher(settings)
    app.state.handlers = handlers if handlers is not None else {"noop": noop_handler}
    app.state.oidc_verifier = oidc_verifier or google_oidc_verifier
    app.state.instance_id = f"worker-{uuid.uuid4().hex[:8]}"
    app.include_router(router)
    if settings.enable_recovery_dispatcher:
        app.include_router(dispatcher_router)
    install_web(app)
    return app
