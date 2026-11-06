"""Demo data cleanup (AUTH-35, ADR 0006): idempotent, bounded, safe against conversion races.

``run`` deletes ``demo`` users created more than ``KS_DEMO_RETENTION_SECONDS`` ago, in batches of
``KS_DEMO_CLEANUP_BATCH_SIZE``. Foreign keys with ON DELETE CASCADE remove their sessions, usage
counters and every other dependent row (conversations arrive in M2/M4 and must cascade too).

Race safety: conversion locks the user row (``SELECT ... FOR UPDATE``) and sets ``kind =
'registered'``. Each batch here picks its rows with ``FOR UPDATE SKIP LOCKED`` and deletes with
``kind = 'demo'`` re-checked in the same transaction, so exactly one of the two wins:

* conversion first: its commit makes the row ``registered``, the batch no longer selects it;
* cleanup first: conversion waits for the row lock, then finds the row gone (the converting caller
  must treat that as "no such Demo user", which Auth does by creating a fresh row);
* conversion holds the lock when the batch runs: ``SKIP LOCKED`` leaves the row alone.

Every batch is its own transaction, so a failing batch rolls back alone, earlier batches stay
deleted and the next run simply continues (resumable). A batch that fails is excluded for the rest
of the run so one poisoned row cannot block the others. Logs and the audit event carry counts only
(MON-04, MON-05): never an id, uid or email.

This module takes no caller input: every limit comes from ``Settings`` (SEC-14 exception).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import audit
from .clock import Clock
from .settings import Settings

logger = logging.getLogger("knowserve.demo_cleanup")

AUDIT_EVENT = "demo.cleanup.run"
# Per-run bounds, deliberately not configurable: with the default batch size of 500 a run removes
# at most 10 000 users; the next daily run continues where this one stopped.
MAX_BATCHES_PER_RUN = 20
# A run gives up after this many failing batches (a down database would fail every one of them).
MAX_FAILED_BATCHES_PER_RUN = 3
# Fixed-window counters are kept this long after their window started, plus the longest known
# window (the Demo-start window). A counter older than that can no longer affect any decision.
COUNTER_RETENTION = timedelta(days=1)

_SELECT_BATCH = text(
    """
    SELECT id FROM users
    WHERE kind = 'demo' AND created_at < :cutoff AND NOT (id = ANY(:skip))
    ORDER BY created_at, id
    LIMIT :batch
    FOR UPDATE SKIP LOCKED
    """
)
# kind is checked again at delete time even though the rows are locked: it is the guard that the
# security review reads, and it keeps the statement safe if the SELECT above is ever changed.
_DELETE_BATCH = text("DELETE FROM users WHERE id = ANY(:ids) AND kind = 'demo'")
_PURGE_COUNTERS = text("DELETE FROM rate_limit_counters WHERE window_start < :cutoff")


@dataclass(frozen=True)
class CleanupResult:
    """Counts only. Safe to log, audit and return from the Worker endpoint."""

    deleted_users: int = 0
    batches: int = 0
    failed_batches: int = 0
    purged_rate_limit_counters: int = 0
    # True when the per-run cap stopped the run while more expired rows may remain.
    capped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Batch:
    ids: list[uuid.UUID]
    deleted: int = 0
    failed: bool = False


async def _delete_one_batch(
    session_factory: async_sessionmaker[AsyncSession],
    cutoff: datetime,
    batch_size: int,
    skip: list[uuid.UUID],
) -> _Batch:
    """Lock, then delete one batch in one transaction. A failure rolls the batch back whole."""
    batch = _Batch(ids=[])
    try:
        async with session_factory() as session, session.begin():
            batch.ids = list(
                (
                    await session.execute(
                        _SELECT_BATCH, {"cutoff": cutoff, "skip": skip, "batch": batch_size}
                    )
                ).scalars()
            )
            if batch.ids:
                result = await session.execute(_DELETE_BATCH, {"ids": batch.ids})
                batch.deleted = result.rowcount  # type: ignore[attr-defined]
    except Exception:
        batch.failed = True
        batch.deleted = 0
        logger.error("demo cleanup batch failed", exc_info=True)
    return batch


async def run(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, clock: Clock
) -> CleanupResult:
    """Delete expired Demo users, purge old counters, audit the counts. Safe to repeat."""
    now = clock.now()
    cutoff = now - timedelta(seconds=settings.demo_retention_seconds)
    batch_size = settings.demo_cleanup_batch_size

    deleted_users = 0
    batches = 0
    failed = 0
    capped = False
    # Rows of a failed batch are skipped for the rest of this run so they cannot block the others;
    # they are tried again by the next run (nothing about them was changed).
    skip: list[uuid.UUID] = []
    while True:
        if batches + failed >= MAX_BATCHES_PER_RUN:
            capped = True
            break
        batch = await _delete_one_batch(session_factory, cutoff, batch_size, skip)
        if batch.failed:
            failed += 1
            skip = skip + batch.ids
            if failed >= MAX_FAILED_BATCHES_PER_RUN:
                break
            continue
        if not batch.ids:
            break
        deleted_users += batch.deleted
        batches += 1
        if len(batch.ids) < batch_size:
            break

    purged = await _purge_counters(session_factory, settings, now)
    result = CleanupResult(
        deleted_users=deleted_users,
        batches=batches,
        failed_batches=failed,
        purged_rate_limit_counters=purged,
        capped=capped,
    )
    async with session_factory() as session, session.begin():
        await audit.record(session, AUDIT_EVENT, **result.as_dict())
    logger.info("demo cleanup run", extra=result.as_dict())
    return result


async def _purge_counters(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> int:
    window = timedelta(seconds=settings.demo_start_window_seconds)
    try:
        async with session_factory() as session, session.begin():
            result = await session.execute(
                _PURGE_COUNTERS, {"cutoff": now - COUNTER_RETENTION - window}
            )
            return result.rowcount  # type: ignore[attr-defined]
    except Exception:
        logger.error("demo cleanup counter purge failed", exc_info=True)
        return 0
