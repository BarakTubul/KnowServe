"""Job claim, lease renewal and fenced finish for the Worker (M3-00a; ING-10, 15, 16, 19).

Two counters stay apart (docs/contracts/jobs-outbox.md): a *delivery* is one HTTP call from QStash,
an *attempt* is one successful claim and is the only thing that increments ``jobs.attempts``. A
delivery that finds the job claimed, done, failed or unknown uses no attempt.

Rules enforced here:

* The claim checks ``attempts < max_attempts`` (finding F5). A job that is past the cap and not
  currently leased is marked ``failed`` with ``PROCESSING_CRASHED`` instead of running again, so a
  handler that dies before any ``except`` block (out of memory, native crash) cannot loop forever.
* Every state change after the claim is conditional on ``claimed_by = me AND status = 'processing'``
  and reports whether it matched, so a stale worker never overwrites a newer claim (F7).
* ``fail_job`` marks the job ``failed`` and calls the terminal-failure hook in the same
  transaction, so the revision and the job never disagree (F3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .ingestion_contract import FailureCode
from .job_hooks import TerminalFailureHook

Factory = async_sessionmaker[AsyncSession]

_RECLAIMABLE = (
    "(status = 'queued' OR (status = 'processing' "
    "AND (lease_expires_at IS NULL OR lease_expires_at < now())))"
)
_CLAIM = text(
    f"""
    UPDATE jobs SET status = 'processing', attempts = attempts + 1, claimed_by = :me,
                    lease_expires_at = now() + make_interval(secs => :lease), updated_at = now()
    WHERE id = :id AND attempts < :max_attempts AND {_RECLAIMABLE}
    RETURNING job_type, correlation_id, attempts, last_error
    """
)
_CRASH_GUARD = text(
    f"""
    UPDATE jobs SET status = 'failed', last_error = :error, lease_expires_at = NULL,
                    claimed_by = NULL, updated_at = now()
    WHERE id = :id AND attempts >= :max_attempts AND {_RECLAIMABLE}
    RETURNING id
    """
)
_STATUS = text("SELECT status FROM jobs WHERE id = :id")
_RENEW = text(
    """
    UPDATE jobs SET lease_expires_at = now() + make_interval(secs => :lease), updated_at = now()
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    RETURNING id
    """
)
_COMPLETE = text(
    """
    UPDATE jobs SET status = 'done', completed_at = now(), updated_at = now(),
                    lease_expires_at = NULL, last_error = NULL
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    RETURNING id
    """
)
_RELEASE = text(
    """
    UPDATE jobs SET status = 'queued', last_error = :error, lease_expires_at = NULL,
                    claimed_by = NULL, updated_at = now()
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    RETURNING id
    """
)
_FAIL = text(
    """
    UPDATE jobs SET status = 'failed', last_error = :error, lease_expires_at = NULL,
                    claimed_by = NULL, updated_at = now()
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    RETURNING id
    """
)

CRASH_ERROR = f"{FailureCode.PROCESSING_CRASHED.value}: attempt cap reached without a result"


@dataclass(frozen=True)
class ClaimedJob:
    job_type: str
    correlation_id: str
    attempts: int
    last_error: str | None


@dataclass(frozen=True)
class ClaimResult:
    """``claimed``: this worker holds the job. ``done`` and ``failed``: nothing to do (200).
    ``busy``: someone else holds a live lease (409). ``crash_failed``: the claim found the job past
    its attempt cap and ended it ``failed`` (the Worker answers like any permanent failure).
    ``unknown``: no such job (200)."""

    kind: Literal["claimed", "done", "failed", "busy", "crash_failed", "unknown"]
    job: ClaimedJob | None = None


async def claim_job(
    factory: Factory,
    job_id: uuid.UUID,
    me: str,
    *,
    lease_seconds: float,
    max_attempts: int,
    terminal_hook: TerminalFailureHook,
) -> ClaimResult:
    async with factory() as session, session.begin():
        row = (
            await session.execute(
                _CLAIM,
                {"id": job_id, "me": me, "lease": lease_seconds, "max_attempts": max_attempts},
            )
        ).first()
        if row is not None:
            return ClaimResult(
                "claimed",
                ClaimedJob(row.job_type, row.correlation_id, row.attempts, row.last_error),
            )
        crashed = (
            await session.execute(
                _CRASH_GUARD, {"id": job_id, "max_attempts": max_attempts, "error": CRASH_ERROR}
            )
        ).first()
        if crashed is not None:
            await terminal_hook(session, job_id, FailureCode.PROCESSING_CRASHED)
            return ClaimResult("crash_failed")
        status = (await session.execute(_STATUS, {"id": job_id})).scalar_one_or_none()
    if status is None:
        return ClaimResult("unknown")
    if status == "done":
        return ClaimResult("done")
    if status == "failed":
        return ClaimResult("failed")
    return ClaimResult("busy")


async def renew_lease(factory: Factory, job_id: uuid.UUID, me: str, lease_seconds: float) -> bool:
    """Extend the lease while the handler runs. False means the claim is gone."""
    async with factory() as session, session.begin():
        result = await session.execute(_RENEW, {"id": job_id, "me": me, "lease": lease_seconds})
        return result.first() is not None


async def complete_job(factory: Factory, job_id: uuid.UUID, me: str) -> bool:
    """Mark ``done``. False means this worker no longer held the job (nothing changed)."""
    async with factory() as session, session.begin():
        return (await session.execute(_COMPLETE, {"id": job_id, "me": me})).first() is not None


async def release_job(factory: Factory, job_id: uuid.UUID, me: str, error: str) -> bool:
    """Back to ``queued`` for the next delivery. False means the claim was gone."""
    async with factory() as session, session.begin():
        released = await session.execute(_RELEASE, {"id": job_id, "me": me, "error": error})
        return released.first() is not None


async def fail_job(
    factory: Factory,
    job_id: uuid.UUID,
    me: str,
    code: FailureCode,
    error: str,
    terminal_hook: TerminalFailureHook,
) -> bool:
    """Mark ``failed`` and run the terminal-failure hook in the same transaction.

    False means this worker no longer held the job: nothing changed and the hook did not run.
    """
    async with factory() as session, session.begin():
        failed = await session.execute(_FAIL, {"id": job_id, "me": me, "error": error})
        if failed.first() is None:
            return False
        await terminal_hook(session, job_id, code)
        return True
