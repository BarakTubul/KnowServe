"""Transactional outbox publishing (ING-13, ING-14, M0-AC10).

Publishing is at-least-once: a row is claimed with a lease, published outside any DB lock, then
marked ``published``. If the process dies in between, the lease expires and a later dispatch
publishes it again; the Worker is idempotent (ING-15). Nothing here claims exactly-once delivery.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import request_context
from .qstash import Publisher, PublishError

logger = logging.getLogger("knowserve.outbox")

_MAX_BACKOFF_SECONDS = 300
_BASE_BACKOFF_SECONDS = 5

# Claim = lease + attempts+1 in one statement. SKIP LOCKED lets concurrent dispatchers take
# disjoint rows. The lease check also lets a crashed dispatcher's rows be picked up again.
_CLAIM_BATCH = text(
    """
    UPDATE outbox SET lease_expires_at = now() + make_interval(secs => :lease),
                      attempts = attempts + 1
    WHERE id IN (
        SELECT id FROM outbox
        WHERE status = 'pending' AND next_attempt_at <= now()
          AND (lease_expires_at IS NULL OR lease_expires_at < now())
        ORDER BY next_attempt_at, created_at
        LIMIT :batch
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, job_id, correlation_id
    """
)
_CLAIM_ONE = text(
    """
    UPDATE outbox SET lease_expires_at = now() + make_interval(secs => :lease),
                      attempts = attempts + 1
    WHERE id IN (
        SELECT id FROM outbox
        WHERE job_id = :job_id AND status = 'pending'
          AND (lease_expires_at IS NULL OR lease_expires_at < now())
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, job_id, correlation_id
    """
)
_MARK_PUBLISHED = text(
    """
    UPDATE outbox SET status = 'published', published_at = now(),
                      lease_expires_at = NULL, last_error = NULL
    WHERE id = :id AND status = 'pending'
    """
)
_MARK_FAILED = text(
    """
    UPDATE outbox SET lease_expires_at = NULL, last_error = :error,
                      next_attempt_at = now() + make_interval(secs => :backoff)
    WHERE id = :id AND status = 'pending'
    """
)


@dataclass(frozen=True)
class DispatchResult:
    published: int
    failed: int


@dataclass(frozen=True)
class _Claimed:
    id: uuid.UUID
    job_id: uuid.UUID
    correlation_id: str


def _backoff_seconds(attempts: int) -> int:
    return min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * 2 ** max(0, attempts - 1))


async def _attempts(session: AsyncSession, outbox_id: uuid.UUID) -> int:
    row = await session.execute(
        text("SELECT attempts FROM outbox WHERE id = :id"), {"id": outbox_id}
    )
    return int(row.scalar_one())


async def _deliver(
    session_factory: async_sessionmaker[AsyncSession], publisher: Publisher, claimed: _Claimed
) -> bool:
    """Publish one claimed row, then mark it published or back off. Returns True on success."""
    request_context.set_correlation_id(claimed.correlation_id)
    try:
        await publisher.publish(claimed.job_id, claimed.correlation_id)
    except PublishError as exc:
        error = str(exc)[:300]
    except Exception as exc:
        error = f"unexpected {type(exc).__name__}"[:300]
    else:
        async with session_factory() as session, session.begin():
            await session.execute(_MARK_PUBLISHED, {"id": claimed.id})
        logger.info("outbox row published", extra={"job_id": str(claimed.job_id)})
        return True
    async with session_factory() as session, session.begin():
        backoff = _backoff_seconds(await _attempts(session, claimed.id))
        await session.execute(_MARK_FAILED, {"id": claimed.id, "error": error, "backoff": backoff})
    logger.warning(
        "outbox publish failed; will retry",
        extra={"job_id": str(claimed.job_id), "error": error},
    )
    return False


async def publish_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    job_id: uuid.UUID,
    lease_seconds: int = 60,
) -> bool:
    """Best-effort immediate publish for one job's outbox row, called after the caller commits.

    Never raises: failures are logged and the row stays ``pending`` for ``dispatch_pending``.
    Returns True only if this call published the row.
    """
    try:
        async with session_factory() as session, session.begin():
            result = await session.execute(_CLAIM_ONE, {"job_id": job_id, "lease": lease_seconds})
            row = result.first()
        if row is None:
            return False
        return await _deliver(session_factory, publisher, _Claimed(*row))
    except Exception as exc:
        logger.warning(
            "publish_after_commit failed; recovery dispatcher will retry",
            extra={"job_id": str(job_id), "error_type": type(exc).__name__},
        )
        return False


async def dispatch_pending(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    batch_size: int = 20,
    lease_seconds: int = 60,
) -> DispatchResult:
    """Claim due ``pending`` rows (FOR UPDATE SKIP LOCKED + lease), publish, mark or back off."""
    async with session_factory() as session, session.begin():
        result = await session.execute(_CLAIM_BATCH, {"batch": batch_size, "lease": lease_seconds})
        claimed = [_Claimed(*row) for row in result.all()]
    published = failed = 0
    for item in claimed:
        if await _deliver(session_factory, publisher, item):
            published += 1
        else:
            failed += 1
    return DispatchResult(published=published, failed=failed)
