"""Shared helpers for the M3 upload and import tests (M3-03, M3-04). Not a test module."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_api.app import create_app
from knowserve_core.clock import FakeClock
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.qstash import FakePublisher
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS

FIN = DEPARTMENT_IDS["finance"]
HR = DEPARTMENT_IDS["human-resources"]
ENG = DEPARTMENT_IDS["engineering"]
LEGAL = DEPARTMENT_IDS["legal"]
ORIGIN = "http://localhost:5173"

# Tables a rejected upload must leave untouched (SEC-11: no row, object or job afterwards).
COUNTED_TABLES = (
    "documents",
    "document_revisions",
    "document_department_access",
    "jobs",
    "outbox",
    "admin_idempotency_keys",
    "import_batch_entries",
)


def make_app(
    engine: AsyncEngine,
    clock: FakeClock,
    *,
    store: Any = None,
    publisher: Any = None,
    **overrides: Any,
) -> FastAPI:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        api_allowed_origins=[ORIGIN],
        **overrides,
    )
    return create_app(
        settings,
        engine=engine,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=store if store is not None else FakeObjectStore(),
        publisher=publisher if publisher is not None else FakePublisher(),
    )


def make_client(app: FastAPI) -> httpx.AsyncClient:
    # A server error is a 500 response here, not an exception in the test.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="https://api.test")


def stored_keys(store: FakeObjectStore) -> list[str]:
    return sorted(store._objects)  # pyright: ignore[reportPrivateUsage]


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        return {
            table: int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
            for table in COUNTED_TABLES
        }


async def assert_nothing_created(engine: AsyncEngine, store: FakeObjectStore) -> None:
    assert await counts(engine) == dict.fromkeys(COUNTED_TABLES, 0)
    assert stored_keys(store) == []


def upload_data(
    *,
    title: str = "Leave policy",
    owner: str = FIN,
    allowed: Sequence[str] | None = (FIN,),
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"title": title, "owner_department_id": owner}
    if allowed is not None:
        data["allowed_department_ids"] = list(allowed)
    data.update(extra or {})
    return data


async def post_document(
    client: httpx.AsyncClient,
    session: Any,
    *,
    pdf: bytes,
    filename: str = "policy.pdf",
    key: str | None = None,
    data: dict[str, Any] | None = None,
    csrf: bool = True,
) -> httpx.Response:
    headers = {"Idempotency-Key": key or f"key-{uuid.uuid4().hex}", **session.headers}
    if not csrf:
        headers.pop("X-CSRF-Token")
    return await client.post(
        "/v1/admin/documents",
        headers=headers,
        cookies=session.cookies,
        data=data if data is not None else upload_data(),
        files={"file": (filename, pdf, "application/pdf")},
    )
