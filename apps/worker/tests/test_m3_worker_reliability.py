"""M3-00a Worker reliability tests (ING-10, ING-15, ING-16, ING-19, ING-23, SEC-14; M3-AC05,
M3-AC06, M3-AC19).

Real PostgreSQL, fake QStash signatures (as in the M0 Worker tests), no real providers. The
terminal-failure and requeue hooks run against real ``documents`` and ``document_revisions`` rows.
Security and reliability gates: no skips, no xfails.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from conftest import sign_qstash_delivery
from knowserve_core.ingestion_contract import FailureCode
from knowserve_core.job_claims import claim_job, fail_job
from knowserve_core.job_fencing import LostClaimError, assert_claimed
from knowserve_core.job_hooks import NonRetryableJobError, RetryableJobError
from knowserve_core.job_recovery import retry_job
from knowserve_core.jobs import enqueue_job
from knowserve_core.qstash import FakePublisher
from knowserve_core.revision_hooks import mark_revision_failed
from knowserve_core.settings import Settings
from knowserve_core.testing import make_document
from knowserve_worker.app import JobContext, create_app

pytestmark = [pytest.mark.m3, pytest.mark.worker, pytest.mark.integration]

CURRENT = "local-only-qstash-current-key-not-a-secret"
NEXT = "local-only-qstash-next-key-not-a-secret"
PUBLIC_URL = "https://worker.test"
RUN_URL = PUBLIC_URL + "/internal/jobs/run"
INGEST = "ingest_revision"
Factory = async_sessionmaker[AsyncSession]
Handler = Callable[[JobContext], Awaitable[None]]


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "env": "local",
        "qstash_current_signing_key": CURRENT,
        "qstash_next_signing_key": NEXT,
        "worker_public_url": PUBLIC_URL,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class Harness:
    def __init__(self, engine: AsyncEngine, factory: Factory, url: str) -> None:
        self.engine, self.factory, self.url = engine, factory, url
        self.calls: list[JobContext] = []
        self.behavior: Handler | None = None

    async def handler(self, ctx: JobContext) -> None:
        self.calls.append(ctx)
        if self.behavior is not None:
            await self.behavior(ctx)

    def app(self, settings_update: dict[str, Any] | None = None, **settings: Any) -> Any:
        s = make_settings(self.url, **settings)
        if settings_update:
            # model_copy skips validation: the handler timeout may exceed the lease only because
            # the heartbeat keeps the lease alive (tests of exactly that).
            s = s.model_copy(update=settings_update)
        return create_app(
            settings=s,
            engine=self.engine,
            publisher=FakePublisher(),
            handlers={INGEST: self.handler},
            heartbeat_interval=0.1,
        )

    def client(self, app: Any) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL, timeout=30)

    async def deliver(self, client: httpx.AsyncClient, job_id: uuid.UUID) -> httpx.Response:
        body = json.dumps({"schema_version": 1, "job_id": str(job_id)}).encode()
        token = sign_qstash_delivery(body, CURRENT, RUN_URL)
        return await client.post(
            "/internal/jobs/run", content=body, headers={"Upstash-Signature": token}
        )

    async def job_with_revision(
        self, *, revision_status: str = "queued", job_type: str = INGEST
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """A job linked to a revision, as the upload path will create them."""
        async with self.factory() as s, s.begin():
            doc = await make_document(s, status=revision_status)
            job = await enqueue_job(s, job_type)
            revision_id = (
                await s.execute(
                    text(
                        "UPDATE document_revisions SET job_id = :j WHERE document_id = :d "
                        "RETURNING id"
                    ),
                    {"j": job.id, "d": doc.id},
                )
            ).scalar_one()
            return job.id, revision_id

    async def job(self, job_id: uuid.UUID) -> Any:
        async with self.factory() as s:
            return (
                await s.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id})
            ).one()

    async def revision(self, revision_id: uuid.UUID) -> Any:
        async with self.factory() as s:
            return (
                await s.execute(
                    text("SELECT * FROM document_revisions WHERE id = :id"), {"id": revision_id}
                )
            ).one()

    async def sql(self, statement: str, **params: Any) -> None:
        async with self.factory() as s, s.begin():
            await s.execute(text(statement), params)


@pytest_asyncio.fixture
async def h(
    engine: AsyncEngine, session_factory: Factory, database_url: str
) -> AsyncIterator[Harness]:
    yield Harness(engine, session_factory, database_url)


def raising(exc: Exception) -> Handler:
    async def _raise(ctx: JobContext) -> None:
        raise exc

    return _raise


# ----------------------------------------------------------------------- non-retryable (ING-23)


async def test_ing23_non_retryable_error_fails_job_and_revision_at_once(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision()
    await h.sql("UPDATE document_revisions SET status='processing', phase='extracting'")
    h.behavior = raising(NonRetryableJobError(FailureCode.NO_EXTRACTABLE_TEXT))
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
        redelivery = await h.deliver(c, job_id)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "JOB_FAILED_PERMANENTLY"
    job = await h.job(job_id)
    assert (job.status, job.attempts, job.claimed_by, job.lease_expires_at) == (
        "failed",
        1,
        None,
        None,
    )
    assert job.last_error == "NO_EXTRACTABLE_TEXT"
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason, revision.phase) == (
        "failed",
        "NO_EXTRACTABLE_TEXT",
        None,
    )
    # No automatic retry: the redelivery finds `failed` and answers 200 without running.
    assert redelivery.status_code == 200 and redelivery.json() == {"result": "failed"}
    assert len(h.calls) == 1


async def test_ing23_terminal_hook_never_touches_a_ready_revision(h: Harness) -> None:
    """Reindex mode (OPEN-31 D4): a failure never turns a published revision `failed`."""
    job_id, revision_id = await h.job_with_revision(revision_status="ready")
    h.behavior = raising(NonRetryableJobError(FailureCode.INVALID_PDF))
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    assert (await h.job(job_id)).status == "failed"
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason) == ("ready", None)


# ----------------------------------------------------------------------- cap and retries (ING-16)


async def test_ing16_retryable_failure_requeues_and_the_fourth_attempt_fails_the_revision(
    h: Harness,
) -> None:
    job_id, revision_id = await h.job_with_revision()
    h.behavior = raising(RetryableJobError(FailureCode.EMBEDDING_FAILED))
    app = h.app()
    codes: list[int] = []
    async with h.client(app) as c:
        for attempt in range(1, 4):
            codes.append((await h.deliver(c, job_id)).status_code)
            job = await h.job(job_id)
            assert (job.status, job.attempts, job.last_error) == (
                "queued",
                attempt,
                "EMBEDDING_FAILED",
            )
            # The revision is not failed while attempts remain.
            assert (await h.revision(revision_id)).status == "queued"
        fourth = await h.deliver(c, job_id)
        fifth = await h.deliver(c, job_id)
    assert codes == [500, 500, 500]
    assert fourth.status_code == 500
    assert fourth.json()["error"]["code"] == "JOB_FAILED_PERMANENTLY"
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("failed", 4)
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason) == ("failed", "EMBEDDING_FAILED")
    assert fifth.status_code == 200 and fifth.json() == {"result": "failed"}
    assert len(h.calls) == 4  # the 4-attempt cap, never a fifth run


async def test_ing16_unexpected_exception_ends_as_internal_error(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision()
    h.behavior = raising(RuntimeError("boom"))
    async with h.client(h.app(job_max_attempts=1)) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason) == ("failed", "INTERNAL_ERROR")


async def test_ing16_handler_timeout_ends_as_processing_timeout(h: Harness) -> None:
    async def slow(ctx: JobContext) -> None:
        await asyncio.sleep(5)

    job_id, revision_id = await h.job_with_revision()
    h.behavior = slow
    app = h.app(job_max_attempts=1, job_lease_seconds=3, job_handler_timeout_seconds=1)
    async with h.client(app) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    assert (await h.revision(revision_id)).failure_reason == "PROCESSING_TIMEOUT"


async def test_ing21_job_without_handler_fails_the_revision_too(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision(job_type="no_such_type")
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 200 and response.json() == {"result": "failed"}
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason) == ("failed", "INTERNAL_ERROR")


async def test_ing16_deliveries_that_do_not_claim_use_no_attempt(h: Harness) -> None:
    """Concurrent duplicate deliveries: one claim (one attempt); the rest get 409 or 200."""

    async def slow(ctx: JobContext) -> None:
        await asyncio.sleep(0.5)

    job_id, _ = await h.job_with_revision()
    h.behavior = slow
    async with h.client(h.app()) as c:
        responses = await asyncio.gather(*(h.deliver(c, job_id) for _ in range(6)))
        later = await h.deliver(c, job_id)
    assert {r.status_code for r in responses} <= {200, 409}
    assert later.json() == {"result": "already_done"}
    assert len(h.calls) == 1
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("done", 1)


# ----------------------------------------------------------------------- crash guard (F5, ING-19)


async def test_ing19_expired_lease_is_reclaimed_and_runs(h: Harness) -> None:
    job_id, _ = await h.job_with_revision()
    await h.sql(
        "UPDATE jobs SET status='processing', attempts=1, claimed_by='dead', "
        "lease_expires_at = now() - interval '1 minute' WHERE id = :id",
        id=job_id,
    )
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    assert len(h.calls) == 1 and h.calls[0].attempts == 2
    assert (await h.job(job_id)).attempts == 2


@pytest.mark.parametrize("stored_status", ["processing", "queued"])
async def test_ing19_claim_checks_the_attempt_cap_and_ends_a_crash_loop(
    h: Harness, stored_status: str
) -> None:
    """F5: a job past the cap is never run again. It ends `failed` / PROCESSING_CRASHED."""
    job_id, revision_id = await h.job_with_revision()
    await h.sql("UPDATE document_revisions SET status='processing', phase='embedding'")
    await h.sql(
        "UPDATE jobs SET status=:s, attempts=4, claimed_by='dead', "
        "lease_expires_at = now() - interval '1 minute' WHERE id = :id",
        id=job_id,
        s=stored_status,
    )
    async with h.client(h.app()) as c:
        first = await h.deliver(c, job_id)
        second = await h.deliver(c, job_id)
    assert h.calls == []
    assert first.status_code == 500
    assert first.json()["error"]["code"] == "JOB_FAILED_PERMANENTLY"
    job = await h.job(job_id)
    assert (job.status, job.attempts, job.claimed_by) == ("failed", 4, None)
    assert job.last_error is not None and job.last_error.startswith("PROCESSING_CRASHED")
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason) == ("failed", "PROCESSING_CRASHED")
    assert second.status_code == 200 and second.json() == {"result": "failed"}


async def test_ing19_a_live_lease_past_the_cap_is_left_alone(h: Harness) -> None:
    """The 4th attempt may still be running: the cap check must not fail it."""
    job_id, _ = await h.job_with_revision()
    await h.sql(
        "UPDATE jobs SET status='processing', attempts=4, claimed_by='running', "
        "lease_expires_at = now() + interval '1 minute' WHERE id = :id",
        id=job_id,
    )
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 409 and response.json()["error"]["code"] == "JOB_IN_PROGRESS"
    assert (await h.job(job_id)).status == "processing" and h.calls == []


# ----------------------------------------------------------------------- heartbeat (F6)


async def test_ing19_heartbeat_keeps_the_lease_alive_past_its_original_expiry(h: Harness) -> None:
    """Lease 2 s, handler 3 s: without renewal a second delivery at 2.5 s would reclaim the job."""
    seen: dict[str, Any] = {}

    async def long_job(ctx: JobContext) -> None:
        await asyncio.sleep(2.5)
        seen["second"] = None
        async with h.factory() as s:
            seen["lease"] = (
                await s.execute(
                    text("SELECT lease_expires_at > now() AS live FROM jobs WHERE id = :id"),
                    {"id": ctx.job_id},
                )
            ).scalar_one()
        await asyncio.sleep(0.5)

    job_id, _ = await h.job_with_revision()
    h.behavior = long_job
    app = h.app(
        settings_update={"job_handler_timeout_seconds": 10},
        job_lease_seconds=2,
        job_handler_timeout_seconds=1,
    )
    async with h.client(app) as c:
        first = asyncio.ensure_future(h.deliver(c, job_id))
        await asyncio.sleep(2.3)  # past the original 2 s lease
        duplicate = await h.deliver(c, job_id)
        result = await first
    assert duplicate.status_code == 409  # still leased: the heartbeat renewed it
    assert seen["lease"] is True
    assert result.json() == {"result": "done"}
    assert len(h.calls) == 1 and (await h.job(job_id)).attempts == 1


async def test_ing19_worker_that_loses_its_claim_stops_and_writes_nothing(h: Harness) -> None:
    """The heartbeat notices the claim is gone, cancels the handler and answers 409."""
    cancelled = asyncio.Event()

    async def victim(ctx: JobContext) -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    job_id, revision_id = await h.job_with_revision()
    h.behavior = victim
    async with h.client(h.app()) as c:
        task = asyncio.ensure_future(h.deliver(c, job_id))
        await asyncio.sleep(0.4)
        # Another worker takes the job over (lease lapsed, reclaimed).
        await h.sql(
            "UPDATE jobs SET claimed_by='usurper', attempts=2, "
            "lease_expires_at = now() + interval '1 minute' WHERE id = :id",
            id=job_id,
        )
        response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409 and response.json()["error"]["code"] == "JOB_CLAIM_LOST"
    assert cancelled.is_set()
    job = await h.job(job_id)
    assert (job.status, job.claimed_by, job.attempts) == ("processing", "usurper", 2)
    assert (await h.revision(revision_id)).status == "queued"


# ----------------------------------------------------------------------- fencing (F7)


async def test_ing15_fence_rejects_a_stale_worker_and_accepts_the_current_one(h: Harness) -> None:
    job_id, _ = await h.job_with_revision()
    for me in ("worker-a", "worker-b"):
        await h.sql(
            "UPDATE jobs SET status='processing', claimed_by=:me, "
            "lease_expires_at = now() + interval '1 minute' WHERE id = :id",
            id=job_id,
            me=me,
        )
        if me == "worker-b":
            async with h.factory() as s, s.begin():
                await assert_claimed(s, job_id, "worker-b")
            async with h.factory() as s, s.begin():
                with pytest.raises(LostClaimError):
                    await assert_claimed(s, job_id, "worker-a")  # the stale writer


async def test_ing15_fence_fails_when_the_job_is_not_processing_or_missing(h: Harness) -> None:
    job_id, _ = await h.job_with_revision()
    await h.sql("UPDATE jobs SET claimed_by='worker-a', status='done' WHERE id = :id", id=job_id)
    async with h.factory() as s, s.begin():
        with pytest.raises(LostClaimError):
            await assert_claimed(s, job_id, "worker-a")
    async with h.factory() as s, s.begin():
        with pytest.raises(LostClaimError):
            await assert_claimed(s, uuid.uuid4(), "worker-a")


async def test_ing15_fenced_write_by_a_stale_handler_changes_nothing(h: Harness) -> None:
    """The handler's claim is taken over; its fenced write raises and the row stays as it was."""

    async def stale_writer(ctx: JobContext) -> None:
        await h.sql("UPDATE jobs SET claimed_by='usurper' WHERE id = :id", id=ctx.job_id)
        async with h.factory() as s, s.begin():
            await ctx.fence(s)
            await s.execute(text("UPDATE document_revisions SET phase = 'publishing'"))

    job_id, revision_id = await h.job_with_revision()
    h.behavior = stale_writer
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 409 and response.json()["error"]["code"] == "JOB_CLAIM_LOST"
    revision = await h.revision(revision_id)
    assert revision.phase is None
    job = await h.job(job_id)
    assert (job.status, job.claimed_by) == ("processing", "usurper")


async def test_ing15_fence_holds_the_row_so_a_reclaim_waits_for_the_transaction(
    h: Harness,
) -> None:
    job_id, _ = await h.job_with_revision()
    await h.sql(
        "UPDATE jobs SET status='processing', attempts=1, claimed_by='worker-a', "
        "lease_expires_at = now() - interval '1 minute' WHERE id = :id",
        id=job_id,
    )
    async with h.factory() as writer, writer.begin():
        await assert_claimed(writer, job_id, "worker-a")  # fence passes even with a lapsed lease
        reclaim = asyncio.ensure_future(
            claim_job(
                h.factory,
                job_id,
                "worker-b",
                lease_seconds=60,
                max_attempts=4,
                terminal_hook=mark_revision_failed,
            )
        )
        await asyncio.sleep(0.5)
        assert not reclaim.done()  # blocked by the fence's row lock
    result = await asyncio.wait_for(reclaim, 5)
    assert result.kind == "claimed"


# ----------------------------------------------------------------------- hooks


async def test_ing15_terminal_hook_failure_rolls_the_job_update_back(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision()
    await h.sql(
        "UPDATE jobs SET status='processing', claimed_by='me', "
        "lease_expires_at = now() + interval '1 minute' WHERE id = :id",
        id=job_id,
    )

    async def broken_hook(
        session: AsyncSession, job_id: uuid.UUID, failure_code: FailureCode
    ) -> None:
        raise RuntimeError("hook broke")

    with pytest.raises(RuntimeError):
        await fail_job(h.factory, job_id, "me", FailureCode.INVALID_PDF, "x", broken_hook)
    assert (await h.job(job_id)).status == "processing"  # job and revision still agree
    assert (await h.revision(revision_id)).status == "queued"


async def test_ing15_terminal_hook_does_not_run_for_a_lost_claim(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision()
    await h.sql(
        "UPDATE jobs SET status='processing', claimed_by='usurper', "
        "lease_expires_at = now() + interval '1 minute' WHERE id = :id",
        id=job_id,
    )
    ok = await fail_job(
        h.factory, job_id, "stale", FailureCode.INVALID_PDF, "x", mark_revision_failed
    )
    assert ok is False
    assert (await h.job(job_id)).status == "processing"
    assert (await h.revision(revision_id)).status == "queued"


async def test_adm16_requeue_hook_puts_the_revision_back_to_queued(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision()
    await h.sql(
        "UPDATE document_revisions SET status='failed', failure_reason='EMBEDDING_FAILED', "
        "phase='embedding' WHERE id = :r",
        r=revision_id,
    )
    await h.sql("UPDATE jobs SET status='failed', attempts=4 WHERE id = :id", id=job_id)
    await h.sql(
        "UPDATE outbox SET status='published', published_at=now() WHERE job_id = :id", id=job_id
    )
    result = await retry_job(
        h.factory, FakePublisher(), job_id, grace_seconds=120, stuck_after_seconds=900
    )
    assert result.action == "requeue"
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("queued", 0)
    revision = await h.revision(revision_id)
    assert (revision.status, revision.failure_reason, revision.phase) == ("queued", None, None)


async def test_adm16_requeue_hook_leaves_a_ready_revision_alone(h: Harness) -> None:
    job_id, revision_id = await h.job_with_revision(revision_status="ready")
    await h.sql("UPDATE jobs SET status='failed', attempts=4 WHERE id = :id", id=job_id)
    await h.sql(
        "UPDATE outbox SET status='published', published_at=now() WHERE job_id = :id", id=job_id
    )
    await retry_job(h.factory, FakePublisher(), job_id, grace_seconds=120, stuck_after_seconds=900)
    assert (await h.revision(revision_id)).status == "ready"


async def test_adm16_requeue_hook_failure_leaves_job_and_revision_unchanged(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id, revision_id = await h.job_with_revision()
    await h.sql(
        "UPDATE document_revisions SET status='failed', failure_reason='INVALID_PDF' WHERE id = :r",
        r=revision_id,
    )
    await h.sql("UPDATE jobs SET status='failed', attempts=4 WHERE id = :id", id=job_id)
    await h.sql(
        "UPDATE outbox SET status='published', published_at=now() WHERE job_id = :id", id=job_id
    )

    async def broken(session: AsyncSession, job_id: uuid.UUID) -> None:
        raise RuntimeError("requeue hook broke")

    monkeypatch.setattr("knowserve_core.job_recovery.requeue_revision", broken)
    with pytest.raises(RuntimeError):
        await retry_job(
            h.factory, FakePublisher(), job_id, grace_seconds=120, stuck_after_seconds=900
        )
    assert (await h.job(job_id)).status == "failed"
    assert (await h.revision(revision_id)).status == "failed"


async def test_adm16_requeue_after_a_terminal_failure_runs_again_from_attempt_one(
    h: Harness,
) -> None:
    """End to end: fail permanently, retry, the next delivery is attempt 1 and can succeed."""
    job_id, revision_id = await h.job_with_revision()
    h.behavior = raising(NonRetryableJobError(FailureCode.INVALID_PDF))
    app = h.app()
    async with h.client(app) as c:
        await h.deliver(c, job_id)
        await h.sql(
            "UPDATE outbox SET status='published', published_at=now() WHERE job_id = :id", id=job_id
        )
        await retry_job(
            h.factory, FakePublisher(), job_id, grace_seconds=120, stuck_after_seconds=900
        )
        assert (await h.revision(revision_id)).status == "queued"
        h.behavior = None
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("done", 1)
