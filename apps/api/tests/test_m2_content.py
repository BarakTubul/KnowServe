"""M2-03: document metadata and bytes routes (DOC-04, 05, 09, 10, 11; SEC-02, 06; M2-AC03, 05, 08).

Real ``create_app``, real sessions and PostgreSQL, ``FakeObjectStore`` for the bytes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.app import create_app
from knowserve_api.documents.router import RangeUnsatisfiable, resolve_range, safe_filename
from knowserve_core.clock import FakeClock
from knowserve_core.object_store import (
    ByteRange,
    FakeObjectStore,
    ObjectStoreError,
)
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS, make_document

pytestmark = [pytest.mark.m2, pytest.mark.documents, pytest.mark.api, pytest.mark.integration]

FIN = uuid.UUID(DEPARTMENT_IDS["finance"])
PDF = b"%PDF-1.4\n" + bytes(range(256)) * 8 + b"\n%%EOF\n"  # 2064 bytes, a few non-text bytes
SIZE = len(PDF)


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        api_allowed_origins=["http://localhost:5173"],
    )


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, clock: FakeClock, store: FakeObjectStore) -> FastAPI:
    return create_app(
        _settings(),
        engine=engine,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=store,
    )


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def cookies(make_user: Any, make_session: Any) -> dict[str, str]:
    user = await make_user("registered", department_id=FIN)
    handle = await make_session(user, department_id=FIN)
    return handle.cookies


async def _doc(
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
    *,
    put: bool = True,
    **kwargs: Any,
) -> uuid.UUID:
    async with session_factory() as s:
        doc = await make_document(s, **kwargs)
        await s.commit()
    if put:
        await store.put(f"documents/{doc.id}/rev.pdf", PDF, "application/pdf")
    return doc.id


# --- 404 uniformity and the check order ---------------------------------------------------------


def _strip(response: httpx.Response) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = response.json()
    body["error"].pop("request_id", None)
    headers = {
        k: v for k, v in response.headers.items() if k not in {"x-request-id", "content-length"}
    }
    return response.status_code, body, headers


@pytest.mark.parametrize("suffix", ["", "/content"])
async def test_doc05_every_cause_gives_the_identical_404(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
    suffix: str,
) -> None:
    allowed = await _doc(session_factory, store)
    ids = {
        "forbidden": await _doc(session_factory, store, allowed=("engineering",)),
        "deleted": await _doc(session_factory, store, deleted=True),
        "queued": await _doc(session_factory, store, status="queued"),
        "failed": await _doc(session_factory, store, status="failed"),
        "no_revision": await _doc(session_factory, store, status=None),
        "unknown": uuid.uuid4(),
        "malformed": "not-a-uuid",
        "empty-ish": "0",
    }
    ok = await client.get(f"/v1/documents/{allowed}{suffix}", cookies=cookies)
    assert ok.status_code == 200
    results = {
        cause: _strip(await client.get(f"/v1/documents/{doc_id}{suffix}", cookies=cookies))
        for cause, doc_id in ids.items()
    }
    first = next(iter(results.values()))
    assert first[0] == 404
    assert first[1]["error"] == {
        "code": "DOCUMENT_NOT_FOUND",
        "message": "This document is not available.",
    }
    assert all(r == first for r in results.values()), results


async def test_sec01_no_session_is_401_and_no_department_is_409(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store)
    for suffix in ("", "/content"):
        assert (await client.get(f"/v1/documents/{doc}{suffix}")).status_code == 401
    user = await make_user("registered")
    handle = await make_session(user, department_id=None)
    for suffix in ("", "/content"):
        r = await client.get(f"/v1/documents/{doc}{suffix}", cookies=handle.cookies)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ACTIVE_DEPARTMENT_REQUIRED"


async def test_sec17_owner_label_and_admin_kind_grant_nothing(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store, owner="finance", allowed=("engineering",))
    admin = await make_user("admin", department_id=FIN)
    cookies = (await make_session(admin, department_id=FIN)).cookies
    for suffix in ("", "/content"):
        assert (
            await client.get(f"/v1/documents/{doc}{suffix}", cookies=cookies)
        ).status_code == 404


# --- metadata and page validation ---------------------------------------------------------------


async def test_doc09_metadata_and_page_validation(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store, title="Handbook", filename="h.pdf", page_count=3)
    ok = await client.get(f"/v1/documents/{doc}", cookies=cookies)
    assert ok.status_code == 200
    body = ok.json()
    assert body["id"] == str(doc)
    assert body["title"] == "Handbook"
    assert body["filename"] == "h.pdf"
    assert body["page_count"] == 3
    assert body["owner_department"]["id"] == str(FIN)
    assert body["owner_department"]["name"]
    assert (await client.get(f"/v1/documents/{doc}?page=3", cookies=cookies)).status_code == 200
    for bad in ("0", "4", "-1", "abc"):
        r = await client.get(f"/v1/documents/{doc}?page={bad}", cookies=cookies)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_doc09_page_check_runs_only_after_the_visibility_lookup(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    hidden = await _doc(session_factory, store, allowed=("engineering",), page_count=3)
    plain = _strip(await client.get(f"/v1/documents/{hidden}", cookies=cookies))
    with_page = _strip(await client.get(f"/v1/documents/{hidden}?page=999", cookies=cookies))
    assert plain[0] == 404
    assert with_page == plain


async def test_doc09_metadata_exposes_no_storage_fields(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store)
    r = await client.get(f"/v1/documents/{doc}", cookies=cookies)
    assert set(r.json()) == {"id", "title", "filename", "owner_department", "page_count"}
    assert "storage" not in r.text and "documents/" not in r.text and "http" not in r.text


# --- bytes, headers, no storage leak ------------------------------------------------------------


async def test_doc04_streams_the_pdf_with_safe_headers_and_no_storage_url(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store, filename='Q3 "plan"/..\\é\r\n.pdf')
    r = await client.get(f"/v1/documents/{doc}/content", cookies=cookies)
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-length"] == str(SIZE)
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("inline; filename=")
    assert disposition == 'inline; filename="_.pdf"' or ".." not in disposition
    for ch in ('"/', "\\", "\r", "\n"):
        assert ch not in disposition.removeprefix('inline; filename="').removesuffix('"')
    joined = " ".join(f"{k}: {v}" for k, v in r.headers.items())
    for needle in ("http", "r2.", "cloudflarestorage", f"documents/{doc}", "rev.pdf", "X-Amz"):
        assert needle.lower() not in joined.lower()


async def test_doc04_range_header_set_is_identical_on_the_not_found_path(
    client: httpx.AsyncClient, cookies: dict[str, str]
) -> None:
    r = await client.get(f"/v1/documents/{uuid.uuid4()}/content", cookies=cookies)
    assert r.status_code == 404
    assert "content-range" not in r.headers and "etag" not in r.headers


def test_doc04_filename_sanitizer() -> None:
    assert safe_filename("Report 2026.pdf") == "Report 2026.pdf"
    assert safe_filename('a"b\r\nc') == "a_b__c.pdf"
    assert safe_filename("../../etc/passwd") == "passwd.pdf"
    assert safe_filename("C:\\dir\\x.PDF") == "x.PDF"
    assert safe_filename("é.pdf") == "_.pdf"
    assert safe_filename("...") == "document.pdf"
    assert safe_filename("") == "document.pdf"


# --- revocation ---------------------------------------------------------------------------------


async def test_doc10_revoke_then_fetch_and_soft_delete_apply_on_the_next_request(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    revoked = await _doc(session_factory, store)
    deleted = await _doc(session_factory, store)
    for doc in (revoked, deleted):
        assert (
            await client.get(f"/v1/documents/{doc}/content", cookies=cookies)
        ).status_code == 200
        assert (await client.get(f"/v1/documents/{doc}", cookies=cookies)).status_code == 200
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM document_department_access WHERE document_id = :d"), {"d": revoked}
        )
        await conn.execute(
            text("UPDATE documents SET deleted_at = now() WHERE id = :d"), {"d": deleted}
        )
    for doc in (revoked, deleted):
        for suffix in ("", "/content"):
            r = await client.get(f"/v1/documents/{doc}{suffix}", cookies=cookies)
            assert r.status_code == 404, (doc, suffix)


async def test_doc11_revoke_between_two_range_requests(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store)
    first = await client.get(
        f"/v1/documents/{doc}/content", cookies=cookies, headers={"Range": "bytes=0-9"}
    )
    assert first.status_code == 206
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM document_department_access WHERE document_id = :d"), {"d": doc}
        )
    second = await client.get(
        f"/v1/documents/{doc}/content", cookies=cookies, headers={"Range": "bytes=10-19"}
    )
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


# --- the range matrix ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [
        ("bytes=0-0", 0, 0),
        ("bytes=0-9", 0, 9),
        ("bytes=10-", 10, SIZE - 1),
        ("bytes=-5", SIZE - 5, SIZE - 1),
        ("bytes=-999999", 0, SIZE - 1),
        ("bytes=2000-999999", 2000, SIZE - 1),
        (f"bytes={SIZE - 1}-{SIZE - 1}", SIZE - 1, SIZE - 1),
        ("bytes=0-", 0, SIZE - 1),
    ],
)
async def test_doc11_valid_single_range_gives_206(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
    header: str,
    start: int,
    end: int,
) -> None:
    doc = await _doc(session_factory, store)
    r = await client.get(f"/v1/documents/{doc}/content", cookies=cookies, headers={"Range": header})
    assert r.status_code == 206
    assert r.content == PDF[start : end + 1]
    assert r.headers["content-range"] == f"bytes {start}-{end}/{SIZE}"
    assert r.headers["content-length"] == str(end - start + 1)
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-type"] == "application/pdf"


@pytest.mark.parametrize("header", [f"bytes={SIZE}-", f"bytes={SIZE + 10}-{SIZE + 20}", "bytes=-0"])
async def test_doc11_unsatisfiable_range_gives_416(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
    header: str,
) -> None:
    doc = await _doc(session_factory, store)
    r = await client.get(f"/v1/documents/{doc}/content", cookies=cookies, headers={"Range": header})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{SIZE}"
    assert r.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"


@pytest.mark.parametrize(
    "header",
    ["bytes=0-1,5-9", "bytes=5-2", "items=0-5", "bytes=", "bytes=-", "garbage", "bytes=a-b"],
)
async def test_doc11_multiple_or_malformed_ranges_are_ignored_and_serve_the_full_body(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
    header: str,
) -> None:
    doc = await _doc(session_factory, store)
    r = await client.get(f"/v1/documents/{doc}/content", cookies=cookies, headers={"Range": header})
    assert r.status_code == 200
    assert r.content == PDF
    assert "content-range" not in r.headers


async def test_doc11_if_range_matches_etag_or_falls_back_to_the_full_body(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store)
    url = f"/v1/documents/{doc}/content"
    etag = (await client.get(url, cookies=cookies)).headers["etag"]
    match = await client.get(url, cookies=cookies, headers={"Range": "bytes=0-9", "If-Range": etag})
    assert match.status_code == 206 and match.content == PDF[:10]
    for validator in ('"other"', f"W/{etag}", "Wed, 21 Oct 2015 07:28:00 GMT"):
        stale = await client.get(
            url, cookies=cookies, headers={"Range": "bytes=0-9", "If-Range": validator}
        )
        assert stale.status_code == 200 and stale.content == PDF, validator
    # An unsatisfiable range with a stale validator is a plain 200, not a 416.
    stale = await client.get(
        url, cookies=cookies, headers={"Range": f"bytes={SIZE + 5}-", "If-Range": '"other"'}
    )
    assert stale.status_code == 200


async def test_doc11_range_on_a_forbidden_document_is_the_uniform_404_not_416(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    hidden = await _doc(session_factory, store, allowed=("engineering",))
    r = await client.get(
        f"/v1/documents/{hidden}/content",
        cookies=cookies,
        headers={"Range": f"bytes={SIZE + 100}-"},
    )
    assert r.status_code == 404
    assert "content-range" not in r.headers


def test_doc11_resolve_range_unit() -> None:
    assert resolve_range(None, 10) is None
    assert resolve_range("bytes=2-4", 10) == ByteRange(2, 4)
    assert resolve_range("bytes=2-99", 10) == ByteRange(2, 9)
    assert resolve_range("bytes=-3", 10) == ByteRange(7, 9)
    with pytest.raises(RangeUnsatisfiable):
        resolve_range("bytes=10-", 10)
    with pytest.raises(RangeUnsatisfiable):
        resolve_range("bytes=0-1", 0)
    with pytest.raises(RangeUnsatisfiable):
        resolve_range("bytes=-1", 0)
    assert resolve_range("bytes=0-1,3-4", 10) is None


# --- storage failures ---------------------------------------------------------------------------


async def test_doc05_ready_revision_with_missing_bytes_is_the_uniform_404(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store, put=False)
    r = await client.get(f"/v1/documents/{doc}/content", cookies=cookies)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_sec13_store_outage_is_503_without_storage_details(
    app: FastAPI,
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
) -> None:
    doc = await _doc(session_factory, store)

    class Down(FakeObjectStore):
        async def size(self, key: str) -> int:
            raise ObjectStoreError("https://secret-host.r2.cloudflarestorage.com/b/k failed")

    app.state.object_store = Down()
    r = await client.get(f"/v1/documents/{doc}/content", cookies=cookies)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "secret-host" not in r.text


# --- log hygiene --------------------------------------------------------------------------------


async def test_mon05_routes_log_no_cookie_content_or_storage_details(
    client: httpx.AsyncClient,
    cookies: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    store: FakeObjectStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    doc = await _doc(session_factory, store)
    hidden = await _doc(session_factory, store, allowed=("engineering",))
    for url, headers in (
        (f"/v1/documents/{doc}", {}),
        (f"/v1/documents/{doc}/content", {}),
        (f"/v1/documents/{doc}/content", {"Range": "bytes=0-9"}),
        (f"/v1/documents/{doc}/content", {"Range": "bytes=99999-"}),
        (f"/v1/documents/{hidden}/content", {}),
        ("/v1/documents/not-a-uuid/content", {}),
    ):
        await client.get(url, cookies=cookies, headers=headers)
    token = cookies["ks_session"]
    assert token not in caplog.text
    assert "%PDF" not in caplog.text
    for needle in ("rev.pdf", "cloudflarestorage", "Authorization", "X-Amz"):
        assert needle not in caplog.text


# --- startup guard ------------------------------------------------------------------------------


def _prod(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "env": "production",
        "api_allowed_origins": ["https://app.example.test"],
        "proxy_shared_secret": "s" * 32,
        "firebase_project_id": "knowserve-test",
    }
    values.update(over)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({}, "KS_OBJECT_STORE='filesystem'"),
        ({"object_store": "fake"}, "KS_OBJECT_STORE='fake'"),
        ({"object_store": "r2"}, "KS_R2_ENDPOINT"),
        (
            {"object_store": "r2", "r2_endpoint": "https://x.r2.cloudflarestorage.com"},
            "KS_R2_BUCKET",
        ),
    ],
)
def test_m2_production_refuses_to_start_without_a_real_object_store(
    over: dict[str, Any], needle: str
) -> None:
    with pytest.raises(RuntimeError, match="refuses to start") as excinfo:
        create_app(_prod(**over))
    assert needle in str(excinfo.value)


def test_m2_production_error_never_prints_secret_values() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        create_app(_prod(object_store="r2", r2_secret_access_key="topsecretvalue"))
    assert "topsecretvalue" not in str(excinfo.value)
