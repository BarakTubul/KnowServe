"""FastAPI application factory (contract: docs/contracts/api.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_core.db import check_database, create_engine
from knowserve_core.logging import configure_logging
from knowserve_core.settings import Settings, get_settings
from knowserve_core.web import AppError, ErrorEnvelope, install_web


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


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    settings = settings or get_settings()
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
    app.include_router(router)
    install_web(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    return app
