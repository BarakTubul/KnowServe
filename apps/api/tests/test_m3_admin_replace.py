"""M3-05b: replace the file of a failed document (ADM-18, M3-AC12).

Real ``create_app``, real PostgreSQL, fake publisher and object store. Hard gates, no skips.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from test_m3_admin_manage import (  # type: ignore[import-not-found]
    ENG,
    FIN,
    SECRET_FILENAME,
    SECRET_TITLE,
    Factory,
    _settings,
    access_of,
    count,
    make_doc,
    sql,
)

from knowserve_api.app import create_app
from knowserve_core.clock import FakeClock
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.qstash import FakePublisher
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.testing_fixtures import not_a_pdf, pdf_image_only, pdf_two_pages

pytestmark = [pytest.mark.m3, pytest.mark.admin, pytest.mark.api, pytest.mark.integration]


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest_asyncio.fixture
async def app(
    engine: AsyncEngine, clock: FakeClock, publisher: FakePublisher, store: FakeObjectStore
) -> FastAPI:
    return create_app(
        _settings(),
        engine=engine,
        publisher=publisher,
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
async def admin(make_user: Any, make_session: Any) -> Any:
    return await make_session(await make_user("admin"), department_id=None)


def replace(
    client: httpx.AsyncClient,
    session: Any,
    doc_id: Any,
    *,
    key: str = "replace-key-0001",
    data: bytes | None = None,
    filename: str = "fixed.pdf",
) -> Any:
    headers = dict(session.headers)
    headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    headers["Idempotency-Key"] = key
    return client.post(
        f"/v1/admin/documents/{doc_id}/replace",
        headers=headers,
        files={
            "file": (filename, data if data is not None else pdf_two_pages(), "application/pdf")
        },
    )


def get(client: httpx.AsyncClient, session: Any, path: str) -> Any:
    cookie = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    return client.get(path, headers={"Cookie": cookie})


async def failed_doc(factory: Factory, publisher: FakePublisher, **kwargs: Any) -> uuid.UUID:
    return await make_doc(
        factory,
        publisher,
        status="failed",
        failure="NO_EXTRACTABLE_TEXT",
        job="failed",
        allowed=("finance", "legal"),
        **kwargs,
    )


async def revisions(factory: Factory, doc_id: uuid.UUID) -> list[tuple[str, str]]:
    from sqlalchemy import text

    async with factory() as s:
        rows = await s.execute(
            text(
                "SELECT id::text, status FROM document_revisions "
                "WHERE document_id = :d ORDER BY created_at, id"
            ),
            {"d": doc_id},
        )
        return [(r[0], r[1]) for r in rows]


async def test_adm18_replacement_keeps_identity_owner_and_access_and_starts_one_attempt(
    client: httpx.AsyncClient,
    admin: Any,
    make_user: Any,
    make_session: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    store: FakeObjectStore,
) -> None:
    doc_id = await failed_doc(session_factory, publisher, owner="engineering")
    before_revisions = await revisions(session_factory, doc_id)
    access_before = await access_of(session_factory, doc_id)
    jobs_before = await count(session_factory, "jobs")
    published_before = len(publisher.published)

    response = await replace(client, admin, doc_id)
    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == str(doc_id)
    assert body["status"] == "queued" and body["failure_code"] is None
    assert body["owner_department"]["slug"] == "engineering"
    assert {d["slug"] for d in body["allowed_departments"]} == {"finance", "legal"}
    assert body["can_retry"] is False and body["can_replace"] is False
    new_id = body["revision_id"]
    assert new_id not in {r[0] for r in before_revisions}

    after = await revisions(session_factory, doc_id)
    assert len(after) == len(before_revisions) + 1
    assert dict(after)[new_id] == "queued"
    assert [s for i, s in after if i != new_id] == ["failed"]  # the failed one stays as it was
    assert await access_of(session_factory, doc_id) == access_before
    assert await count(session_factory, "jobs") == jobs_before + 1
    assert len(publisher.published) == published_before + 1
    assert await store.size(f"documents/{doc_id}/{new_id}.pdf") > 0
    assert await count(session_factory, "audit_events", "event = 'admin.document.replaced'") == 1

    # The detail shows the new attempt, and no user route shows the document yet (SEC-07).
    detail = (await get(client, admin, f"/v1/admin/documents/{doc_id}")).json()
    assert detail["revision_id"] == new_id and detail["status"] == "queued"
    fin = await make_session(await make_user("registered"), department_id=FIN)
    listing = (await get(client, fin, "/v1/documents")).json()
    assert str(doc_id) not in {i["id"] for i in listing["items"]}
    assert (await get(client, fin, f"/v1/documents/{doc_id}")).status_code == 404


async def test_adm18_same_key_replays_the_first_result_and_another_file_is_409(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await failed_doc(session_factory, publisher)
    first = await replace(client, admin, doc_id)
    assert first.status_code == 202
    published = len(publisher.published)
    again = await replace(client, admin, doc_id)  # same key, same file; the document is queued now
    assert again.status_code == 202 and again.json() == first.json()
    assert len(await revisions(session_factory, doc_id)) == 2
    assert len(publisher.published) == published
    other = await replace(client, admin, doc_id, data=pdf_image_only())
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(await revisions(session_factory, doc_id)) == 2


@pytest.mark.parametrize(
    ("status", "job"), [("ready", "done"), ("queued", "queued"), ("processing", "processing")]
)
async def test_adm18_documents_that_are_not_failed_are_409_and_nothing_changes(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    store: FakeObjectStore,
    status: str,
    job: str,
) -> None:
    doc_id = await make_doc(session_factory, publisher, status=status, job=job)
    published = len(publisher.published)
    response = await replace(client, admin, doc_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_REPLACEABLE"
    assert len(await revisions(session_factory, doc_id)) == 1
    assert await count(session_factory, "jobs") == 1
    assert len(publisher.published) == published
    assert not store._objects  # type: ignore[attr-defined]


async def test_adm18_a_failed_document_with_a_current_revision_or_an_active_job_is_409(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    with_current = await make_doc(
        session_factory,
        publisher,
        status="failed",
        failure="INTERNAL_ERROR",
        job="failed",
        current=True,
    )
    retried = await make_doc(
        session_factory, publisher, status="failed", failure="INTERNAL_ERROR", job="queued"
    )
    for doc_id in (with_current, retried):
        response = await replace(client, admin, doc_id)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_REPLACEABLE"
        assert len(await revisions(session_factory, doc_id)) == 1


async def test_adm18_unknown_and_deleted_documents_are_404(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    gone = await failed_doc(session_factory, publisher, deleted=True)
    for target in (uuid.uuid4(), gone):
        response = await replace(client, admin, target)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert len(await revisions(session_factory, gone)) == 1


@pytest.mark.parametrize("kind", ["not_a_pdf", "empty", "bad_name"])
async def test_adm18_invalid_files_are_422_and_the_document_stays_failed(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    store: FakeObjectStore,
    kind: str,
) -> None:
    doc_id = await failed_doc(session_factory, publisher)
    data = {"not_a_pdf": not_a_pdf(), "empty": b"", "bad_name": pdf_two_pages()}[kind]
    filename = "../../etc/x.exe" if kind == "bad_name" else "ok.pdf"
    response = await replace(client, admin, doc_id, data=data, filename=filename)
    assert response.status_code == 422
    assert await revisions(session_factory, doc_id) == [
        (r[0], "failed") for r in await revisions(session_factory, doc_id)
    ]
    assert len(await revisions(session_factory, doc_id)) == 1
    assert await count(session_factory, "jobs") == 1
    assert not store._objects  # type: ignore[attr-defined]
    detail = (await get(client, admin, f"/v1/admin/documents/{doc_id}")).json()
    assert detail["status"] == "failed" and detail["can_replace"] is True


async def test_adm18_oversize_file_is_413(
    engine: AsyncEngine,
    clock: FakeClock,
    publisher: FakePublisher,
    admin: Any,
    session_factory: Factory,
) -> None:
    app = create_app(
        _settings(upload_max_pdf_bytes=1024),
        engine=engine,
        publisher=publisher,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=FakeObjectStore(),
    )
    doc_id = await failed_doc(session_factory, publisher)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        response = await replace(c, admin, doc_id, data=pdf_two_pages() + b"0" * 4096)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert len(await revisions(session_factory, doc_id)) == 1


async def test_adm18_concurrent_replacements_start_exactly_one_attempt(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    store: FakeObjectStore,
) -> None:
    doc_id = await failed_doc(session_factory, publisher)
    published = len(publisher.published)
    results = await asyncio.gather(
        *[replace(client, admin, doc_id, key=f"replace-key-race-{i}") for i in range(4)]
    )
    assert sorted(r.status_code for r in results) == [202, 409, 409, 409]
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {
        "DOCUMENT_NOT_REPLACEABLE"
    }
    assert len(await revisions(session_factory, doc_id)) == 2
    assert await count(session_factory, "jobs") == 2
    assert len(publisher.published) == published + 1
    assert len(store._objects) == 1  # type: ignore[attr-defined]  # losers removed their objects


async def test_adm18_retry_and_replace_cannot_both_start_an_attempt(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await failed_doc(session_factory, publisher)
    headers = dict(admin.headers)
    headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in admin.cookies.items())
    retry, repl = await asyncio.gather(
        client.post(f"/v1/admin/documents/{doc_id}/retry", headers=headers),
        replace(client, admin, doc_id),
    )
    # Exactly one starts an attempt: if the retry wins, the job is queued and the replacement is
    # 409; if the replacement wins, retry targets the new queued job and is 409.
    assert sorted([retry.status_code, repl.status_code]) == [202, 409]


async def test_adm18_a_second_failure_can_be_replaced_again(
    client: httpx.AsyncClient,
    admin: Any,
    clock: FakeClock,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await failed_doc(session_factory, publisher)
    first = (await replace(client, admin, doc_id, key="replace-key-first")).json()
    # The Worker fails the new attempt: job and revision are failed together (M3-AC06).
    await sql(
        session_factory,
        "UPDATE jobs SET status='failed', attempts=3 WHERE id IN "
        "(SELECT job_id FROM document_revisions WHERE id = :r)",
        r=uuid.UUID(first["revision_id"]),
    )
    await sql(
        session_factory,
        "UPDATE document_revisions SET status='failed', failure_reason='INVALID_PDF' WHERE id = :r",
        r=uuid.UUID(first["revision_id"]),
    )
    detail = (await get(client, admin, f"/v1/admin/documents/{doc_id}")).json()
    assert detail["failure_code"] == "INVALID_PDF" and detail["can_replace"] is True
    clock.advance(minutes=5)
    second = await replace(client, admin, doc_id, key="replace-key-second")
    assert second.status_code == 202
    assert second.json()["revision_id"] not in (first["revision_id"],)
    assert len(await revisions(session_factory, doc_id)) == 3


async def test_adm18_audit_and_logs_carry_ids_only(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    from sqlalchemy import text

    doc_id = await failed_doc(
        session_factory, publisher, title=SECRET_TITLE, filename=SECRET_FILENAME
    )
    response = await replace(client, admin, doc_id, filename="secret-replacement-name.pdf")
    assert response.status_code == 202
    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT user_id, ip, details FROM audit_events "
                    "WHERE event = 'admin.document.replaced'"
                )
            )
        ).one()
    assert row.user_id == admin.user_id and row.ip is None
    assert row.details["document_id"] == str(doc_id)
    blob = json.dumps(row.details)
    for forbidden in (
        SECRET_TITLE,
        SECRET_FILENAME,
        "secret-replacement-name",
        "documents/",
        ".pdf",
    ):
        assert forbidden not in blob


async def test_adm18_replacement_does_not_touch_access_even_when_it_was_changed_before(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await failed_doc(session_factory, publisher)
    headers = dict(admin.headers)
    headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in admin.cookies.items())
    await client.patch(
        f"/v1/admin/documents/{doc_id}/access",
        headers=headers,
        json={"allowed_department_ids": [str(ENG)]},
    )
    assert (await replace(client, admin, doc_id)).status_code == 202
    assert await access_of(session_factory, doc_id) == {ENG}


async def test_m3_ac26_replace_is_503_when_uploads_are_disabled(
    engine: AsyncEngine,
    clock: FakeClock,
    publisher: FakePublisher,
    admin: Any,
    session_factory: Factory,
) -> None:
    app = create_app(
        _settings(uploads_enabled=False),
        engine=engine,
        publisher=publisher,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=FakeObjectStore(),
    )
    doc_id = await failed_doc(session_factory, publisher)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        response = await replace(c, admin, doc_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPLOADS_DISABLED"
