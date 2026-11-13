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
from pathlib import Path
from typing import Any, NoReturn

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core import demo_cleanup, request_context
from knowserve_core.clock import Clock, SystemClock
from knowserve_core.db import check_database, create_engine, create_session_factory
from knowserve_core.embeddings import EmbeddingProvider, build_embedding_provider
from knowserve_core.ingestion_contract import FAILURES, INGEST_JOB_TYPE, FailureCode
from knowserve_core.job_claims import (
    claim_job,
    complete_job,
    fail_job,
    release_job,
    renew_lease,
)
from knowserve_core.job_fencing import LostClaimError, assert_claimed
from knowserve_core.job_hooks import NonRetryableJobError, RetryableJobError, TerminalFailureHook
from knowserve_core.jobs import MANUAL_RETRY_MARKER
from knowserve_core.logging import configure_logging
from knowserve_core.object_store import ObjectStore, R2Config, build_object_store
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
from knowserve_core.revision_hooks import mark_revision_failed
from knowserve_core.settings import Settings, get_settings
from knowserve_core.web import AppError, install_web

from .ingest import lazy_ingest_handler

logger = logging.getLogger("knowserve.worker")


@dataclass(frozen=True)
class JobContext:
    job_id: uuid.UUID
    job_type: str
    correlation_id: str
    attempts: int
    previous_error: str | None = None
    # The claim this worker holds. Pipeline writes call ``fence`` first (F7).
    claimed_by: str = ""

    async def fence(self, session: AsyncSession) -> None:
        """Lock the job row and require that this worker still holds it, or raise
        ``LostClaimError``. Call it first in every transaction that writes pipeline results."""
        await assert_claimed(session, self.job_id, self.claimed_by)


Handler = Callable[[JobContext], Awaitable[None]]
RUN_PATH = "/internal/jobs/run"
DEMO_CLEANUP_PATH = "/internal/maintenance/demo-cleanup"


async def always_fail_handler(ctx: JobContext) -> None:
    """Spike failure hook (KS_ENABLE_SPIKE_FAILURE_HOOKS): drives retries and terminal failure."""
    raise RuntimeError("always_fail test job")


async def fail_then_ok_handler(ctx: JobContext) -> None:
    """Spike failure hook: fails until an operator has manually retried the job, then succeeds.

    Shows the full recovery cycle (automatic attempts exhausted, `failed`, manual retry, `done`).
    Registered only with KS_ENABLE_SPIKE_FAILURE_HOOKS; real job types never use it.
    """
    if not (ctx.previous_error or "").startswith(MANUAL_RETRY_MARKER):
        raise RuntimeError("fail_then_ok test job: not retried manually yet")


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


def _build_object_store(settings: Settings) -> ObjectStore:
    """The Worker only reads: in production its R2 token is read-only (OPEN-31 D6) and no code
    path here deletes or writes."""
    key_id = settings.r2_access_key_id
    secret = settings.r2_secret_access_key
    return build_object_store(
        settings.object_store,
        env=settings.env,
        filesystem_root=Path(settings.object_store_path),
        r2=R2Config(
            endpoint=settings.r2_endpoint,
            bucket=settings.r2_bucket,
            access_key_id=key_id.get_secret_value() if key_id else None,
            secret_access_key=secret.get_secret_value() if secret else None,
        ),
    )


def _build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    key = settings.openai_api_key
    return build_embedding_provider(
        settings.embedding_provider,
        settings.env,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        api_key=key.get_secret_value() if key else None,
        batch_size=settings.embedding_batch_size,
        timeout_seconds=settings.embedding_timeout_seconds,
    )


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


def _expected_url(settings: Settings, path: str = RUN_PATH) -> str | None:
    if settings.worker_public_url:
        return settings.worker_public_url.rstrip("/") + path
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

    hook: TerminalFailureHook = state.terminal_hook
    me = f"{state.instance_id}:{uuid.uuid4().hex[:8]}"
    claim = await claim_job(
        factory,
        job_id,
        me,
        lease_seconds=settings.job_lease_seconds,
        max_attempts=settings.job_max_attempts,
        terminal_hook=hook,
    )
    if claim.kind == "unknown":
        return JSONResponse({"result": "unknown_job"})
    if claim.kind == "done":
        return JSONResponse({"result": "already_done"})
    if claim.kind == "failed":
        return JSONResponse({"result": "failed"})
    if claim.kind == "busy":
        raise AppError(409, "JOB_IN_PROGRESS", "Job is being processed by another worker")
    if claim.kind == "crash_failed":
        # The attempt cap was already used up by claims that never reported back (crash loop).
        logger.error("job failed permanently: crash guard", extra={"job_id": str(job_id)})
        raise AppError(500, "JOB_FAILED_PERMANENTLY", "Job failed; attempts exhausted")
    assert claim.job is not None

    ctx = JobContext(
        job_id,
        claim.job.job_type,
        claim.job.correlation_id,
        claim.job.attempts,
        claim.job.last_error,
        claimed_by=me,
    )
    handler: Handler | None = state.handlers.get(ctx.job_type)
    if handler is None:
        if not await fail_job(factory, job_id, me, FailureCode.INTERNAL_ERROR, "no handler", hook):
            raise _claim_lost(job_id)
        logger.error("no handler for job type", extra={"job_type": ctx.job_type})
        return JSONResponse({"result": "failed"})
    logger.info("job claimed", extra={"job_id": str(job_id), "attempts": ctx.attempts})
    try:
        await _run_with_heartbeat(handler, ctx, state, settings)
    except LostClaimError:
        raise _claim_lost(job_id) from None
    except NonRetryableJobError as exc:
        # Retrying cannot help (ING-23): failed at once, without waiting for the attempt cap.
        await _fail_permanently(
            factory, hook, job_id, me, exc.failure_code, exc.failure_code.value, ctx.attempts
        )
    except Exception as exc:
        code, error = _classify(exc)
        if ctx.attempts >= settings.job_max_attempts:
            # Attempts exhausted: the job is terminally failed and visible for a manual retry.
            # The execution still failed, so it is not acknowledged with 2xx; if QStash has
            # retries left, the next delivery finds a `failed` job and answers 200 (no work).
            await _fail_permanently(factory, hook, job_id, me, code, error, ctx.attempts)
        if not await release_job(factory, job_id, me, error):
            raise _claim_lost(job_id) from None
        logger.error("job handler failed", extra={"job_id": str(job_id)}, exc_info=True)
        raise AppError(500, "JOB_FAILED", "Job failed; delivery will be retried") from None
    if not await complete_job(factory, job_id, me):
        raise _claim_lost(job_id)
    logger.info("job done", extra={"job_id": str(job_id)})
    return JSONResponse({"result": "done"})


def _classify(exc: Exception) -> tuple[FailureCode, str]:
    """The failure code shown if this was the last attempt, and the text kept in ``last_error``."""
    if isinstance(exc, RetryableJobError):
        return exc.failure_code, exc.failure_code.value
    if isinstance(exc, TimeoutError):
        return FailureCode.PROCESSING_TIMEOUT, "handler timed out"
    return FailureCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"[:500]


def _claim_lost(job_id: uuid.UUID) -> AppError:
    # The job is no longer ours (reclaimed after a lease expiry, or finished elsewhere). Nothing
    # was changed; the current owner decides the outcome. QStash may redeliver.
    logger.warning("job claim lost", extra={"job_id": str(job_id)})
    return AppError(409, "JOB_CLAIM_LOST", "Job is no longer claimed by this worker")


async def _fail_permanently(
    factory: async_sessionmaker[AsyncSession],
    hook: TerminalFailureHook,
    job_id: uuid.UUID,
    me: str,
    code: FailureCode,
    error: str,
    attempts: int,
) -> NoReturn:
    if not await fail_job(factory, job_id, me, code, error, hook):
        raise _claim_lost(job_id)
    logger.error(
        "job failed permanently",
        extra={"job_id": str(job_id), "attempts": attempts, "failure_code": code.value},
        exc_info=True,
    )
    raise AppError(500, "JOB_FAILED_PERMANENTLY", FAILURES[code].message) from None


async def _run_with_heartbeat(
    handler: Handler, ctx: JobContext, state: Any, settings: Settings
) -> None:
    """Run the handler under the handler timeout while a heartbeat keeps the lease alive.

    If the heartbeat finds the claim gone, the handler is cancelled and ``LostClaimError`` is
    raised, so a worker that lost its job stops working on it.
    """
    factory: async_sessionmaker[AsyncSession] = state.session_factory
    interval: float = state.heartbeat_interval
    task = asyncio.ensure_future(handler(ctx))
    lost = asyncio.Event()
    stop = asyncio.Event()

    async def beat() -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), interval)
                return  # the handler finished; stop without cutting a renewal short
            except TimeoutError:
                pass
            try:
                alive = await renew_lease(
                    factory, ctx.job_id, ctx.claimed_by, settings.job_lease_seconds
                )
            except Exception:
                # A database blip must not kill the handler; the next beat tries again and the
                # fencing check protects the writes if the lease really lapsed.
                logger.warning("lease renewal failed", extra={"job_id": str(ctx.job_id)})
                continue
            if not alive:
                lost.set()
                task.cancel()
                return

    heartbeat = asyncio.ensure_future(beat())
    try:
        await asyncio.wait_for(task, settings.job_handler_timeout_seconds)
    except asyncio.CancelledError:
        if lost.is_set():
            raise LostClaimError("lease renewal found the claim gone") from None
        raise
    finally:
        stop.set()
        await asyncio.gather(heartbeat, return_exceptions=True)
    if lost.is_set():
        raise LostClaimError("lease renewal found the claim gone")


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


# The single SEC-14 exception (OPEN-26 N6, ADR 0006, AUTH-35): a signed delivery without a job row.
# It takes NO caller-controlled input. The body is read (capped) only because the QStash signature
# commits to its hash; it is never parsed, and neither are the query string or any header other
# than the signature. The destination (`sub`) is bound to this path, so a signed job delivery
# cannot be replayed here. Mounted unconditionally; there is no other maintenance route.
maintenance_router = APIRouter()


@maintenance_router.post(DEMO_CLEANUP_PATH, tags=["internal"])
async def demo_cleanup_run(request: Request) -> dict[str, int | bool]:
    state = request.app.state
    settings: Settings = state.settings
    body = await _read_capped_body(request)
    if body is None:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Request body too large")
    expected_url = _expected_url(settings, DEMO_CLEANUP_PATH)
    if expected_url is None:
        # Without the destination binding a signed job delivery could be replayed here.
        raise _unauthenticated()
    try:
        verify_signature(
            token=request.headers.get(SIGNATURE_HEADER),
            body=body,
            signing_keys=_signing_keys(settings),
            expected_url=expected_url,
        )
    except SignatureError:
        logger.warning("rejected maintenance delivery with invalid signature")
        raise _unauthenticated() from None

    result = await demo_cleanup.run(state.session_factory, settings, state.clock)
    if result.failed_batches:
        # Not acknowledged, so QStash retries; the cleanup is idempotent and resumable.
        raise AppError(500, "CLEANUP_FAILED", "Demo cleanup did not complete; it will be retried")
    return result.as_dict()


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    publisher: Publisher | None = None,
    handlers: dict[str, Handler] | None = None,
    oidc_verifier: OidcVerifier | None = None,
    clock: Clock | None = None,
    terminal_hook: TerminalFailureHook | None = None,
    heartbeat_interval: float | None = None,
    object_store: ObjectStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
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
    default_handlers: dict[str, Handler] = {
        "noop": noop_handler,
        INGEST_JOB_TYPE: lazy_ingest_handler(
            app.state.session_factory,
            settings,
            lambda: object_store or _build_object_store(settings),
            lambda: embedding_provider or _build_embedding_provider(settings),
        ),
    }
    if settings.enable_spike_failure_hooks:
        default_handlers["always_fail"] = always_fail_handler
        default_handlers["fail_then_ok"] = fail_then_ok_handler
    app.state.handlers = handlers if handlers is not None else default_handlers
    app.state.oidc_verifier = oidc_verifier or google_oidc_verifier
    app.state.clock = clock or SystemClock()
    app.state.instance_id = f"worker-{uuid.uuid4().hex[:8]}"
    app.state.terminal_hook = terminal_hook or mark_revision_failed
    # Renew at a third of the lease, so two missed beats still leave the lease alive.
    app.state.heartbeat_interval = heartbeat_interval or max(0.05, settings.job_lease_seconds / 3)
    app.include_router(router)
    app.include_router(maintenance_router)
    if settings.enable_recovery_dispatcher:
        app.include_router(dispatcher_router)
    install_web(app)
    return app
