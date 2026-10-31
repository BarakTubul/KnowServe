"""ING-13, ING-14, ING-16, ADM-16 (core), M0-AC10: stale claims, delivery states, manual retry.

Real PostgreSQL. Publishers are fakes: nothing here proves live QStash behaviour.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.job_recovery import (
    ATTENTION_STATES,
    JobNotFoundError,
    NotRetryableError,
    create_job,
    get_job_view,
    list_job_views,
    retry_job,
)
from knowserve_core.outbox import _CLAIM_ONE, _Claimed, _deliver, publish_after_commit
from knowserve_core.qstash import FakePublisher

pytestmark = [pytest.mark.m0, pytest.mark.worker, pytest.mark.integration]

Factory = async_sessionmaker[AsyncSession]
GRACE = 120
STUCK = 900
KW = {"grace_seconds": GRACE, "stuck_after_seconds": STUCK}


async def sql(factory: Factory, statement: str, **params: object) -> None:
    async with factory() as s, s.begin():
        for part in statement.split(";"):
            if part.strip():
                await s.execute(text(part), params)


async def state(factory: Factory, job_id: uuid.UUID) -> str:
    view = await get_job_view(factory, job_id, **KW)
    assert view is not None
    return view.delivery_state


async def unpublished(factory: Factory) -> uuid.UUID:
    """A job whose API 'crashed' after commit: row pending, never claimed, older than the grace."""
    job_id = await create_job(factory, None, "noop", correlation_id="req_rec_001", publish=False)
    await sql(
        factory,
        "UPDATE outbox SET created_at = now() - interval '10 minutes' WHERE job_id = :id",
        id=job_id,
    )
    return job_id


# ------------------------------------------------------------------ claim ownership (ING-14)


class _Hangs:
    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        await asyncio.sleep(30)


async def test_ing14_expired_claim_holder_cannot_mark_published(session_factory: Factory) -> None:
    job_id = await create_job(session_factory, None, "noop", publish=False)
    async with session_factory() as s, s.begin():
        first = _Claimed(*(await s.execute(_CLAIM_ONE, {"job_id": job_id, "lease": 60})).one())
    await sql(session_factory, "UPDATE outbox SET lease_expires_at = now() - interval '1 second'")
    async with session_factory() as s, s.begin():
        second = _Claimed(*(await s.execute(_CLAIM_ONE, {"job_id": job_id, "lease": 60})).one())
    assert (first.attempt, second.attempt) == (1, 2)

    late = FakePublisher()
    assert await _deliver(session_factory, late, first) is False  # stale: nothing is marked
    async with session_factory() as s:
        row = (await s.execute(text("SELECT status, lease_expires_at FROM outbox"))).one()
    assert row.status == "pending" and row.lease_expires_at is not None  # newer claim intact

    assert await _deliver(session_factory, FakePublisher(), second) is True
    async with session_factory() as s:
        assert (await s.execute(text("SELECT status FROM outbox"))).scalar_one() == "published"


async def test_ing14_expired_claim_holder_cannot_back_off_a_newer_claim(
    session_factory: Factory,
) -> None:
    job_id = await create_job(session_factory, None, "noop", publish=False)
    async with session_factory() as s, s.begin():
        first = _Claimed(*(await s.execute(_CLAIM_ONE, {"job_id": job_id, "lease": 60})).one())
    await sql(session_factory, "UPDATE outbox SET lease_expires_at = now() - interval '1 second'")
    async with session_factory() as s, s.begin():
        await s.execute(_CLAIM_ONE, {"job_id": job_id, "lease": 60})  # the newer claim
    assert await _deliver(session_factory, FakePublisher(fail=True), first) is False
    async with session_factory() as s:
        row = (await s.execute(text("SELECT last_error, lease_expires_at FROM outbox"))).one()
    assert row.last_error is None and row.lease_expires_at is not None  # not reset by the stale one


async def test_ing13_publish_is_bounded_by_a_timeout_and_recorded_as_unconfirmed(
    session_factory: Factory,
) -> None:
    job_id = await create_job(session_factory, None, "noop", publish=False)
    ok = await publish_after_commit(session_factory, _Hangs(), job_id, publish_timeout=0.2)  # type: ignore[arg-type]
    assert ok is False
    view = await get_job_view(session_factory, job_id, **KW)
    assert (
        view
        and view.delivery_state == "publish_failed"
        and "unconfirmed" in str(view.publish_error)
    )


# ------------------------------------------------------------------------- delivery states


async def test_ing16_delivery_states_are_derived_from_existing_columns(
    session_factory: Factory,
) -> None:
    f = session_factory
    young = await create_job(f, None, "noop", publish=False)
    stuck = await unpublished(f)
    errored = await create_job(f, None, "noop", publish=False)
    await sql(f, "UPDATE outbox SET last_error = 'rejected' WHERE job_id = :id", id=errored)
    leased = await create_job(f, None, "noop", publish=False)
    await sql(
        f,
        "UPDATE outbox SET lease_expires_at = now() + interval '1 minute' WHERE job_id = :id",
        id=leased,
    )
    queued = await create_job(f, FakePublisher(), "noop")
    queued_stuck = await create_job(f, FakePublisher(), "noop")
    await sql(
        f,
        "UPDATE jobs SET updated_at = now() - interval '1 hour' WHERE id = :id;"
        "UPDATE outbox SET published_at = now() - interval '1 hour' WHERE job_id = :id",
        id=queued_stuck,
    )
    processing = await create_job(f, FakePublisher(), "noop")
    await sql(
        f,
        "UPDATE jobs SET status = 'processing', lease_expires_at = now() + interval '1 minute' "
        "WHERE id = :id",
        id=processing,
    )
    processing_stuck = await create_job(f, FakePublisher(), "noop")
    await sql(
        f,
        "UPDATE jobs SET status = 'processing', lease_expires_at = now() - interval '1 minute' "
        "WHERE id = :id",
        id=processing_stuck,
    )
    failed = await create_job(f, FakePublisher(), "noop")
    await sql(f, "UPDATE jobs SET status = 'failed', last_error = 'boom' WHERE id = :id", id=failed)
    done = await create_job(f, FakePublisher(), "noop")
    await sql(f, "UPDATE jobs SET status = 'done' WHERE id = :id", id=done)

    expected = {
        young: "publish_pending",
        stuck: "unpublished_stuck",
        errored: "publish_failed",
        leased: "publishing",
        queued: "queued",
        queued_stuck: "queued_stuck",
        processing: "processing",
        processing_stuck: "processing_stuck",
        failed: "failed",
        done: "done",
    }
    for job_id, want in expected.items():
        assert await state(f, job_id) == want, want

    listed = await list_job_views(f, states=ATTENTION_STATES, **KW)
    assert {v.job_id for v in listed} == {stuck, errored, queued_stuck, processing_stuck, failed}
    assert {v.job_id: v.retry_action for v in listed} == {
        stuck: "republish",
        errored: "republish",
        queued_stuck: "requeue",
        processing_stuck: "requeue",
        failed: "requeue",
    }


# ------------------------------------------------------------- manual retry: publish failures


async def test_m0_ac10_job_left_pending_after_api_crash_is_found_and_published_once(
    session_factory: Factory,
) -> None:
    job_id = await unpublished(session_factory)
    attention = await list_job_views(session_factory, states=ATTENTION_STATES, **KW)
    assert [v.job_id for v in attention] == [job_id]
    publisher = FakePublisher()
    result = await retry_job(session_factory, publisher, job_id, **KW)
    assert (result.action, result.published) == ("republish", True)
    assert publisher.published == [(job_id, "req_rec_001")]
    assert await state(session_factory, job_id) == "queued"
    with pytest.raises(NotRetryableError):  # published now: a second retry is rejected
        await retry_job(session_factory, publisher, job_id, **KW)
    assert len(publisher.published) == 1


async def test_adm16_publish_failure_is_retried_by_republishing(session_factory: Factory) -> None:
    job_id = await create_job(session_factory, FakePublisher(fail=True), "noop")
    assert await state(session_factory, job_id) == "publish_failed"
    publisher = FakePublisher()
    result = await retry_job(session_factory, publisher, job_id, **KW)
    assert (result.action, result.published) == ("republish", True)
    assert await state(session_factory, job_id) == "queued"
    async with session_factory() as s:
        assert (await s.execute(text("SELECT attempts FROM jobs"))).scalar_one() == 0  # not touched


async def test_adm16_failed_republish_leaves_it_retryable(session_factory: Factory) -> None:
    job_id = await unpublished(session_factory)
    result = await retry_job(session_factory, FakePublisher(fail=True), job_id, **KW)
    assert (result.action, result.published) == ("republish", False)
    assert await state(session_factory, job_id) == "publish_failed"


async def test_adm16_simultaneous_retries_publish_exactly_once(session_factory: Factory) -> None:
    job_id = await unpublished(session_factory)
    publisher = FakePublisher(delay=0.2)
    outcomes = await asyncio.gather(
        *[retry_job(session_factory, publisher, job_id, **KW) for _ in range(6)],
        return_exceptions=True,
    )
    wins = [o for o in outcomes if not isinstance(o, Exception)]
    assert len(wins) == 1 and all(
        isinstance(o, NotRetryableError) for o in outcomes if o not in wins
    )
    assert len(publisher.published) == 1


# ---------------------------------------------------------- manual retry: processing failures


async def test_adm16_failed_job_is_requeued_and_republished(session_factory: Factory) -> None:
    f = session_factory
    job_id = await create_job(f, FakePublisher(), "noop", correlation_id="req_rec_002")
    await sql(
        f,
        "UPDATE jobs SET status = 'failed', attempts = 4, last_error = 'boom' WHERE id = :id",
        id=job_id,
    )
    assert await state(f, job_id) == "failed"
    publisher = FakePublisher()
    result = await retry_job(f, publisher, job_id, **KW)
    assert (result.action, result.published) == ("requeue", True)
    assert publisher.published == [(job_id, "req_rec_002")]
    async with f() as s:
        job = (await s.execute(text("SELECT status, attempts, claimed_by FROM jobs"))).one()
        box = (await s.execute(text("SELECT status, attempts FROM outbox"))).one()
    assert (job.status, job.attempts, job.claimed_by) == ("queued", 0, None)
    assert box.status == "published" and box.attempts == 1  # re-armed, then claimed once


async def test_adm16_processing_stuck_and_queued_stuck_are_requeued(
    session_factory: Factory,
) -> None:
    f = session_factory
    expired = await create_job(f, FakePublisher(), "noop")
    await sql(
        f,
        "UPDATE jobs SET status = 'processing', claimed_by = 'dead', "
        "lease_expires_at = now() - interval '1 minute' WHERE id = :id",
        id=expired,
    )
    lost = await create_job(f, FakePublisher(), "noop")
    await sql(
        f,
        "UPDATE jobs SET updated_at = now() - interval '1 hour' WHERE id = :id;"
        "UPDATE outbox SET published_at = now() - interval '1 hour' WHERE job_id = :id",
        id=lost,
    )
    publisher = FakePublisher()
    for job_id in (expired, lost):
        assert (await retry_job(f, publisher, job_id, **KW)).action == "requeue"
        assert await state(f, job_id) == "queued"
    assert {p[0] for p in publisher.published} == {expired, lost}


async def test_adm16_simultaneous_requeues_win_once(session_factory: Factory) -> None:
    f = session_factory
    job_id = await create_job(f, FakePublisher(), "noop")
    await sql(f, "UPDATE jobs SET status = 'failed' WHERE id = :id", id=job_id)
    publisher = FakePublisher(delay=0.2)
    outcomes = await asyncio.gather(
        *[retry_job(f, publisher, job_id, **KW) for _ in range(6)], return_exceptions=True
    )
    assert sum(not isinstance(o, Exception) for o in outcomes) == 1
    assert len(publisher.published) == 1


# ------------------------------------------------------------------------ rejected retries


@pytest.mark.parametrize("case", ["done", "processing_live", "queued", "publishing", "young"])
async def test_adm16_retry_is_rejected_for_done_active_or_healthy_jobs(
    session_factory: Factory, case: str
) -> None:
    f = session_factory
    job_id = await create_job(
        f, FakePublisher(), "noop", publish=case not in {"publishing", "young"}
    )
    if case == "done":
        await sql(f, "UPDATE jobs SET status = 'done' WHERE id = :id", id=job_id)
    elif case == "processing_live":
        await sql(
            f,
            "UPDATE jobs SET status = 'processing', lease_expires_at = now() + interval '1 minute'"
            " WHERE id = :id",
            id=job_id,
        )
    elif case == "publishing":
        await sql(
            f,
            "UPDATE outbox SET lease_expires_at = now() + interval '1 minute' WHERE job_id = :id",
            id=job_id,
        )
    before = await state(f, job_id)
    publisher = FakePublisher()
    with pytest.raises(NotRetryableError) as excinfo:
        await retry_job(f, publisher, job_id, **KW)
    assert excinfo.value.state == before and publisher.published == []
    assert await state(f, job_id) == before  # nothing changed


async def test_adm16_unknown_job_is_not_found(session_factory: Factory) -> None:
    with pytest.raises(JobNotFoundError):
        await retry_job(session_factory, FakePublisher(), uuid.uuid4(), **KW)


async def test_adm16_requeue_rolls_back_when_outbox_is_not_published(
    session_factory: Factory,
) -> None:
    f = session_factory
    job_id = await create_job(f, None, "noop", publish=False)  # outbox stays pending
    await sql(f, "UPDATE jobs SET status = 'failed' WHERE id = :id", id=job_id)
    with pytest.raises(NotRetryableError):
        await retry_job(f, FakePublisher(), job_id, **KW)
    async with f() as s:
        assert (await s.execute(text("SELECT status FROM jobs"))).scalar_one() == "failed"
