"""Default hooks that keep a revision consistent with its job (M3-00a, plan finding F3, M3-AC06).

``mark_revision_failed`` implements ``TerminalFailureHook`` and ``requeue_revision`` implements
``RequeueHook`` (interfaces in ``job_hooks.py``). Both find the revision by
``document_revisions.job_id`` and run in the caller's transaction, so a job and its revision
change together or not at all. A job with no linked revision (the ``noop`` job, a seeded
revision before its reindex) matches no row and the hook does nothing. Neither hook touches a
``ready`` revision: that is reindex mode, where a failure must never fail a published
document (OPEN-31 D4).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .ingestion_contract import FailureCode

_FAIL = text(
    """
    UPDATE document_revisions
    SET status = 'failed', failure_reason = :code, phase = NULL
    WHERE job_id = :job_id AND status <> 'ready'
    """
)
_REQUEUE = text(
    """
    UPDATE document_revisions
    SET status = 'queued', phase = NULL, failure_reason = NULL
    WHERE job_id = :job_id AND status <> 'ready'
    """
)


async def mark_revision_failed(
    session: AsyncSession, job_id: uuid.UUID, failure_code: FailureCode
) -> None:
    """Set the job's revision to ``failed`` with the stable reason code (never a ``ready`` one)."""
    await session.execute(_FAIL, {"job_id": job_id, "code": failure_code.value})


async def requeue_revision(session: AsyncSession, job_id: uuid.UUID) -> None:
    """Set the job's revision back to ``queued`` and clear its phase and reason (ADM-16)."""
    await session.execute(_REQUEUE, {"job_id": job_id})
