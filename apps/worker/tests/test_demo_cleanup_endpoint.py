"""M1-11 maintenance endpoint tests: SEC-14 (the single signed-without-job exception), AUTH-35.

Signatures are produced locally with the M0 helpers; this does not prove live QStash delivery.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_worker_service import NEXT, PUBLIC_URL, make_settings, sign

from knowserve_core.clock import FakeClock
from knowserve_core.qstash import FakePublisher
from knowserve_worker.app import create_app

pytestmark = [pytest.mark.m1, pytest.mark.worker, pytest.mark.integration]

PATH = "/internal/maintenance/demo-cleanup"
URL = PUBLIC_URL + PATH
Factory = async_sessionmaker[AsyncSession]


def client_for(engine: AsyncEngine, database_url: str, clock: FakeClock, **kw: Any):
    app = create_app(
        settings=make_settings(database_url, **kw),
        engine=engine,
        publisher=FakePublisher(),
        handlers={},
        clock=clock,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL, timeout=30)


async def user_count(factory: Factory) -> int:
    async with factory() as s:
        return (await s.execute(text("SELECT count(*) FROM users"))).scalar_one()


async def audit_count(factory: Factory) -> int:
    async with factory() as s:
        return (
            await s.execute(
                text("SELECT count(*) FROM audit_events WHERE event = 'demo.cleanup.run'")
            )
        ).scalar_one()


@pytest.fixture
async def expired_demo(clock: FakeClock, make_user: Any) -> None:
    for _ in range(2):
        await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    await make_user("registered", created_at=clock.now() - timedelta(hours=60))


def signed(body: bytes = b"", **kw: Any) -> dict[str, str]:
    return {"Upstash-Signature": sign(body, sub=URL, **kw)}


async def test_sec14_cleanup_without_signature_is_rejected_and_does_nothing(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    expired_demo: None,
) -> None:
    async with client_for(engine, database_url, clock) as c:
        response = await c.post(PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert await user_count(session_factory) == 3 and await audit_count(session_factory) == 0


@pytest.mark.parametrize(
    "case", ["bad_key", "expired", "body_mismatch", "job_endpoint_token", "wrong_iss", "garbage"]
)
async def test_sec14_cleanup_with_bad_signature_is_rejected_like_the_job_endpoint(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    expired_demo: None,
    case: str,
) -> None:
    body = b""
    headers = {
        "bad_key": {"Upstash-Signature": sign(body, key="other-key", sub=URL)},
        "expired": signed(body, exp=int(time.time()) - 600),
        "body_mismatch": {"Upstash-Signature": sign(b"different", sub=URL)},
        # A genuine signed job delivery (sub = the job URL) must not work on this route.
        "job_endpoint_token": {"Upstash-Signature": sign(body)},
        "wrong_iss": signed(body, iss="Nobody"),
        "garbage": {"Upstash-Signature": "not.a.jwt"},
    }[case]
    async with client_for(engine, database_url, clock) as c:
        response = await c.post(PATH, content=body, headers=headers)
        job_like = await c.post("/internal/jobs/run", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    # Same status and same error envelope shape as the job endpoint for the same bad signature.
    if case != "job_endpoint_token":
        assert job_like.status_code == response.status_code
        assert job_like.json()["error"].keys() == response.json()["error"].keys()
    assert await user_count(session_factory) == 3 and await audit_count(session_factory) == 0


async def test_sec14_cleanup_fails_closed_without_signing_keys(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    expired_demo: None,
) -> None:
    async with client_for(
        engine, database_url, clock, qstash_current_signing_key=None, qstash_next_signing_key=None
    ) as c:
        response = await c.post(PATH, content=b"", headers=signed())
    assert response.status_code == 401 and await user_count(session_factory) == 3


async def test_sec14_auth35_valid_signature_runs_exactly_one_cleanup(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    expired_demo: None,
) -> None:
    async with client_for(engine, database_url, clock) as c:
        response = await c.post(PATH, content=b"", headers=signed())
        again = await c.post(PATH, content=b"", headers=signed(key=NEXT))
    assert response.status_code == 200
    assert response.json() == {
        "deleted_users": 2,
        "batches": 1,
        "failed_batches": 0,
        "purged_rate_limit_counters": 0,
        "capped": False,
    }
    assert again.status_code == 200 and again.json()["deleted_users"] == 0
    assert await user_count(session_factory) == 1  # the registered user only
    assert await audit_count(session_factory) == 2  # one audit event per run, counts only


async def test_sec14_cleanup_ignores_query_and_body_parameters(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    make_user: Any,
) -> None:
    fresh = await make_user("demo", created_at=clock.now() - timedelta(hours=1))
    old = await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    body = (
        b'{"retention_seconds": 1, "batch_size": 1000000, "user_id": "'
        + str(fresh.id).encode()
        + b'"}'
    )
    async with client_for(engine, database_url, clock) as c:
        response = await c.post(
            PATH + "?retention_seconds=1&batch_size=99999&all=true&user_id=" + str(fresh.id),
            content=body,
            headers=signed(body),
        )
    assert response.status_code == 200
    assert response.json()["deleted_users"] == 1  # limits come from settings, not the caller
    async with session_factory() as s:
        left = set((await s.execute(text("SELECT id FROM users"))).scalars())
    assert left == {fresh.id} and old.id not in left


async def test_sec14_cleanup_oversized_body_is_rejected_before_any_work(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    expired_demo: None,
) -> None:
    body = b"x" * 5000
    async with client_for(engine, database_url, clock) as c:
        response = await c.post(PATH, content=body, headers=signed(body))
    assert response.status_code == 413 and await user_count(session_factory) == 3


async def test_sec14_cleanup_failure_is_not_acknowledged_so_qstash_retries(
    engine: AsyncEngine,
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    expired_demo: None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE tmp_endpoint_blocker (user_id uuid REFERENCES users(id))")
        )
        await conn.execute(
            text("INSERT INTO tmp_endpoint_blocker SELECT id FROM users WHERE kind = 'demo'")
        )
    try:
        async with client_for(engine, database_url, clock, demo_cleanup_batch_size=1) as c:
            response = await c.post(PATH, content=b"", headers=signed())
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "CLEANUP_FAILED"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE tmp_endpoint_blocker"))


async def test_sec14_only_one_maintenance_route_exists(
    engine: AsyncEngine, database_url: str, clock: FakeClock
) -> None:
    app = create_app(
        settings=make_settings(database_url), engine=engine, publisher=FakePublisher(), handlers={}
    )
    paths = set(app.openapi()["paths"])
    assert {p for p in paths if "maintenance" in p} == {PATH}
