"""FastAPI application factory (contract: docs/contracts/api.md)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_core.db import check_database, create_engine, create_session_factory
from knowserve_core.logging import configure_logging
from knowserve_core.oidc import OidcVerifier, google_oidc_verifier
from knowserve_core.qstash import Publisher, build_publisher
from knowserve_core.settings import Settings, get_settings
from knowserve_core.web import AppError, ErrorEnvelope, install_web

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
    return SpikeEchoResponse(
        cookie_present=SPIKE_COOKIE in request.cookies,
        client_ip=getattr(request.state, "client_ip", None),
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


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    publisher: Publisher | None = None,
    oidc_verifier: OidcVerifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    proxy_secret = (
        settings.proxy_shared_secret.get_secret_value() if settings.proxy_shared_secret else ""
    )
    if settings.env == "production" and not proxy_secret:
        raise RuntimeError("API refuses to start in production without KS_PROXY_SHARED_SECRET")
    configure_logging("api", settings.log_level)
    engine = engine or create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
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
    app.include_router(router)
    if settings.enable_spike_job_ops:
        app.include_router(operator_router)
    if settings.enable_spike_endpoints:
        app.include_router(spike_router)
    if proxy_secret:
        install_proxy_guard(app, proxy_secret)  # before install_web: errors keep a request id
    install_web(app)
    if not proxy_secret:
        # Same-origin proxy route (docs/contracts/proxy.md) needs no CORS. With the guard on,
        # CORS is not installed, so preflights reach the guard and are rejected too.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    return app
