"""FastAPI application factory (contract: docs/contracts/api.md)."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_core.clock import Clock, SystemClock
from knowserve_core.db import check_database, create_engine, create_session_factory
from knowserve_core.firebase_tokens import TokenVerifier
from knowserve_core.firebase_verifier import FirebaseTokenVerifier
from knowserve_core.logging import configure_logging
from knowserve_core.object_store import ObjectStore, R2Config, build_object_store
from knowserve_core.oidc import OidcVerifier, google_oidc_verifier
from knowserve_core.qstash import Publisher, build_publisher
from knowserve_core.ratelimit import RateLimiter
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings, get_settings
from knowserve_core.web import AppError, ErrorEnvelope, install_web

from .admin.router import router as admin_router
from .auth.router import router as auth_router
from .body_limit import AdminBodyLimit
from .demo.router import router as demo_router
from .departments.router import router as departments_router
from .documents.router import router as documents_router
from .operator import router as operator_router
from .proxy_guard import install_proxy_guard


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]


class StatusResponse(BaseModel):
    service: Literal["api"]
    version: str
    environment: Literal["local", "ci", "production"]
    database: Literal["ok"]


def _operation_id(route: APIRoute) -> str:
    return route.name


router = APIRouter()
_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorEnvelope, "description": "Database unavailable"}
}


spike_router = APIRouter(prefix="/v1/spike", tags=["spike"])
SPIKE_COOKIE = "ks_spike"


class SpikeEchoResponse(BaseModel):
    cookie_present: bool
    # The client IP the Pages Function forwarded (X-KS-Client-IP), trusted only after the proxy
    # secret check; None when absent. M0-AC11 spike evidence only.
    # Always None in production (SEC-18: no client address leaves the API).
    client_ip: str | None = None


@spike_router.post("/cookie", status_code=204)
async def spike_cookie() -> Response:
    """M0-08 only: host-only test cookie (no Domain attribute)."""
    response = Response(status_code=204)
    response.set_cookie(
        SPIKE_COOKIE, "1", max_age=300, path="/", secure=True, httponly=True, samesite="lax"
    )
    return response


@spike_router.get("/echo", response_model=SpikeEchoResponse)
async def spike_echo(request: Request) -> SpikeEchoResponse:
    production = request.app.state.settings.env == "production"
    return SpikeEchoResponse(
        cookie_present=SPIKE_COOKIE in request.cookies,
        client_ip=None if production else getattr(request.state, "client_ip", None),
    )


@spike_router.get("/stream")
async def spike_stream(
    seconds: int = Query(10, ge=1, le=600), interval: float = Query(1.0, ge=0.1, le=10.0)
) -> StreamingResponse:
    """M0 spike only: a timed SSE stream to measure proxy buffering and timeouts.

    Emits one ``data`` event every ``interval`` seconds for ``seconds`` seconds, then a final
    ``done`` event.
    """

    async def events() -> AsyncIterator[str]:
        total = int(seconds / interval)
        for i in range(1, total + 1):
            await asyncio.sleep(interval)
            yield f"data: {json.dumps({'n': i, 'of': total})}\n\n"
        yield 'event: done\ndata: {"complete": true}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _engine(request: Request) -> AsyncEngine:
    return request.app.state.engine


@router.get("/health/live", response_model=LiveResponse, tags=["health"])
async def health_live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/health/ready", response_model=ReadyResponse, responses=_UNAVAILABLE, tags=["health"])
async def health_ready(request: Request) -> ReadyResponse:
    if not await check_database(_engine(request)):
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable")
    return ReadyResponse(status="ready")


@router.get("/v1/status", response_model=StatusResponse, responses=_UNAVAILABLE, tags=["status"])
async def get_status(request: Request) -> StatusResponse:
    if not await check_database(_engine(request)):
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable")
    settings: Settings = request.app.state.settings
    return StatusResponse(
        service="api", version=version("knowserve-api"), environment=settings.env, database="ok"
    )


def _build_object_store(settings: Settings) -> ObjectStore:
    """Select the document store at startup. In production only ``r2`` with its full
    configuration is accepted; anything else stops the API with a message naming the setting."""
    secret = settings.r2_secret_access_key
    key_id = settings.r2_access_key_id
    try:
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
    except ValueError as exc:
        raise RuntimeError(f"API refuses to start: {exc}") from None


def _ip_hash_pepper(settings: Settings) -> bytes:
    """Pepper for the keyed hash of client addresses in limiter keys (SEC-18, OPEN-28 Q9).

    Production must configure it. Elsewhere a random per-process pepper is used, so nothing
    reversible is ever derived from a stable value in a local database.
    """
    value = settings.ip_hash_pepper.get_secret_value() if settings.ip_hash_pepper else ""
    if value:
        if len(value) >= 16:
            return value.encode()
        raise RuntimeError("KS_IP_HASH_PEPPER must be at least 16 characters")
    if settings.env == "production":
        raise RuntimeError("API refuses to start in production without KS_IP_HASH_PEPPER")
    return secrets.token_bytes(32)


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    publisher: Publisher | None = None,
    oidc_verifier: OidcVerifier | None = None,
    token_verifier: TokenVerifier | None = None,
    rate_limiter: RateLimiter | None = None,
    clock: Clock | None = None,
    object_store: ObjectStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    proxy_secret = (
        settings.proxy_shared_secret.get_secret_value() if settings.proxy_shared_secret else ""
    )
    if settings.env == "production" and not proxy_secret:
        raise RuntimeError("API refuses to start in production without KS_PROXY_SHARED_SECRET")
    if settings.env == "production" and not settings.firebase_project_id:
        raise RuntimeError("API refuses to start in production without KS_FIREBASE_PROJECT_ID")
    configure_logging("api", settings.log_level)
    pepper = _ip_hash_pepper(settings)
    store = object_store or _build_object_store(settings)
    engine = engine or create_engine(settings.database_url)

    app_clock = clock or SystemClock()
    owns_verifier = token_verifier is None
    app_token_verifier = token_verifier or FirebaseTokenVerifier(settings, app_clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_verifier and isinstance(app_token_verifier, FirebaseTokenVerifier):
            app_token_verifier.close()
        close = getattr(store, "aclose", None)
        if close is not None:
            await close()
        await engine.dispose()

    app = FastAPI(
        title="KnowServe API",
        version=version("knowserve-api"),
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    token = settings.qstash_token.get_secret_value() if settings.qstash_token else None
    app.state.publisher = publisher or build_publisher(
        settings.qstash_url, token, settings.worker_public_url, settings.publish_timeout_seconds
    )
    app.state.oidc_verifier = oidc_verifier or google_oidc_verifier
    # M1 auth state (M1-02a): injectable for tests, real implementations otherwise.
    app.state.clock = app_clock
    app.state.ip_hash_pepper = pepper
    app.state.object_store = store
    app.state.token_verifier = app_token_verifier
    app.state.rate_limiter = rate_limiter or PostgresRateLimiter(app_clock)
    app.include_router(router)
    # M1 slice routers are registered once here so slices never edit the app factory.
    for slice_router in (
        auth_router,
        demo_router,
        departments_router,
        admin_router,
        documents_router,
    ):
        app.include_router(slice_router)
    if settings.enable_spike_job_ops:
        app.include_router(operator_router)
    if settings.enable_spike_endpoints:
        app.include_router(spike_router)
    if proxy_secret:
        install_proxy_guard(app, proxy_secret)  # before install_web: errors keep a request id
    app.add_middleware(
        AdminBodyLimit,
        max_body_bytes=max(settings.upload_max_zip_bytes, settings.upload_max_pdf_bytes),
    )
    install_web(app)
    if not proxy_secret:
        # Same-origin proxy route (docs/contracts/proxy.md) needs no CORS. With the guard on,
        # CORS is not installed, so preflights reach the guard and are rejected too.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Token"],
            expose_headers=["X-Request-ID"],
        )
    return app
