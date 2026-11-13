"""M3-05a: Admin document management (list, detail, access, delete, retry, status stream).

Real ``create_app``, real PostgreSQL, fake publisher and object store. Hard gates, no skips:
authorization (ADM-01), no inferred access (ADM-05, SEC-04), delete and retry races (ADM-08,
ADM-16), stream authorization and statelessness (ING-07, ING-11), non-ready states never reach a
user route (SEC-07, LIFE-02, SEC-17) and log hygiene (ADM-17, MON-04).

The requeue hook (M3-00a) that sets a retried revision back to ``queued`` lives in the shared
``job_recovery`` code. These tests assert on the job and its delivery state, which are right with
or without it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.admin import events as events_module
from knowserve_api.admin.document_views import JobWindows, load_status
from knowserve_api.app import create_app
from knowserve_core.clock import FakeClock
from knowserve_core.job_recovery import create_job
from knowserve_core.models import (
    Document,
    DocumentDepartmentAccess,
    DocumentRevision,
)
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.qstash import FakePublisher
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS

pytestmark = [pytest.mark.m3, pytest.mark.admin, pytest.mark.api, pytest.mark.integration]

Factory = async_sessionmaker[AsyncSession]
FIN = uuid.UUID(DEPARTMENT_IDS["finance"])
ENG = uuid.UUID(DEPARTMENT_IDS["engineering"])
LEG = uuid.UUID(DEPARTMENT_IDS["legal"])
HR = uuid.UUID(DEPARTMENT_IDS["human-resources"])
BASE = datetime(2026, 1, 1, tzinfo=UTC)
SECRET_TITLE = "Quarterly layoffs plan"
SECRET_FILENAME = "layoffs-q4-confidential.pdf"
GRACE = 120
STUCK = 2400


def _settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        api_allowed_origins=["http://localhost:5173"],
        **overrides,
    )


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, clock: FakeClock, publisher: FakePublisher) -> FastAPI:
    return create_app(
        _settings(),
        engine=engine,
        publisher=publisher,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=FakeObjectStore(),
    )


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin(make_user: Any, make_session: Any) -> Any:
    """An Admin session with no active department at all (SEC-17)."""
    return await make_session(await make_user("admin"), department_id=None)


# --- fixtures: documents with revisions and jobs ------------------------------------------------


async def sql(factory: Factory, statement: str, **params: Any) -> None:
    async with factory() as s, s.begin():
        await s.execute(text(statement), params)


async def make_doc(
    factory: Factory,
    publisher: FakePublisher | None = None,
    *,
    status: str = "queued",
    job: str | None = None,
    phase: str | None = None,
    failure: str | None = None,
    owner: str = "finance",
    allowed: tuple[str, ...] = ("finance",),
    current: bool | None = None,
    deleted: bool = False,
    title: str = "Leave policy",
    filename: str = "leave-policy.pdf",
    created_at: datetime | None = None,
) -> uuid.UUID:
    """A document with one revision and, unless ``job`` is None, its job.

    ``job`` is the delivery shape: ``queued`` (published), ``processing`` (live lease),
    ``stuck`` (processing, lease expired), ``failed``, ``done`` or ``unpublished`` (a job whose
    API crashed after commit). ``current`` defaults to True only for a ready revision.
    """
    job_id: uuid.UUID | None = None
    if job is not None:
        job_id = await create_job(
            factory,
            publisher if job != "unpublished" else None,
            "noop",
            correlation_id="req_m3_05a",
            publish=job != "unpublished",
        )
        if job == "unpublished":
            await sql(
                factory,
                "UPDATE outbox SET created_at = now() - interval '10 minutes' WHERE job_id = :j",
                j=job_id,
            )
        elif job == "processing":
            await sql(
                factory,
                "UPDATE jobs SET status='processing', claimed_by='w', "
                "lease_expires_at = now() + interval '1 hour' WHERE id = :j",
                j=job_id,
            )
        elif job == "stuck":
            await sql(
                factory,
                "UPDATE jobs SET status='processing', claimed_by='w', "
                "lease_expires_at = now() - interval '1 minute' WHERE id = :j",
                j=job_id,
            )
        elif job in ("failed", "done"):
            await sql(
                factory,
                "UPDATE jobs SET status=:s, attempts=3, completed_at=now() WHERE id = :j",
                s=job,
                j=job_id,
            )
    doc_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    is_current = (status == "ready") if current is None else current
    async with factory() as s, s.begin():
        s.add(
            Document(
                id=doc_id,
                title=title,
                filename=filename,
                owner_department_id=uuid.UUID(DEPARTMENT_IDS[owner]),
                deleted_at=datetime.now(UTC) if deleted else None,
                created_at=created_at or BASE,
                updated_at=created_at or BASE,
            )
        )
        await s.flush()
        for slug in allowed:
            s.add(
                DocumentDepartmentAccess(
                    document_id=doc_id, department_id=uuid.UUID(DEPARTMENT_IDS[slug])
                )
            )
        s.add(
            DocumentRevision(
                id=rev_id,
                document_id=doc_id,
                storage_key=f"documents/{doc_id}/{rev_id}.pdf",
                status=status,
                phase=phase,
                failure_reason=failure,
                page_count=3 if status == "ready" else None,
                size_bytes=2048,
                content_type="application/pdf",
                job_id=job_id,
                created_at=created_at or BASE,
                ready_at=datetime.now(UTC) if status == "ready" else None,
            )
        )
        await s.flush()
        if is_current:
            await s.execute(
                text("UPDATE documents SET current_revision_id = :r WHERE id = :d"),
                {"r": rev_id, "d": doc_id},
            )
    return doc_id


async def count(factory: Factory, table: str, where: str = "true", **params: Any) -> int:
    async with factory() as s:
        return int(
            (await s.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)).scalar()
            or 0
        )


async def access_of(factory: Factory, doc_id: uuid.UUID) -> set[uuid.UUID]:
    async with factory() as s:
        rows = await s.execute(
            text("SELECT department_id FROM document_department_access WHERE document_id = :d"),
            {"d": doc_id},
        )
        return {r[0] for r in rows}


def call(client: httpx.AsyncClient, method: str, path: str, session: Any, **kwargs: Any) -> Any:
    headers = dict(session.headers) if method.upper() not in ("GET", "HEAD") else {}
    headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    return client.request(method, path, headers=headers, **kwargs)


# --- ADM-02, ADM-09, SEC-17: list and detail ---------------------------------------------------


async def test_adm02_list_shows_every_state_with_phase_reason_and_departments(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    q = await make_doc(session_factory, publisher, status="queued", job="queued", title="Q")
    p = await make_doc(
        session_factory,
        publisher,
        status="processing",
        phase="embedding",
        job="processing",
        title="P",
        owner="legal",
        allowed=("legal", "finance"),
    )
    r = await make_doc(session_factory, publisher, status="ready", job="done", title="R")
    f = await make_doc(
        session_factory,
        publisher,
        status="failed",
        failure="NO_EXTRACTABLE_TEXT",
        job="failed",
        title="F",
    )
    response = await call(client, "GET", "/v1/admin/documents", admin)
    assert response.status_code == 200
    items = {item["document_id"]: item for item in response.json()["items"]}
    assert set(items) == {str(q), str(p), str(r), str(f)}
    assert items[str(q)]["status"] == "queued" and items[str(q)]["phase"] is None
    assert items[str(p)]["status"] == "processing" and items[str(p)]["phase"] == "embedding"
    assert items[str(p)]["owner_department"]["slug"] == "legal"
    assert {d["slug"] for d in items[str(p)]["allowed_departments"]} == {"legal", "finance"}
    assert items[str(r)]["status"] == "ready" and items[str(r)]["delivery_state"] is None
    failed = items[str(f)]
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "NO_EXTRACTABLE_TEXT"
    assert "No readable text" in failed["failure_message"]
    assert failed["delivery_state"] == "failed"
    assert failed["filename"] == "leave-policy.pdf" and failed["size_bytes"] == 2048


async def test_m3_sec17_admin_list_ignores_the_active_department_and_hides_deleted(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    ready = await make_doc(
        session_factory, publisher, status="ready", job="done", allowed=("human-resources",)
    )
    gone = await make_doc(session_factory, publisher, status="ready", job="done", deleted=True)
    for department in (None, ENG, FIN):
        session = await make_session(await make_user("admin"), department_id=department)
        body = (await call(client, "GET", "/v1/admin/documents", session)).json()
        ids = {item["document_id"] for item in body["items"]}
        assert str(ready) in ids and str(gone) not in ids


async def test_adm02_detail_shows_the_latest_revision_not_the_current_one(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="ready", job="done")
    new_rev = uuid.uuid4()
    new_job = await create_job(session_factory, publisher, "noop", correlation_id="req_new")
    async with session_factory() as s, s.begin():
        s.add(
            DocumentRevision(
                id=new_rev,
                document_id=doc_id,
                storage_key=f"documents/{doc_id}/{new_rev}.pdf",
                status="processing",
                phase="chunking",
                size_bytes=10,
                content_type="application/pdf",
                job_id=new_job,
                created_at=BASE + timedelta(hours=1),
            )
        )
    body = (await call(client, "GET", f"/v1/admin/documents/{doc_id}", admin)).json()
    assert body["revision_id"] == str(new_rev)
    assert body["status"] == "processing" and body["phase"] == "chunking"


async def test_adm09_list_paging_filters_and_cursor_validation(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    ids = []
    for i in range(5):
        ids.append(
            await make_doc(
                session_factory,
                publisher,
                status="failed" if i % 2 else "queued",
                failure="INVALID_PDF" if i % 2 else None,
                job="failed" if i % 2 else "queued",
                title=f"Doc 50%_{i}" if i == 3 else f"Doc {i}",
                created_at=BASE + timedelta(minutes=i),
            )
        )
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await call(client, "GET", "/v1/admin/documents", admin, params=params)).json()
        seen += [item["document_id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert seen == [str(i) for i in reversed(ids)]  # newest first, no gaps, no repeats

    failed = (
        await call(client, "GET", "/v1/admin/documents", admin, params={"status": "failed"})
    ).json()
    assert {i["document_id"] for i in failed["items"]} == {str(ids[1]), str(ids[3])}
    literal = (await call(client, "GET", "/v1/admin/documents", admin, params={"q": "50%_"})).json()
    assert [i["document_id"] for i in literal["items"]] == [str(ids[3])]  # % and _ are literal
    bad = await call(client, "GET", "/v1/admin/documents", admin, params={"cursor": "nope"})
    assert bad.status_code == 422
    bad_status = await call(client, "GET", "/v1/admin/documents", admin, params={"status": "x"})
    assert bad_status.status_code == 422


@pytest.mark.parametrize(
    ("status", "job", "current", "failure", "can_retry", "can_replace"),
    [
        ("queued", "queued", None, None, False, False),
        ("queued", "unpublished", None, None, True, False),  # lost publish: retry republishes
        ("queued", "stuck", None, None, True, False),
        ("processing", "processing", None, None, False, False),  # live lease
        ("processing", "stuck", None, None, True, False),
        ("ready", "done", None, None, False, False),
        ("failed", "failed", None, "NO_EXTRACTABLE_TEXT", True, True),  # FE-ADM-06, ADM-18
        ("failed", "failed", None, "EMBEDDING_FAILED", True, True),
        ("failed", "failed", True, "EMBEDDING_FAILED", True, False),  # a current revision exists
        ("failed", "queued", None, "EMBEDDING_FAILED", False, False),  # an attempt is active
        ("failed", None, None, "INTERNAL_ERROR", False, True),  # no job to retry; file can go
    ],
)
async def test_adm16_adm18_actions_are_computed_on_the_backend(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    status: str,
    job: str | None,
    current: bool | None,
    failure: str | None,
    can_retry: bool,
    can_replace: bool,
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status=status, job=job, current=current, failure=failure
    )
    body = (await call(client, "GET", f"/v1/admin/documents/{doc_id}", admin)).json()
    assert (body["can_retry"], body["can_replace"]) == (can_retry, can_replace)


async def test_adm02_unknown_failure_reason_reads_as_internal_error(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure="SOMETHING_NEW", job="failed"
    )
    body = (await call(client, "GET", f"/v1/admin/documents/{doc_id}", admin)).json()
    assert body["failure_code"] == "INTERNAL_ERROR" and body["failure_message"]


# --- ADM-07, ADM-05, SEC-04: access update -----------------------------------------------------


async def test_adm07_access_change_takes_effect_on_the_next_request_without_a_job(
    client: httpx.AsyncClient,
    admin: Any,
    make_user: Any,
    make_session: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="ready", job="done", allowed=("finance", "engineering")
    )
    fin = await make_session(await make_user("registered"), department_id=FIN)
    eng = await make_session(await make_user("registered"), department_id=ENG)
    leg = await make_session(await make_user("registered"), department_id=LEG)

    async def visible(session: Any) -> bool:
        listing = (await call(client, "GET", "/v1/documents", session)).json()
        return str(doc_id) in {i["id"] for i in listing["items"]}

    assert (await visible(fin), await visible(eng), await visible(leg)) == (True, True, False)
    jobs_before = await count(session_factory, "jobs")
    published_before = len(publisher.published)

    response = await call(
        client,
        "PATCH",
        f"/v1/admin/documents/{doc_id}/access",
        admin,
        json={"allowed_department_ids": [str(ENG), str(LEG)]},
    )
    assert response.status_code == 200
    assert {d["slug"] for d in response.json()["allowed_departments"]} == {"engineering", "legal"}
    assert (await visible(fin), await visible(eng), await visible(leg)) == (False, True, True)
    assert await count(session_factory, "jobs") == jobs_before
    assert len(publisher.published) == published_before
    assert await count(session_factory, "document_chunks") == 0
    detail = (await call(client, "GET", f"/v1/admin/documents/{doc_id}", admin)).json()
    assert {d["slug"] for d in detail["allowed_departments"]} == {"engineering", "legal"}


async def test_adm05_sec04_access_rows_are_exactly_what_was_sent_never_the_owner(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory,
        publisher,
        status="ready",
        job="done",
        owner="finance",
        allowed=("finance", "engineering"),
    )
    path = f"/v1/admin/documents/{doc_id}/access"
    response = await call(
        client, "PATCH", path, admin, json={"allowed_department_ids": [str(LEG), str(LEG)]}
    )
    assert response.status_code == 200
    assert await access_of(session_factory, doc_id) == {LEG}  # owner finance gets nothing
    assert [d["slug"] for d in response.json()["allowed_departments"]] == ["legal"]
    # An unchanged list is accepted and changes nothing.
    again = await call(client, "PATCH", path, admin, json={"allowed_department_ids": [str(LEG)]})
    assert again.status_code == 200 and await access_of(session_factory, doc_id) == {LEG}


async def test_adm05_empty_missing_and_unknown_lists_change_nothing(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="ready", job="done", allowed=("finance", "legal")
    )
    before = await access_of(session_factory, doc_id)
    path = f"/v1/admin/documents/{doc_id}/access"
    empty = await call(client, "PATCH", path, admin, json={"allowed_department_ids": []})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "ALLOWED_DEPARTMENTS_EMPTY"
    unknown = await call(
        client,
        "PATCH",
        path,
        admin,
        json={"allowed_department_ids": [str(FIN), str(uuid.uuid4())]},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "UNKNOWN_DEPARTMENT"
    missing = await call(client, "PATCH", path, admin, json={})
    assert missing.status_code == 422
    assert await access_of(session_factory, doc_id) == before  # nothing was inferred or kept half
    assert (
        await count(session_factory, "audit_events", "event = 'admin.document.access_changed'") == 0
    )


async def test_adm07_access_update_of_an_unknown_or_deleted_document_is_404_before_validation(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    deleted = await make_doc(session_factory, publisher, status="ready", job="done", deleted=True)
    for target in (uuid.uuid4(), deleted):
        for body in ({"allowed_department_ids": []}, {"allowed_department_ids": [str(FIN)]}):
            response = await call(
                client, "PATCH", f"/v1/admin/documents/{target}/access", admin, json=body
            )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_adm07_access_can_change_while_the_document_is_still_processing(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="queued", job="queued")
    response = await call(
        client,
        "PATCH",
        f"/v1/admin/documents/{doc_id}/access",
        admin,
        json={"allowed_department_ids": [str(ENG)]},
    )
    assert response.status_code == 200 and response.json()["status"] == "queued"
    assert await access_of(session_factory, doc_id) == {ENG}


# --- ADM-08, LIFE-06: soft delete --------------------------------------------------------------


async def test_adm08_soft_delete_blocks_every_path_and_removes_nothing(
    client: httpx.AsyncClient,
    admin: Any,
    make_user: Any,
    make_session: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="ready", job="done")
    fin = await make_session(await make_user("registered"), department_id=FIN)
    assert (await call(client, "GET", f"/v1/documents/{doc_id}", fin)).status_code == 200
    jobs_before = await count(session_factory, "jobs")
    published_before = len(publisher.published)

    response = await call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin)
    assert response.status_code == 204 and response.content == b""

    for path in (f"/v1/documents/{doc_id}", f"/v1/documents/{doc_id}/content"):
        assert (await call(client, "GET", path, fin)).status_code == 404
    listing = (await call(client, "GET", "/v1/documents", fin)).json()
    assert str(doc_id) not in {i["id"] for i in listing["items"]}
    admin_list = (await call(client, "GET", "/v1/admin/documents", admin)).json()
    assert str(doc_id) not in {i["document_id"] for i in admin_list["items"]}
    assert (await call(client, "GET", f"/v1/admin/documents/{doc_id}", admin)).status_code == 404
    # Soft only: the rows, the revision and the access are still there; no job, no cleanup.
    assert (
        await count(session_factory, "documents", "id = :d AND deleted_at IS NOT NULL", d=doc_id)
        == 1
    )
    assert await count(session_factory, "document_revisions", "document_id = :d", d=doc_id) == 1
    assert await access_of(session_factory, doc_id) == {FIN}
    assert await count(session_factory, "jobs") == jobs_before
    assert len(publisher.published) == published_before


async def test_adm08_deleting_twice_changes_nothing_and_audits_once(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="ready", job="done")
    assert (await call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin)).status_code == 204
    async with session_factory() as s:
        first = (
            await s.execute(text("SELECT deleted_at FROM documents WHERE id = :d"), {"d": doc_id})
        ).scalar()
    again = await call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin)
    assert again.status_code == 404 and again.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    async with session_factory() as s:
        second = (
            await s.execute(text("SELECT deleted_at FROM documents WHERE id = :d"), {"d": doc_id})
        ).scalar()
    assert first == second  # the first deletion time is kept
    assert await count(session_factory, "audit_events", "event = 'admin.document.deleted'") == 1
    unknown = await call(client, "DELETE", f"/v1/admin/documents/{uuid.uuid4()}", admin)
    assert unknown.status_code == 404


async def test_adm08_concurrent_deletes_delete_once(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="queued", job="queued")
    results = await asyncio.gather(
        *[call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin) for _ in range(5)]
    )
    assert sorted(r.status_code for r in results) == [204, 404, 404, 404, 404]
    assert await count(session_factory, "audit_events", "event = 'admin.document.deleted'") == 1


async def test_adm08_a_deleted_document_cannot_be_changed_or_retried(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure="EMBEDDING_FAILED", job="failed"
    )
    assert (await call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin)).status_code == 204
    published = len(publisher.published)
    retry = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert retry.status_code == 404 and retry.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    patch = await call(
        client,
        "PATCH",
        f"/v1/admin/documents/{doc_id}/access",
        admin,
        json={"allowed_department_ids": [str(ENG)]},
    )
    assert patch.status_code == 404
    assert len(publisher.published) == published
    assert await access_of(session_factory, doc_id) == {FIN}
    async with session_factory() as s:
        status = (await s.execute(text("SELECT status FROM jobs"))).scalar()
    assert status == "failed"  # the retry never touched the job


# --- ADM-16: retry -----------------------------------------------------------------------------


async def _job_of(factory: Factory, doc_id: uuid.UUID) -> uuid.UUID:
    async with factory() as s:
        return (
            await s.execute(
                text("SELECT job_id FROM document_revisions WHERE document_id = :d"), {"d": doc_id}
            )
        ).scalar_one()


@pytest.mark.parametrize("failure", ["EMBEDDING_FAILED", "NO_EXTRACTABLE_TEXT"])
async def test_adm16_retry_of_a_failed_revision_requeues_the_same_job_once(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    failure: str,
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure=failure, job="failed"
    )
    job_id = await _job_of(session_factory, doc_id)
    published_before = len(publisher.published)
    jobs_before = await count(session_factory, "jobs")

    response = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == str(doc_id)
    assert body["delivery_state"] == "queued"
    assert body["can_retry"] is False and body["can_replace"] is False  # an attempt is active
    assert len(publisher.published) == published_before + 1
    assert publisher.published[-1][0] == job_id
    assert await count(session_factory, "jobs") == jobs_before  # no second job
    assert await _job_of(session_factory, doc_id) == job_id
    async with session_factory() as s:
        row = (
            await s.execute(text("SELECT status, attempts FROM jobs WHERE id = :j"), {"j": job_id})
        ).one()
    assert (row.status, row.attempts) == ("queued", 0)


async def test_adm16_retry_of_a_lost_publish_republishes_the_job_once(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="queued", job="unpublished")
    detail = (await call(client, "GET", f"/v1/admin/documents/{doc_id}", admin)).json()
    assert detail["delivery_state"] == "unpublished_stuck" and detail["can_retry"] is True
    published_before = len(publisher.published)
    response = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert response.status_code == 202
    assert len(publisher.published) == published_before + 1
    second = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert second.status_code == 409
    assert len(publisher.published) == published_before + 1


@pytest.mark.parametrize(
    ("status", "job"),
    [("ready", "done"), ("queued", "queued"), ("processing", "processing"), ("failed", "done")],
)
async def test_adm16_retry_is_409_for_a_done_or_active_job(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    status: str,
    job: str,
) -> None:
    doc_id = await make_doc(
        session_factory,
        publisher,
        status=status,
        job=job,
        failure="INTERNAL_ERROR" if status == "failed" else None,
    )
    published_before = len(publisher.published)
    response = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_RETRYABLE"
    assert len(publisher.published) == published_before


async def test_adm16_retry_without_a_linked_job_is_409(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory
) -> None:
    doc_id = await make_doc(session_factory, status="failed", failure="INTERNAL_ERROR", job=None)
    response = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_RETRYABLE"


async def test_adm16_concurrent_retries_have_one_winner(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure="EMBEDDING_FAILED", job="failed"
    )
    published_before = len(publisher.published)
    results = await asyncio.gather(
        *[call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin) for _ in range(6)]
    )
    assert sorted(r.status_code for r in results) == [202, 409, 409, 409, 409, 409]
    assert len(publisher.published) == published_before + 1
    assert await count(session_factory, "jobs") == 1


async def test_adm16_retry_races_delete_without_leaving_a_visible_or_second_attempt(
    client: httpx.AsyncClient,
    admin: Any,
    make_user: Any,
    make_session: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure="EMBEDDING_FAILED", job="failed"
    )
    fin = await make_session(await make_user("registered"), department_id=FIN)
    retry, delete = await asyncio.gather(
        call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin),
        call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin),
    )
    assert delete.status_code == 204  # delete never loses to a retry
    assert retry.status_code in (202, 404)  # the retry saw the document, or it was already gone
    assert await count(session_factory, "jobs") == 1  # never a second job
    assert (await call(client, "GET", f"/v1/documents/{doc_id}", fin)).status_code == 404
    after = await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert after.status_code == 404


async def test_adm16_retry_publish_failure_still_reports_the_state(
    engine: AsyncEngine,
    clock: FakeClock,
    admin: Any,
    session_factory: Factory,
) -> None:
    failing = FakePublisher(fail=True)
    app = create_app(
        _settings(),
        engine=engine,
        publisher=failing,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=FakeObjectStore(),
    )
    doc_id = await make_doc(
        session_factory, FakePublisher(), status="failed", failure="EMBEDDING_FAILED", job="failed"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        response = await call(c, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    assert response.status_code == 202
    assert response.json()["delivery_state"] == "publish_failed"
    assert response.json()["can_retry"] is True  # the Admin can try again


# --- SEC-07, LIFE-02, SEC-17: non-ready states never reach a user route -------------------------


@pytest.mark.parametrize("status", ["queued", "processing", "failed"])
async def test_sec07_non_ready_documents_never_appear_on_user_routes_not_even_for_the_admin(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    status: str,
) -> None:
    doc_id = await make_doc(
        session_factory,
        publisher,
        status=status,
        job="failed" if status == "failed" else "queued",
        failure="INTERNAL_ERROR" if status == "failed" else None,
        allowed=("finance", "engineering"),
    )
    sessions = [
        await make_session(await make_user("registered"), department_id=FIN),
        await make_session(await make_user("registered"), department_id=ENG),
        # The Admin has no bypass in the regular library: SEC-17 applies to the user routes.
        await make_session(await make_user("admin"), department_id=FIN),
    ]
    for session in sessions:
        listing = (await call(client, "GET", "/v1/documents", session)).json()
        assert str(doc_id) not in {i["id"] for i in listing["items"]}
        for path in (f"/v1/documents/{doc_id}", f"/v1/documents/{doc_id}/content"):
            response = await call(client, "GET", path, session)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


# --- D14: uploads switch ------------------------------------------------------------------------


async def test_m3_ac26_management_keeps_working_with_uploads_disabled(
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
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure="EMBEDDING_FAILED", job="failed"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        assert (await call(c, "GET", "/v1/admin/documents", admin)).status_code == 200
        assert (await call(c, "GET", f"/v1/admin/documents/{doc_id}", admin)).status_code == 200
        assert (
            await call(c, "GET", f"/v1/admin/documents/{doc_id}/events", admin)
        ).status_code == 200
        patch = await call(
            c,
            "PATCH",
            f"/v1/admin/documents/{doc_id}/access",
            admin,
            json={"allowed_department_ids": [str(ENG)]},
        )
        assert patch.status_code == 200
        assert (
            await call(c, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
        ).status_code == 202
        assert (await call(c, "DELETE", f"/v1/admin/documents/{doc_id}", admin)).status_code == 204


# --- ADM-17, MON-04: audit and log hygiene ------------------------------------------------------


async def test_adm17_audit_rows_carry_ids_and_counts_never_content(
    client: httpx.AsyncClient,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    doc_id = await make_doc(
        session_factory,
        publisher,
        status="failed",
        failure="EMBEDDING_FAILED",
        job="failed",
        title=SECRET_TITLE,
        filename=SECRET_FILENAME,
    )
    revision_key = f"documents/{doc_id}/"
    assert (
        await call(client, "POST", f"/v1/admin/documents/{doc_id}/retry", admin)
    ).status_code == 202
    assert (
        await call(
            client,
            "PATCH",
            f"/v1/admin/documents/{doc_id}/access",
            admin,
            json={"allowed_department_ids": [str(ENG)]},
        )
    ).status_code == 200
    assert (await call(client, "DELETE", f"/v1/admin/documents/{doc_id}", admin)).status_code == 204

    async with session_factory() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT event, user_id, ip, details FROM audit_events "
                    "WHERE event LIKE 'admin.document.%' ORDER BY occurred_at"
                )
            )
        ).all()
    assert [r.event for r in rows] == [
        "admin.document.retried",
        "admin.document.access_changed",
        "admin.document.deleted",
    ]
    for row in rows:
        assert row.user_id == admin.user_id  # the admin id
        assert row.ip is None  # SEC-18
        assert row.details["document_id"] == str(doc_id)  # the target
        blob = json.dumps(row.details)
        for forbidden in (SECRET_TITLE, SECRET_FILENAME, revision_key, "storage_key", ".pdf"):
            assert forbidden not in blob
    for record in caplog.records:
        rendered = record.getMessage() + json.dumps(record.__dict__, default=str)
        for forbidden in (SECRET_TITLE, SECRET_FILENAME, revision_key):
            assert forbidden not in rendered, f"{record.name} logged document content"


# --- ADM-01: stream and route authorization ----------------------------------------------------


async def test_adm01_status_stream_authorization_order(
    client: httpx.AsyncClient,
    make_user: Any,
    make_session: Any,
    admin: Any,
    session_factory: Factory,
    publisher: FakePublisher,
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="queued", job="queued")
    path = f"/v1/admin/documents/{doc_id}/events"
    anonymous = await client.get(path)
    assert anonymous.status_code == 401
    assert anonymous.headers["content-type"].startswith("application/json")
    for kind in ("demo", "registered"):
        session = await make_session(await make_user(kind), department_id=FIN)
        denied = await call(client, "GET", path, session)
        assert denied.status_code == 403 and "event-stream" not in denied.headers["content-type"]
    for bad in ("not-a-uuid", str(uuid.uuid4())):
        assert (await client.get(f"/v1/admin/documents/{bad}/events")).status_code == 401
        user = await make_session(await make_user("registered"), department_id=FIN)
        assert (
            await call(client, "GET", f"/v1/admin/documents/{bad}/events", user)
        ).status_code == 403
        missing = await call(client, "GET", f"/v1/admin/documents/{bad}/events", admin)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    gone = await make_doc(session_factory, publisher, status="queued", job="queued", deleted=True)
    assert (
        await call(client, "GET", f"/v1/admin/documents/{gone}/events", admin)
    ).status_code == 404


def _parse(body: str) -> list[tuple[str, Any]]:
    """``[(event, data)]`` with ``("comment", text)`` for comment lines."""
    out: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if block.startswith(":"):
            out.append(("comment", block))
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


async def test_ing07_stream_of_a_failed_document_is_a_snapshot_then_end(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory, publisher, status="failed", failure="NO_EXTRACTABLE_TEXT", job="failed"
    )
    jobs, published = await count(session_factory, "jobs"), len(publisher.published)
    for _ in range(2):  # a reconnect starts again from the database and creates nothing
        response = await call(client, "GET", f"/v1/admin/documents/{doc_id}/events", admin)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "no-cache" in response.headers["cache-control"]
        assert "\nid:" not in "\n" + response.text  # no event ids, no replay
        events = _parse(response.text)
        assert [e[0] for e in events] == ["status", "end"]
        status = events[0][1]
        assert status["status"] == "failed" and status["failure_code"] == "NO_EXTRACTABLE_TEXT"
        assert status["can_retry"] is True and status["can_replace"] is True
        assert events[1][1] == {"reason": "terminal"}
    assert await count(session_factory, "jobs") == jobs
    assert len(publisher.published) == published


async def test_ing07_stream_payload_is_the_status_model_and_nothing_else(
    client: httpx.AsyncClient, admin: Any, session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(
        session_factory,
        publisher,
        status="ready",
        job="done",
        title=SECRET_TITLE,
        filename=SECRET_FILENAME,
    )
    response = await call(client, "GET", f"/v1/admin/documents/{doc_id}/events", admin)
    status = _parse(response.text)[0][1]
    assert set(status) == {
        "document_id",
        "revision_id",
        "status",
        "phase",
        "failure_code",
        "failure_message",
        "delivery_state",
        "can_retry",
        "can_replace",
    }
    assert SECRET_TITLE not in response.text and SECRET_FILENAME not in response.text
    assert "storage" not in response.text


async def test_ing07_stream_of_a_waiting_document_ends_with_timeout(
    engine: AsyncEngine,
    clock: FakeClock,
    publisher: FakePublisher,
    admin: Any,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events_module, "POLL_SECONDS", 0.05)
    app = create_app(
        _settings(sse_max_seconds=1, sse_keepalive_seconds=1),
        engine=engine,
        publisher=publisher,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
        object_store=FakeObjectStore(),
    )
    doc_id = await make_doc(session_factory, publisher, status="queued", job="queued")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        response = await call(c, "GET", f"/v1/admin/documents/{doc_id}/events", admin)
    events = _parse(response.text)
    assert events[0][0] == "status" and events[0][1]["status"] == "queued"
    assert events[-1] == ("end", {"reason": "timeout"})
    assert await count(session_factory, "jobs") == 1


async def _collect(stream: AsyncIterator[str]) -> list[tuple[str, Any]]:
    return _parse("".join([chunk async for chunk in stream]))


async def test_ing07_stream_sends_each_change_then_ends_terminal(
    session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="queued", job="queued")
    windows = JobWindows(GRACE, STUCK)
    first = await load_status(session_factory, doc_id, windows)
    assert first is not None

    async def progress() -> None:
        for status, phase in (
            ("processing", "fetching"),
            ("processing", "fetching"),  # unchanged: nothing is sent
            ("processing", "embedding"),
            ("ready", None),
        ):
            await asyncio.sleep(0.15)
            await sql(
                session_factory,
                "UPDATE document_revisions SET status = :s, phase = :p, "
                "page_count = CASE WHEN :s = 'ready' THEN 3 END, "
                "ready_at = CASE WHEN :s = 'ready' THEN now() END WHERE document_id = :d",
                s=status,
                p=phase,
                d=doc_id,
            )

    stream = events_module.status_events(
        session_factory,
        doc_id,
        windows,
        first,
        keepalive_seconds=0.1,
        max_seconds=10,
        poll_seconds=0.02,
    )
    _, events = await asyncio.gather(progress(), _collect(stream))
    statuses = [(e[1]["status"], e[1]["phase"]) for e in events if e[0] == "status"]
    assert statuses == [
        ("queued", None),
        ("processing", "fetching"),
        ("processing", "embedding"),
        ("ready", None),
    ]
    assert events[-1] == ("end", {"reason": "terminal"})
    assert any(e[0] == "comment" for e in events)  # keepalive while nothing changed


async def test_ing07_stream_reports_a_state_change_that_only_the_job_shows(
    session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="queued", job="queued")
    windows = JobWindows(GRACE, STUCK)
    first = await load_status(session_factory, doc_id, windows)
    assert first is not None and first.delivery_state == "queued"

    async def lease() -> None:
        await asyncio.sleep(0.1)
        await sql(
            session_factory,
            "UPDATE jobs SET status='processing', claimed_by='w', "
            "lease_expires_at = now() + interval '1 hour'",
        )
        await asyncio.sleep(0.2)
        await sql(
            session_factory,
            "UPDATE document_revisions SET status='failed', failure_reason='EMBEDDING_FAILED'",
        )

    stream = events_module.status_events(
        session_factory,
        doc_id,
        windows,
        first,
        keepalive_seconds=5,
        max_seconds=10,
        poll_seconds=0.02,
    )
    _, events = await asyncio.gather(lease(), _collect(stream))
    states = [e[1]["delivery_state"] for e in events if e[0] == "status"]
    assert states[:2] == ["queued", "processing"]
    assert events[-1] == ("end", {"reason": "terminal"})


async def test_ing07_stream_ends_when_the_document_is_deleted_while_watching(
    session_factory: Factory, publisher: FakePublisher
) -> None:
    doc_id = await make_doc(session_factory, publisher, status="processing", job="processing")
    windows = JobWindows(GRACE, STUCK)
    first = await load_status(session_factory, doc_id, windows)
    assert first is not None

    async def delete() -> None:
        await asyncio.sleep(0.1)
        await sql(
            session_factory, "UPDATE documents SET deleted_at = now() WHERE id = :d", d=doc_id
        )

    stream = events_module.status_events(
        session_factory,
        doc_id,
        windows,
        first,
        keepalive_seconds=5,
        max_seconds=10,
        poll_seconds=0.02,
    )
    _, events = await asyncio.gather(delete(), _collect(stream))
    assert [e[0] for e in events] == ["status", "end"]
    assert events[-1][1] == {"reason": "terminal"}
    assert await count(session_factory, "jobs") == 1  # watching created nothing
