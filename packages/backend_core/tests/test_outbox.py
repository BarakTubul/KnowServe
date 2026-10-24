"""ING-13/14, M0-AC10: outbox publish-after-commit, recovery dispatch and SKIP LOCKED claiming."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.jobs import enqueue_job
from knowserve_core.outbox import _CLAIM_BATCH, dispatch_pending, publish_after_commit
from knowserve_core.qstash import FakePublisher

pytestmark = [pytest.mark.m0, pytest.mark.worker, pytest.mark.integration]

Factory = async_sessionmaker[AsyncSession]


async def _enqueue(factory: Factory, n: int = 1) -> list[uuid.UUID]:
    ids = []
    async with factory() as s, s.begin():
        for _ in range(n):
            ids.append((await enqueue_job(s, "noop", correlation_id="req_outbox_001")).id)
    return ids


async def _outbox(factory: Factory, job_id: uuid.UUID):  # type: ignore[no-untyped-def]
    async with factory() as s:
        return (
            await s.execute(
                text(
                    "SELECT status, attempts, published_at, last_error, lease_expires_at, "
                    "next_attempt_at > now() AS backed_off FROM outbox WHERE job_id = :id"
                ),
                {"id": job_id},
            )
        ).one()


async def test_ing13_publish_after_commit_marks_published(session_factory: Factory) -> None:
    (job_id,) = await _enqueue(session_factory)
    publisher = FakePublisher()
    assert await publish_after_commit(session_factory, publisher, job_id) is True
    assert publisher.published == [(job_id, "req_outbox_001")]
    row = await _outbox(session_factory, job_id)
    assert row.status == "published" and row.published_at is not None and row.attempts == 1


async def test_ing13_publisher_failure_leaves_row_pending_and_backs_off(
    session_factory: Factory,
) -> None:
    (job_id,) = await _enqueue(session_factory)
    assert await publish_after_commit(session_factory, FakePublisher(fail=True), job_id) is False
    row = await _outbox(session_factory, job_id)
    assert row.status == "pending" and row.attempts == 1
    assert row.last_error and row.backed_off and row.lease_expires_at is None
    # Backed off: an immediate dispatch must not retry it.
    publisher = FakePublisher()
    result = await dispatch_pending(session_factory, publisher, 10, 60)
    assert (result.published, result.failed) == (0, 0)
    # Once the back-off has passed, dispatch publishes it.
    async with session_factory() as s, s.begin():
        await s.execute(text("UPDATE outbox SET next_attempt_at = now() - interval '1 second'"))
    result = await dispatch_pending(session_factory, publisher, 10, 60)
    assert result.published == 1
    assert (await _outbox(session_factory, job_id)).status == "published"
    assert (await _outbox(session_factory, job_id)).attempts == 2


async def test_ing13_publish_after_commit_never_raises_on_unexpected_error(
    session_factory: Factory,
) -> None:
    class Exploding:
        async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
            raise ValueError("kaboom with detail")

    (job_id,) = await _enqueue(session_factory)
    assert await publish_after_commit(session_factory, Exploding(), job_id) is False
    row = await _outbox(session_factory, job_id)
    assert row.status == "pending" and "kaboom" not in (row.last_error or "")


async def test_m0_ac10_lost_immediate_publish_is_recovered_exactly_once(
    session_factory: Factory,
) -> None:
    """The API committed but never published (crash/lost call): the dispatcher publishes it once."""
    (job_id,) = await _enqueue(session_factory)
    publisher = FakePublisher()
    first = await dispatch_pending(session_factory, publisher, 10, 60)
    second = await dispatch_pending(session_factory, publisher, 10, 60)
    assert (first.published, second.published) == (1, 0)
    assert publisher.published == [(job_id, "req_outbox_001")]


async def test_ing14_unexpired_lease_blocks_reclaim_and_expired_lease_allows_it(
    session_factory: Factory,
) -> None:
    (job_id,) = await _enqueue(session_factory)
    async with session_factory() as s, s.begin():
        await s.execute(text("UPDATE outbox SET lease_expires_at = now() + interval '5 minutes'"))
    publisher = FakePublisher()
    assert (await dispatch_pending(session_factory, publisher, 10, 60)).published == 0
    async with session_factory() as s, s.begin():
        await s.execute(text("UPDATE outbox SET lease_expires_at = now() - interval '1 second'"))
    assert (await dispatch_pending(session_factory, publisher, 10, 60)).published == 1
    assert [j for j, _ in publisher.published] == [job_id]


async def test_ing14_two_concurrent_dispatchers_publish_each_row_once(
    session_factory: Factory,
) -> None:
    ids = await _enqueue(session_factory, 10)
    publisher = FakePublisher(delay=0.02)
    results = await asyncio.gather(
        dispatch_pending(session_factory, publisher, 6, 60),
        dispatch_pending(session_factory, publisher, 6, 60),
    )
    assert sum(r.published for r in results) == 10
    counts = Counter(j for j, _ in publisher.published)
    assert set(counts) == set(ids) and set(counts.values()) == {1}


async def test_ing14_skip_locked_does_not_block_on_rows_locked_by_another_claimer(
    session_factory: Factory,
) -> None:
    ids = await _enqueue(session_factory, 10)
    publisher = FakePublisher()
    async with session_factory() as holder, holder.begin():
        held = (await holder.execute(_CLAIM_BATCH, {"batch": 4, "lease": 60})).all()
        assert len(held) == 4  # claimed but uncommitted: row locks are held
        other = await asyncio.wait_for(dispatch_pending(session_factory, publisher, 10, 60), 5)
        assert other.published == 6  # the other dispatcher skipped the 4 locked rows
    published = {j for j, _ in publisher.published}
    assert published.isdisjoint({r.job_id for r in held}) and published <= set(ids)
