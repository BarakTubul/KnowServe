"""M3-01 tests: the Admin API contract (docs/contracts/admin-api.md).

A structural walk fails when an Admin route appears that is not registered here, so no route ships
without a row in the authorization matrix (M3-AC02). A behavioural walk then runs every route as
anonymous, Demo, registered and Admin users, with and without CSRF. The routes are 501 stubs until
their slices land; the guards, the upload switch and the OpenAPI shape are already real.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_api.app import create_app
from knowserve_core.clock import FakeClock
from knowserve_core.ingestion_contract import AdminErrorCode, FailureCode
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing_fixtures import pdf_two_pages

pytestmark = [pytest.mark.m3, pytest.mark.admin, pytest.mark.api, pytest.mark.integration]

DOC = "00000000-0000-4000-8000-000000000001"
FIN = "00000000-0000-4000-8000-0000000000f1"
KEY = {"Idempotency-Key": "test-key-0001-abcd"}

# (method, path template, writes?, produces uploads?). Anything else under /v1/admin fails the walk.
ROUTES: tuple[tuple[str, str, bool, bool], ...] = (
    ("GET", "/v1/admin/ping", False, False),
    ("GET", "/v1/admin/documents", False, False),
    ("POST", "/v1/admin/documents", True, True),
    ("GET", "/v1/admin/documents/{document_id}", False, False),
    ("GET", "/v1/admin/documents/{document_id}/events", False, False),
    ("PATCH", "/v1/admin/documents/{document_id}/access", True, False),
    ("DELETE", "/v1/admin/documents/{document_id}", True, False),
    ("POST", "/v1/admin/documents/{document_id}/retry", True, False),
    ("POST", "/v1/admin/documents/{document_id}/replace", True, True),
    ("POST", "/v1/admin/imports/preview", True, True),
    ("POST", "/v1/admin/imports/confirm", True, True),
)
STUBS = [r for r in ROUTES if r[1] != "/v1/admin/ping"]


def _app(engine: AsyncEngine, clock: FakeClock, **overrides: Any) -> FastAPI:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        api_allowed_origins=["http://localhost:5173"],
        **overrides,
    )
    return create_app(
        settings,
        engine=engine,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=FakeObjectStore(),
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, clock: FakeClock) -> FastAPI:
    return _app(engine, clock)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app) as c:
        yield c


def _request_kwargs(method: str, path: str) -> dict[str, Any]:
    """A request that is valid for the stub's own validation, so auth is what decides."""
    kwargs: dict[str, Any] = {}
    if path.endswith("/access"):
        kwargs["json"] = {"allowed_department_ids": [FIN]}
    elif method == "POST" and path.endswith(("/documents", "/replace")):
        kwargs["files"] = {"file": ("a.pdf", pdf_two_pages(), "application/pdf")}
        kwargs["headers"] = dict(KEY)
        if path.endswith("/documents"):
            kwargs["data"] = {
                "title": "T",
                "owner_department_id": FIN,
                "allowed_department_ids": FIN,
            }
    elif method == "POST" and "/imports/" in path:
        kwargs["files"] = {"file": ("a.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")}
        if path.endswith("/confirm"):
            kwargs["headers"] = dict(KEY)
    return kwargs


async def _call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    session: Any = None,
    csrf: bool = True,
    origin: str | None = None,
) -> httpx.Response:
    kwargs = _request_kwargs(method, path)
    headers = dict(kwargs.pop("headers", {}))
    cookies = None
    if session is not None:
        cookies = session.cookies
        if csrf:
            headers["X-CSRF-Token"] = session.csrf_token
        headers["Origin"] = origin or "http://localhost:5173"
    return await client.request(
        method, path.format(document_id=DOC), headers=headers, cookies=cookies, **kwargs
    )


def _admin_routes(app: FastAPI) -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/v1/admin")
        for method in operations
    }


async def test_m3_ac02_no_unregistered_admin_route(app: FastAPI) -> None:
    assert _admin_routes(app) == {(m, p) for m, p, _, _ in ROUTES}


@pytest.mark.parametrize(("method", "path", "writes", "uploads"), ROUTES)
async def test_m3_ac02_admin_routes_need_a_session_and_the_admin_role(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    method: str,
    path: str,
    writes: bool,
    uploads: bool,
) -> None:
    anonymous = await _call(client, method, path)
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "UNAUTHENTICATED"
    for kind in ("demo", "registered"):
        session = await make_session(await make_user(kind))
        denied = await _call(client, method, path, session=session)
        assert denied.status_code == 403, f"{method} {path} allowed a {kind} user"
        assert denied.json()["error"]["code"] in ("FORBIDDEN", "CSRF_INVALID", "ORIGIN_INVALID")


@pytest.mark.parametrize(("method", "path", "writes", "uploads"), STUBS)
async def test_m3_ac02_admin_reaches_the_stub_and_gets_501(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    method: str,
    path: str,
    writes: bool,
    uploads: bool,
) -> None:
    admin = await make_session(await make_user("admin"))
    response = await _call(client, method, path, session=admin)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, writes, _ in ROUTES if writes])
async def test_m3_auth14_admin_mutations_need_the_csrf_token_and_an_allowed_origin(
    client: httpx.AsyncClient, make_user: Any, make_session: Any, method: str, path: str
) -> None:
    admin = await make_session(await make_user("admin"))
    no_csrf = await _call(client, method, path, session=admin, csrf=False)
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "CSRF_INVALID"
    bad_origin = await _call(client, method, path, session=admin, origin="https://evil.example")
    assert bad_origin.status_code == 403
    assert bad_origin.json()["error"]["code"] == "ORIGIN_INVALID"


async def test_m3_sec17_admin_routes_need_no_active_department(
    client: httpx.AsyncClient, make_user: Any, make_session: Any
) -> None:
    admin = await make_session(await make_user("admin"), department_id=None)
    response = await _call(client, "GET", "/v1/admin/documents", session=admin)
    assert response.status_code == 501  # not 409 ACTIVE_DEPARTMENT_REQUIRED


# --- KS_UPLOADS_ENABLED (OPEN-31 D14, M3-AC26) ---


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _, uploads in STUBS if uploads])
async def test_m3_ac26_disabled_uploads_answer_503_on_upload_producing_routes(
    engine: AsyncEngine, clock: FakeClock, make_user: Any, make_session: Any, method: str, path: str
) -> None:
    async with _client(_app(engine, clock, uploads_enabled=False)) as client:
        admin = await make_session(await make_user("admin"))
        response = await _call(client, method, path, session=admin)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "UPLOADS_DISABLED"
        # Authorization still comes first: a registered user learns nothing about the switch.
        user = await make_session(await make_user("registered"))
        assert (await _call(client, method, path, session=user)).status_code == 403
        assert (await _call(client, method, path)).status_code == 401


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _, uploads in STUBS if not uploads])
async def test_m3_ac26_disabled_uploads_leave_reads_access_delete_and_retry_alone(
    engine: AsyncEngine, clock: FakeClock, make_user: Any, make_session: Any, method: str, path: str
) -> None:
    async with _client(_app(engine, clock, uploads_enabled=False)) as client:
        admin = await make_session(await make_user("admin"))
        response = await _call(client, method, path, session=admin)
        assert response.status_code == 501  # the stub, not 503


# --- Contract shape ---


async def test_m3_openapi_lists_every_error_and_failure_code(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["AdminErrorCode"]["enum"]) == {c.value for c in AdminErrorCode}
    assert set(schemas["FailureCode"]["enum"]) == {c.value for c in FailureCode}
    phase = next(
        option
        for option in schemas["AdminDocumentOut"]["properties"]["phase"]["anyOf"]
        if "enum" in option
    )
    assert set(phase["enum"]) == {
        "fetching",
        "extracting",
        "chunking",
        "embedding",
        "publishing",
    }


async def test_m3_openapi_upload_routes_require_the_idempotency_key_and_multipart(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/v1/admin/documents",
        "/v1/admin/documents/{document_id}/replace",
        "/v1/admin/imports/confirm",
    ):
        operation = paths[path]["post"]
        header = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
        assert header["in"] == "header" and header["required"] is True
        assert "multipart/form-data" in operation["requestBody"]["content"]
    preview = paths["/v1/admin/imports/preview"]["post"]
    assert not [p for p in preview.get("parameters", []) if p["name"] == "Idempotency-Key"]
    assert (
        "text/event-stream"
        in paths["/v1/admin/documents/{document_id}/events"]["get"]["responses"]["200"]["content"]
    )


async def test_m3_idempotency_key_format_is_validated(
    client: httpx.AsyncClient, make_user: Any, make_session: Any
) -> None:
    admin = await make_session(await make_user("admin"))
    kwargs = _request_kwargs("POST", "/v1/admin/documents")
    kwargs["headers"] = {"Idempotency-Key": "short"}
    response = await client.post(
        "/v1/admin/documents",
        headers={
            **kwargs.pop("headers"),
            "X-CSRF-Token": admin.csrf_token,
            "Origin": admin.headers["Origin"],
        },
        cookies=admin.cookies,
        **kwargs,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_m3_access_update_accepts_an_empty_list_so_the_route_can_return_its_own_code(
    app: FastAPI,
) -> None:
    body = app.openapi()["components"]["schemas"]["AccessUpdateRequest"]
    assert "minItems" not in body["properties"]["allowed_department_ids"]
    assert uuid.UUID(DOC)
