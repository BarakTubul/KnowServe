"""Transactional outbox publishing (ING-13, ING-14, M0-AC10).

Publishing is at-least-once: a row is claimed with a lease, published outside any DB lock, then
marked ``published``. If the process dies in between, the lease expires and a later publish
(manual retry, or the optional batch dispatcher) publishes it again; the Worker is idempotent
(ING-15). Nothing here claims exactly-once delivery.

Claim ownership: each claim bumps ``attempts`` and returns the new value. Marking a row
``published`` or backing it off requires that value to still match, so a holder whose lease
expired can never overwrite a newer claim (ING-14).

One publishing implementation (``_deliver``) serves the immediate path, manual republish and the
optional batch dispatcher. Only ``dispatch_pending`` claims more than one row.
"""

from __future__ import annotations

import asyncio
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

# Claim = lease + attempts+1 in one statement. SKIP LOCKED lets concurrent claimers take
# disjoint rows. The lease check also lets a crashed holder's rows be picked up again.
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
    RETURNING id, job_id, correlation_id, attempts
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
    RETURNING id, job_id, correlation_id, attempts
    """
)
# Manual republish (publish-failure retry). Eligible only while the job is still queued and the
# row either failed to publish (last_error) or was never published for longer than the grace
# period (for example the API crashed after commit). Ignores backoff, respects a live lease.
_CLAIM_MANUAL = text(
    """
    UPDATE outbox SET lease_expires_at = now() + make_interval(secs => :lease),
                      attempts = attempts + 1
    WHERE id IN (
        SELECT o.id FROM outbox o
        WHERE o.job_id = :job_id AND o.status = 'pending'
          AND (o.lease_expires_at IS NULL OR o.lease_expires_at < now())
          AND (o.last_error IS NOT NULL
               OR o.created_at < now() - make_interval(secs => :grace))
          AND EXISTS (SELECT 1 FROM jobs j WHERE j.id = o.job_id AND j.status = 'queued')
        FOR UPDATE OF o SKIP LOCKED
    )
    RETURNING id, job_id, correlation_id, attempts
    """
)
_MARK_PUBLISHED = text(
    """
    UPDATE outbox SET status = 'published', published_at = now(),
                      lease_expires_at = NULL, last_error = NULL
    WHERE id = :id AND status = 'pending' AND attempts = :attempt
    """
)
_MARK_FAILED = text(
    """
    UPDATE outbox SET lease_expires_at = NULL, last_error = :error,
                      next_attempt_at = now() + make_interval(secs => :backoff)
    WHERE id = :id AND status = 'pending' AND attempts = :attempt
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
    attempt: int


def _backoff_seconds(attempts: int) -> int:
    return min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * 2 ** max(0, attempts - 1))


async def _deliver(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    claimed: _Claimed,
    publish_timeout: float = 10.0,
) -> bool:
    """Publish one claimed row, then mark it published or back off. True if this claim published.

    The publish is bounded by ``publish_timeout``; a timeout is an unconfirmed delivery, recorded
    as a failure so the row can be retried (a duplicate delivery is safe, ING-15). Both marks
    require the claim's attempt number, so a stale holder changes nothing.
    """
    request_context.set_correlation_id(claimed.correlation_id)
    try:
        await asyncio.wait_for(
            publisher.publish(claimed.job_id, claimed.correlation_id), publish_timeout
        )
    except TimeoutError:
        error = "publish timed out; delivery unconfirmed"
    except PublishError as exc:
        error = str(exc)[:300]
    except Exception as exc:
        error = f"unexpected {type(exc).__name__}"[:300]
    else:
        async with session_factory() as session, session.begin():
            marked = await session.execute(
                _MARK_PUBLISHED, {"id": claimed.id, "attempt": claimed.attempt}
            )
        if marked.rowcount == 1:  # type: ignore[attr-defined]
            logger.info("outbox row published", extra={"job_id": str(claimed.job_id)})
            return True
        logger.warning(
            "outbox claim was superseded; the row is left to its current owner",
            extra={"job_id": str(claimed.job_id)},
        )
        return False
    async with session_factory() as session, session.begin():
        marked = await session.execute(
            _MARK_FAILED,
            {
                "id": claimed.id,
                "attempt": claimed.attempt,
                "error": error,
                "backoff": _backoff_seconds(claimed.attempt),
            },
        )
    if marked.rowcount == 1:  # type: ignore[attr-defined]
        logger.warning(
            "outbox publish failed", extra={"job_id": str(claimed.job_id), "error": error}
        )
    return False


async def publish_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    job_id: uuid.UUID,
    lease_seconds: int = 60,
    publish_timeout: float = 10.0,
) -> bool:
    """Best-effort immediate publish for one job's outbox row, called after the caller commits.

    Await it inside the request: Cloud Run may throttle CPU once the response is sent, so never
    run it as unawaited background work. Never raises: failures are logged and the row stays
    ``pending`` for a manual retry. Returns True only if this call published the row.
    """
    try:
        async with session_factory() as session, session.begin():
            result = await session.execute(_CLAIM_ONE, {"job_id": job_id, "lease": lease_seconds})
            row = result.first()
        if row is None:
            return False
        return await _deliver(session_factory, publisher, _Claimed(*row), publish_timeout)
    except Exception as exc:
        logger.warning(
            "publish_after_commit failed; the row stays pending for a manual retry",
            extra={"job_id": str(job_id), "error_type": type(exc).__name__},
        )
        return False


async def republish_manual(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    job_id: uuid.UUID,
    *,
    grace_seconds: int,
    lease_seconds: int = 60,
    publish_timeout: float = 10.0,
) -> bool | None:
    """Manual publish-failure retry for one job. Same claim, lease and ``_deliver`` as every path.

    Returns None when the row is not eligible or another claim holds it (the caller reports 409),
    otherwise whether this call published it.
    """
    async with session_factory() as session, session.begin():
        result = await session.execute(
            _CLAIM_MANUAL, {"job_id": job_id, "lease": lease_seconds, "grace": grace_seconds}
        )
        row = result.first()
    if row is None:
        return None
    return await _deliver(session_factory, publisher, _Claimed(*row), publish_timeout)


async def dispatch_pending(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    batch_size: int = 20,
    lease_seconds: int = 60,
) -> DispatchResult:
    """Claim due ``pending`` rows (FOR UPDATE SKIP LOCKED + lease), publish, mark or back off.

    OPTIONAL scheduled-recovery path and the only multi-row claim. Not reachable in M0 unless
    ``KS_ENABLE_RECOVERY_DISPATCHER`` is true. KNOWN GAP when enabled: the whole batch shares one
    lease while rows are published one after another, so a long batch can outlive the lease and a
    later claim can publish a row twice (safe, but wasteful). Fix before enabling it.
    """
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
