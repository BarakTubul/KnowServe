"""Job delivery states and manual retry (ING-13, ING-16, ADM-16 core; M0 spike surface).

Two different failures need two different retries, so they are told apart from existing columns
(no schema change):

* **Publish failure** (the job never reached QStash): the outbox row is still ``pending``.
  States ``publish_failed`` (the publish was rejected or timed out) and ``unpublished_stuck``
  (no error, older than the grace period, for example the API crashed after commit). Retry =
  *republish*: claim the outbox row and publish through the shared outbox code.
* **Processing failure** (delivered, the handler failed or never finished): the outbox row is
  ``published``. States ``failed`` (attempts exhausted), ``queued_stuck`` (nothing happened for
  ``stuck_after_seconds``: message lost or QStash retries exhausted) and ``processing_stuck``
  (the lease expired). Retry = *requeue*: reset the job and re-arm the outbox row in one
  transaction, then publish.

A job that is ``done`` or has a live processing/publishing lease is never retried. Every guard is
repeated inside the UPDATE that performs the retry, so two simultaneous retries cannot both win.
Duplicate deliveries a retry may cause are safe: the Worker claims atomically and skips done jobs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .jobs import MANUAL_RETRY_MARKER, enqueue_job
from .outbox import publish_after_commit, republish_manual
from .qstash import Publisher

DeliveryState = Literal[
    "publishing",
    "publish_pending",
    "publish_failed",
    "unpublished_stuck",
    "queued",
    "queued_stuck",
    "processing",
    "processing_stuck",
    "failed",
    "done",
]
RetryAction = Literal["republish", "requeue"]

REPUBLISH_STATES: frozenset[str] = frozenset({"publish_failed", "unpublished_stuck"})
REQUEUE_STATES: frozenset[str] = frozenset({"failed", "queued_stuck", "processing_stuck"})
ATTENTION_STATES: frozenset[str] = REPUBLISH_STATES | REQUEUE_STATES

_SELECT = """
    SELECT j.id, j.job_type, j.status AS job_status, j.attempts AS job_attempts,
           j.last_error AS job_error, j.correlation_id, j.created_at, j.updated_at,
           o.attempts AS outbox_attempts, o.last_error AS publish_error,
           CASE
             WHEN j.status = 'done' THEN 'done'
             WHEN j.status = 'failed' THEN 'failed'
             WHEN o.status = 'pending' AND o.lease_expires_at > now() THEN 'publishing'
             WHEN o.status = 'pending' AND o.last_error IS NOT NULL THEN 'publish_failed'
             WHEN o.status = 'pending'
                  AND o.created_at < now() - make_interval(secs => :grace)
                  THEN 'unpublished_stuck'
             WHEN o.status = 'pending' THEN 'publish_pending'
             WHEN j.status = 'processing' AND j.lease_expires_at < now() THEN 'processing_stuck'
             WHEN j.status = 'processing' THEN 'processing'
             WHEN j.status = 'queued'
                  AND greatest(coalesce(o.published_at, o.created_at), j.updated_at)
                      < now() - make_interval(secs => :stuck)
                  THEN 'queued_stuck'
             ELSE 'queued'
           END AS delivery_state
    FROM jobs j JOIN outbox o ON o.job_id = j.id
"""

_REQUEUE_JOB = text(
    """
    UPDATE jobs SET status = 'queued', attempts = 0, claimed_by = NULL,
                    lease_expires_at = NULL, updated_at = now(),
                    last_error = left(
                        :marker || '; previous: ' || coalesce(last_error, 'none'), 500)
    WHERE id = :id
      AND (status = 'failed'
           OR (status = 'processing' AND lease_expires_at < now())
           OR (status = 'queued'
               AND greatest(
                     coalesce((SELECT published_at FROM outbox WHERE job_id = jobs.id), created_at),
                     updated_at) < now() - make_interval(secs => :stuck)))
    RETURNING id
    """
)
_REARM_OUTBOX = text(
    """
    UPDATE outbox SET status = 'pending', published_at = NULL, attempts = 0,
                      lease_expires_at = NULL, next_attempt_at = now(), last_error = NULL
    WHERE job_id = :id AND status = 'published'
    """
)


class _Skip(Exception):
    """Internal: abandon the requeue transaction."""


class JobNotFoundError(Exception):
    """No job with that id."""


class NotRetryableError(Exception):
    """The job is not in a retryable state (done, in progress, or claimed by someone else)."""

    def __init__(self, state: str) -> None:
        super().__init__(f"job is {state}")
        self.state = state


@dataclass(frozen=True)
class JobView:
    job_id: uuid.UUID
    job_type: str
    delivery_state: DeliveryState
    job_status: str
    attempts: int
    publish_attempts: int
    last_error: str | None
    publish_error: str | None
    correlation_id: str
    created_at: datetime
    updated_at: datetime

    @property
    def retry_action(self) -> RetryAction | None:
        if self.delivery_state in REPUBLISH_STATES:
            return "republish"
        if self.delivery_state in REQUEUE_STATES:
            return "requeue"
        return None


@dataclass(frozen=True)
class RetryResult:
    action: RetryAction
    published: bool


def _view(row) -> JobView:  # type: ignore[no-untyped-def]
    return JobView(
        job_id=row.id,
        job_type=row.job_type,
        delivery_state=row.delivery_state,
        job_status=row.job_status,
        attempts=row.job_attempts,
        publish_attempts=row.outbox_attempts,
        last_error=row.job_error,
        publish_error=row.publish_error,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def get_job_view(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    *,
    grace_seconds: int,
    stuck_after_seconds: int,
) -> JobView | None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(_SELECT + " WHERE j.id = :id"),
                {"id": job_id, "grace": grace_seconds, "stuck": stuck_after_seconds},
            )
        ).first()
    return _view(row) if row else None


async def list_job_views(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    grace_seconds: int,
    stuck_after_seconds: int,
    states: frozenset[str] | None = None,
    limit: int = 50,
) -> list[JobView]:
    """Newest first. ``states=ATTENTION_STATES`` lists what an operator can retry.

    One read when the operator looks; nothing polls the database.
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(_SELECT + " ORDER BY j.created_at DESC LIMIT :limit"),
                {"grace": grace_seconds, "stuck": stuck_after_seconds, "limit": limit * 4},
            )
        ).all()
    views = [_view(row) for row in rows]
    if states is not None:
        views = [v for v in views if v.delivery_state in states]
    return views[:limit]


async def _requeue(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID, stuck_after_seconds: int
) -> bool:
    """Reset the job and re-arm its outbox row atomically. False if the guard did not match."""
    try:
        async with session_factory() as session, session.begin():
            reset = await session.execute(
                _REQUEUE_JOB,
                {"id": job_id, "stuck": stuck_after_seconds, "marker": MANUAL_RETRY_MARKER},
            )
            if reset.first() is None:
                raise _Skip
            rearmed = await session.execute(_REARM_OUTBOX, {"id": job_id})
            if rearmed.rowcount != 1:  # type: ignore[attr-defined]
                raise _Skip  # outbox not published: not a processing failure; roll back
    except _Skip:
        return False
    return True


async def retry_job(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    job_id: uuid.UUID,
    *,
    grace_seconds: int,
    stuck_after_seconds: int,
    publish_timeout: float = 5.0,
) -> RetryResult:
    """Retry the right way for the job's current state, or raise.

    Raises ``JobNotFoundError`` or ``NotRetryableError`` (the API maps these to 404 and 409).
    """
    view = await get_job_view(
        session_factory,
        job_id,
        grace_seconds=grace_seconds,
        stuck_after_seconds=stuck_after_seconds,
    )
    if view is None:
        raise JobNotFoundError
    action = view.retry_action
    if action is None:
        raise NotRetryableError(view.delivery_state)
    if action == "republish":
        outcome = await republish_manual(
            session_factory,
            publisher,
            job_id,
            grace_seconds=grace_seconds,
            publish_timeout=publish_timeout,
        )
        if outcome is None:
            raise NotRetryableError(
                await _state_now(session_factory, job_id, grace_seconds, stuck_after_seconds)
            )
        return RetryResult("republish", outcome)
    if not await _requeue(session_factory, job_id, stuck_after_seconds):
        raise NotRetryableError(
            await _state_now(session_factory, job_id, grace_seconds, stuck_after_seconds)
        )
    published = await publish_after_commit(
        session_factory, publisher, job_id, publish_timeout=publish_timeout
    )
    return RetryResult("requeue", published)


async def _state_now(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    grace_seconds: int,
    stuck_after_seconds: int,
) -> str:
    view = await get_job_view(
        session_factory,
        job_id,
        grace_seconds=grace_seconds,
        stuck_after_seconds=stuck_after_seconds,
    )
    return view.delivery_state if view else "missing"


async def create_job(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher | None,
    job_type: str,
    *,
    correlation_id: str | None = None,
    publish: bool = True,
    publish_timeout: float = 5.0,
) -> uuid.UUID:
    """Commit a job and its outbox row, then (awaited) try the immediate publish.

    ``publish=False`` leaves the row pending exactly as an API crash after commit would; it is a
    test hook the caller must gate.
    """
    async with session_factory() as session, session.begin():
        job = await enqueue_job(session, job_type, correlation_id)
        job_id = job.id
    if publish and publisher is not None:
        await publish_after_commit(
            session_factory, publisher, job_id, publish_timeout=publish_timeout
        )
    return job_id
