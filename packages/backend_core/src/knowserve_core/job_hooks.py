"""Interfaces between the ingestion handler, the Worker and the retry path (M3-01).

M3-00a implements the Worker side; M3-02b writes the handler; M3-05a calls ``retry_job``. They all
code against these names, so none of them edits another's file. Nothing here has behavior.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .ingestion_contract import FailureCode


class NonRetryableJobError(Exception):
    """Raised by a handler when retrying cannot help (ING-23). The Worker marks the job ``failed``
    at once, without waiting for the attempt cap, and calls the terminal-failure hook."""

    def __init__(self, failure_code: FailureCode) -> None:
        super().__init__(failure_code.value)
        self.failure_code = failure_code


class RetryableJobError(Exception):
    """Raised by a handler for a failure that a later attempt may fix. Carries the code that is
    shown if this was the last attempt. Any other exception counts as ``INTERNAL_ERROR``."""

    def __init__(self, failure_code: FailureCode) -> None:
        super().__init__(failure_code.value)
        self.failure_code = failure_code


class TerminalFailureHook(Protocol):
    """Called by the Worker in the same transaction that marks a job ``failed`` (terminal error,
    attempt cap reached, or the crash guard at claim time). It sets the job's revision to
    ``failed`` with ``failure_reason``, so job and revision never disagree (M3-AC06). It must not
    touch a revision that is already ``ready`` (reindex mode, OPEN-31 D4)."""

    async def __call__(
        self, session: AsyncSession, job_id: uuid.UUID, failure_code: FailureCode
    ) -> None: ...


class RequeueHook(Protocol):
    """Called by ``retry_job`` in the same transaction that requeues a job. It sets the job's
    revision back to ``queued`` and clears ``phase`` and ``failure_reason`` (ADM-16)."""

    async def __call__(self, session: AsyncSession, job_id: uuid.UUID) -> None: ...
