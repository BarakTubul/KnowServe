"""Job enqueue (ING-12): the job row and its outbox row are written in the caller's transaction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from . import request_context
from .models import Job, OutboxEntry

# Prefix written to ``jobs.last_error`` when an operator manually requeues a job. It keeps the
# previous error visible and lets spike-only test handlers see that a manual retry happened.
MANUAL_RETRY_MARKER = "manual retry requested"


async def enqueue_job(
    session: AsyncSession, job_type: str, correlation_id: str | None = None
) -> Job:
    """Insert a queued ``jobs`` row and its pending ``outbox`` row. Never publishes.

    The caller owns the transaction: if it rolls back, neither row exists (ING-12). The
    correlation id defaults to the one in the current request context (MON-03).
    """
    cid = correlation_id or request_context.get_correlation_id() or request_context.new_request_id()
    job = Job(job_type=job_type, status="queued", attempts=0, correlation_id=cid)
    session.add(job)
    await session.flush()
    session.add(OutboxEntry(job_id=job.id, status="pending", attempts=0, correlation_id=cid))
    await session.flush()
    return job
