"""ING-12 / M0-AC05: enqueue_job writes job + outbox atomically in the caller's transaction."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core import request_context
from knowserve_core.jobs import enqueue_job

pytestmark = [pytest.mark.m0, pytest.mark.worker, pytest.mark.integration]


async def _counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with factory() as s:
        jobs = (await s.execute(text("SELECT count(*) FROM jobs"))).scalar_one()
        outbox = (await s.execute(text("SELECT count(*) FROM outbox"))).scalar_one()
    return jobs, outbox


async def test_ing12_enqueue_commits_job_and_outbox_together(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s, s.begin():
        job = await enqueue_job(s, "noop", correlation_id="req_explicit_001")
    assert await _counts(session_factory) == (1, 1)
    async with session_factory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT j.status, j.correlation_id, o.status AS o_status, "
                    "o.correlation_id AS o_cid FROM jobs j JOIN outbox o ON o.job_id = j.id "
                    "WHERE j.id = :id"
                ),
                {"id": job.id},
            )
        ).one()
    assert (row.status, row.o_status) == ("queued", "pending")
    assert row.correlation_id == row.o_cid == "req_explicit_001"


async def test_ing12_exception_before_commit_leaves_no_job_and_no_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="injected"):
        async with session_factory() as s, s.begin():
            await enqueue_job(s, "noop")
            raise RuntimeError("injected fault before commit")
    assert await _counts(session_factory) == (0, 0)


async def test_ing12_outbox_failure_rolls_back_job_too(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="injected"):
        async with session_factory() as s, s.begin():
            await enqueue_job(s, "noop")
            await enqueue_job(s, "noop")
            raise RuntimeError("injected after two enqueues")
    assert await _counts(session_factory) == (0, 0)


async def test_mon03_correlation_id_copied_from_request_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    request_context.clear()
    request_context.set_request_id("req_ctx_corr_01")
    try:
        async with session_factory() as s, s.begin():
            job = await enqueue_job(s, "noop")
    finally:
        request_context.clear()
    assert job.correlation_id == "req_ctx_corr_01"
    async with session_factory() as s:
        cid = (await s.execute(text("SELECT correlation_id FROM outbox"))).scalar_one()
    assert cid == "req_ctx_corr_01"


async def test_ing12_enqueue_never_publishes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s, s.begin():
        await enqueue_job(s, "noop")
    async with session_factory() as s:
        status, published_at = (
            await s.execute(text("SELECT status, published_at FROM outbox"))
        ).one()
    assert status == "pending" and published_at is None
