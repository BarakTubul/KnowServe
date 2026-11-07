"""M2-02: GET /v1/documents (M2-AC01, AC02, AC04, AC05, AC07, AC11; DOC-01, 03, 05, 07, 08, 10).

Real ``create_app``, real session rows and PostgreSQL; the department always comes from the session.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.app import create_app
from knowserve_core.clock import FakeClock
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS, make_document

pytestmark = [pytest.mark.m2, pytest.mark.documents, pytest.mark.api, pytest.mark.integration]

FIN = uuid.UUID(DEPARTMENT_IDS["finance"])
ENG = uuid.UUID(DEPARTMENT_IDS["engineering"])
BASE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, clock: FakeClock) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        api_allowed_origins=["http://localhost:5173"],
    )
    app = create_app(settings, engine=engine, clock=clock)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def fin_cookie(make_user: Any, make_session: Any) -> dict[str, str]:
    user = await make_user("registered")
    return (await make_session(user, department_id=FIN)).cookies


def _c(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


async def get(client: httpx.AsyncClient, cookies: dict[str, str], **params: Any) -> httpx.Response:
    return await client.get("/v1/documents", params=params, headers={"Cookie": _c(cookies)})


async def page_all(client: httpx.AsyncClient, cookies: dict[str, str], **params: Any) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    for _ in range(50):
        extra = {"cursor": cursor} if cursor else {}
        body = (await get(client, cookies, **params, **extra)).json()
        ids += [i["id"] for i in body["items"]]
        if not body["has_more"]:
            assert body["next_cursor"] is None
            return ids
        cursor = body["next_cursor"]
    raise AssertionError("pagination did not terminate")


async def test_doc01_states_matrix_lists_only_ready_current_revisions(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        ok = await make_document(s, status="ready", title="Visible", page_count=7)
        for st in ("queued", "processing", "failed"):
            await make_document(s, status=st)
        await make_document(s, status="ready", deleted=True)
        await make_document(s, status=None)
        await s.commit()
    body = (await get(client, fin_cookie)).json()
    assert [i["id"] for i in body["items"]] == [str(ok.id)]
    item = body["items"][0]
    assert item["title"] == "Visible" and item["page_count"] == 7
    assert item["owner_department"]["id"] == str(FIN)
    assert item["owner_department"]["name"]
    assert body["has_more"] is False and body["next_cursor"] is None
    assert "total" not in body


async def test_sec04_owner_a_allowed_c_only(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    make_user: Any,
    make_session: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        doc = await make_document(s, owner="finance", allowed=("engineering",))
        await s.commit()
    eng_user = await make_user("registered")
    eng = (await make_session(eng_user, department_id=ENG)).cookies
    assert (await get(client, fin_cookie)).json()["items"] == []
    assert [i["id"] for i in (await get(client, eng)).json()["items"]] == [str(doc.id)]


async def test_sec05_org_wide_with_one_row_removed(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        doc = await make_document(s, allowed=tuple(DEPARTMENT_IDS))
        await s.execute(
            text(
                "DELETE FROM document_department_access WHERE document_id=:d AND department_id=:p"
            ),
            {"d": doc.id, "p": ENG},
        )
        await s.commit()
    for slug, dept in DEPARTMENT_IDS.items():
        user = await make_user("registered")
        cookies = (await make_session(user, department_id=uuid.UUID(dept))).cookies
        ids = [i["id"] for i in (await get(client, cookies)).json()["items"]]
        assert (str(doc.id) in ids) is (slug != "engineering")


async def test_doc07_search_and_owner_filter_intersect_across_pages(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        for n in range(7):
            # Pairs share created_at so the id tiebreaker is exercised.
            at = BASE + timedelta(minutes=n // 2)
            await make_document(s, owner="finance", title=f"Budget plan {n}", created_at=at)
            await make_document(
                s, owner="engineering", allowed=("finance",), title="Budget eng", created_at=at
            )
            await make_document(s, owner="finance", title="Handbook", created_at=at)
        await make_document(
            s, owner="finance", title="Other", filename="BUDGET_file.pdf", created_at=BASE
        )
        await s.commit()
    fin = str(FIN)
    paged = await page_all(client, fin_cookie, q="budget", owner_department_id=fin, limit=3)
    assert len(paged) == len(set(paged)) == 8  # 7 title hits + 1 filename hit
    whole = await page_all(client, fin_cookie, q="budget", owner_department_id=fin, limit=50)
    assert paged == whole
    eng = await page_all(client, fin_cookie, q="budget", owner_department_id=str(ENG), limit=2)
    assert len(eng) == len(set(eng)) == 7


async def test_doc07_like_wildcards_are_literal(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        await make_document(s, title="100% sure")
        await make_document(s, title="plain")
        await s.commit()
    assert len((await get(client, fin_cookie, q="%")).json()["items"]) == 1
    assert len((await get(client, fin_cookie, q="_")).json()["items"]) == 0


async def test_doc08_order_is_created_at_desc_then_id_desc(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        for n in range(5):
            await make_document(s, created_at=BASE + timedelta(seconds=n // 2))
        await s.commit()
    items = (await get(client, fin_cookie)).json()["items"]
    async with session_factory() as s:
        sql = "SELECT id::text FROM documents ORDER BY created_at DESC, id DESC"
        expected = list((await s.execute(text(sql))).scalars().all())
    assert [i["id"] for i in items] == expected


@pytest.mark.parametrize("cursor", ["!!!", "abc", "e30", "W10", "WyJ4IiwieSJd", "x" * 500])
async def test_doc08_tampered_cursor_is_a_controlled_422(
    client: httpx.AsyncClient, fin_cookie: dict[str, str], cursor: str
) -> None:
    r = await get(client, fin_cookie, cursor=cursor)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_doc08_real_cursor_with_edited_payload_is_422(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        for _ in range(3):
            await make_document(s)
        await s.commit()
    cursor = (await get(client, fin_cookie, limit=1)).json()["next_cursor"]
    assert cursor and "=" not in cursor
    assert (await get(client, fin_cookie, cursor=cursor[: len(cursor) // 2])).status_code == 422
    assert (await get(client, fin_cookie, cursor=cursor[:-4] + "~~~~")).status_code == 422


@pytest.mark.parametrize("value", ["nope", "123", "' OR 1=1 --"])
async def test_doc07_malformed_owner_filter_is_422(
    client: httpx.AsyncClient, fin_cookie: dict[str, str], value: str
) -> None:
    r = await get(client, fin_cookie, owner_department_id=value)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("limit", [0, 51, "x"])
async def test_doc08_limit_bounds_are_422(
    client: httpx.AsyncClient, fin_cookie: dict[str, str], limit: Any
) -> None:
    assert (await get(client, fin_cookie, limit=limit)).status_code == 422


async def test_doc08_default_limit_is_20(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        for n in range(21):
            await make_document(s, created_at=BASE + timedelta(seconds=n))
        await s.commit()
    body = (await get(client, fin_cookie)).json()
    assert len(body["items"]) == 20 and body["has_more"] is True and body["next_cursor"]


async def test_m2_ac05_unauthenticated_is_401_before_query_validation(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/v1/documents", params={"cursor": "!!!", "limit": 999})
    assert r.status_code == 401


async def test_m2_ac05_admin_without_department_gets_409_before_query_validation(
    client: httpx.AsyncClient, make_user: Any, make_session: Any
) -> None:
    admin = await make_user("admin")
    cookies = (await make_session(admin, department_id=None)).cookies
    r = await get(client, cookies, cursor="!!!", owner_department_id="bad")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ACTIVE_DEPARTMENT_REQUIRED"


async def test_sec06_department_in_the_request_is_ignored(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        await make_document(s, owner="engineering", allowed=("engineering",))
        await s.commit()
    r = await client.get(
        "/v1/documents",
        params={"department_id": str(ENG), "active_department_id": str(ENG)},
        headers={"Cookie": _c(fin_cookie), "X-Department-Id": str(ENG)},
    )
    assert r.json()["items"] == []


async def test_sec05_revoke_between_two_pages(
    client: httpx.AsyncClient,
    fin_cookie: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        docs = [await make_document(s, created_at=BASE + timedelta(seconds=n)) for n in range(4)]
        await s.commit()
    first = (await get(client, fin_cookie, limit=2)).json()
    assert [i["id"] for i in first["items"]] == [str(docs[3].id), str(docs[2].id)]
    assert first["has_more"]
    async with session_factory() as s:
        await s.execute(
            text(
                "DELETE FROM document_department_access WHERE document_id=:d AND department_id=:p"
            ),
            {"d": docs[0].id, "p": FIN},
        )
        await s.commit()
    second = (await get(client, fin_cookie, limit=2, cursor=first["next_cursor"])).json()
    assert [i["id"] for i in second["items"]] == [str(docs[1].id)]
    assert second["has_more"] is False
