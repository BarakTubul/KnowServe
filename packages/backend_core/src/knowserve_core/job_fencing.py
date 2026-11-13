"""Fencing for pipeline writes (M3-00a, plan finding F7, OPEN-31 D9).

A Cloud Run timeout answers 504 while the container may keep running, and a worker whose lease
expired may still be alive. Any write such a worker makes after another worker reclaimed the job
could overwrite newer work. So every pipeline write runs in a transaction that first calls
``assert_claimed``: it locks the job row and checks that this worker still holds the claim. The
lock also stops a reclaim from slipping in between the check and the commit (the claim UPDATE
waits for the transaction), so the check and the writes behave as one step.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class LostClaimError(Exception):
    """This worker no longer holds the job (reclaimed after a lease expiry, requeued, or already
    finished). The caller must stop and write nothing more; the Worker answers 409 and leaves the
    job row to its current owner."""


_FENCE = text(
    """
    SELECT 1 FROM jobs
    WHERE id = :id AND claimed_by = :me AND status = 'processing'
    FOR UPDATE
    """
)


async def assert_claimed(session: AsyncSession, job_id: uuid.UUID, claimed_by: str) -> None:
    """Lock the job row and require that ``claimed_by`` still holds it, or raise.

    Call it as the first statement of every transaction that writes pipeline results (phase
    changes, chunks, publication). Roll the transaction back when it raises (leaving a
    ``session.begin()`` block does that).
    """
    held = (await session.execute(_FENCE, {"id": job_id, "me": claimed_by})).first()
    if held is None:
        raise LostClaimError(f"job {job_id} is no longer claimed by this worker")


@asynccontextmanager
async def fenced_session(
    factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID, claimed_by: str
) -> AsyncIterator[AsyncSession]:
    """A transaction whose first statement is the fence. Every write a handler makes for a job
    (phase changes, chunks, publication) goes through this, so a stale worker's write cannot
    happen by forgetting a call. It commits on a clean exit and rolls back on any exception,
    including ``LostClaimError`` from the fence itself."""
    async with factory() as session, session.begin():
        await assert_claimed(session, job_id, claimed_by)
        yield session
