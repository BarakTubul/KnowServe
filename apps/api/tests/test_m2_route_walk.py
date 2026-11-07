"""M2-AC06: every route that returns document bytes or metadata applies the shared predicate.

Two layers. A structural walk fails when a new document route appears that is not registered here
(so it cannot ship without a matrix row). A behavioural walk runs every registered route through
the matrix {allowed, forbidden, deleted, not ready, no revision} for a caller in one department.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.app import create_app
from knowserve_core.clock import FakeClock
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS, make_document

pytestmark = [pytest.mark.m2, pytest.mark.documents, pytest.mark.api, pytest.mark.integration]

FIN = uuid.UUID(DEPARTMENT_IDS["finance"])
PDF = b"%PDF-1.4\n" + b"x" * 512 + b"\n%%EOF\n"

# Routes that return document data, as (method, path template). A new route under /v1/documents
# that is missing from this set fails the structural walk until it is added with a matrix row.
ID_ROUTES = {
    ("GET", "/v1/documents/{document_id}"),
    ("GET", "/v1/documents/{document_id}/content"),
}
LIST_ROUTES = {("GET", "/v1/documents")}


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, clock: FakeClock) -> tuple[FastAPI, FakeObjectStore]:
    store = FakeObjectStore()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        api_allowed_origins=["http://localhost:5173"],
    )
    return (
        create_app(
            settings,
            engine=engine,
            rate_limiter=PostgresRateLimiter(clock),
            clock=clock,
            object_store=store,
        ),
        store,
    )


@pytest_asyncio.fixture
async def client(app: tuple[FastAPI, FakeObjectStore]) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app[0]), base_url="https://api.test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def cookies(make_user: Any, make_session: Any) -> dict[str, str]:
    user = await make_user("registered", department_id=FIN)
    return (await make_session(user, department_id=FIN)).cookies


def _document_routes(app: FastAPI) -> set[tuple[str, str]]:
    # OpenAPI lists every mounted route, including those of included routers.
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/v1/documents")
        for method in operations
    }


async def test_m2_ac06_no_unregistered_document_route(
    app: tuple[FastAPI, FakeObjectStore],
) -> None:
    assert _document_routes(app[0]) == ID_ROUTES | LIST_ROUTES


async def _make(
    session_factory: async_sessionmaker[AsyncSession], store: FakeObjectStore, **kwargs: Any
) -> uuid.UUID:
    async with session_factory() as s:
        doc = await make_document(s, **kwargs)
        await s.commit()
    await store.put(f"documents/{doc.id}/rev.pdf", PDF, "application/pdf")
    return doc.id


@pytest.mark.parametrize("method,path", sorted(ID_ROUTES))
async def test_m2_ac06_by_id_routes_apply_the_predicate_matrix(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    app: tuple[FastAPI, FakeObjectStore],
    method: str,
    path: str,
) -> None:
    store = app[1]
    allowed = await _make(session_factory, store)
    hidden = {
        "forbidden": await _make(session_factory, store, allowed=("engineering",)),
        "deleted": await _make(session_factory, store, deleted=True),
        "queued": await _make(session_factory, store, status="queued"),
        "processing": await _make(session_factory, store, status="processing"),
        "failed": await _make(session_factory, store, status="failed"),
        "no_revision": await _make(session_factory, store, status=None),
    }
    ok = await client.request(method, path.format(document_id=allowed), cookies=cookies)
    assert ok.status_code == 200
    for cause, doc_id in hidden.items():
        response = await client.request(method, path.format(document_id=doc_id), cookies=cookies)
        assert response.status_code == 404, f"{method} {path} leaked a {cause} document"
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_m2_ac06_list_route_applies_the_predicate_matrix(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    app: tuple[FastAPI, FakeObjectStore],
) -> None:
    store = app[1]
    allowed = await _make(session_factory, store)
    for kwargs in (
        {"allowed": ("engineering",)},
        {"deleted": True},
        {"status": "queued"},
        {"status": "processing"},
        {"status": "failed"},
        {"status": None},
    ):
        await _make(session_factory, store, **kwargs)
    response = await client.get("/v1/documents", cookies=cookies)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(allowed)]
