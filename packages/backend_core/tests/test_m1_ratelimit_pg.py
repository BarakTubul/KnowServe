"""M1-02a: PostgreSQL fixed-window limiter (AUTH-15, ADR 0005)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.clock import FakeClock
from knowserve_core.models import RateLimitCounter
from knowserve_core.ratelimit_pg import PostgresRateLimiter

pytestmark = [pytest.mark.m1, pytest.mark.integration]


@pytest.fixture
def start_of_hour() -> datetime:
    return datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)


async def test_auth_15_sixth_hit_in_the_window_is_refused(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    clock = FakeClock(start_of_hour + timedelta(minutes=10))
    limiter = PostgresRateLimiter(clock)
    async with session_factory() as db:
        decisions = [
            await limiter.hit(db, "demo:ip:1.2.3.4", limit=5, window_seconds=3600) for _ in range(6)
        ]
    assert [d.allowed for d in decisions] == [True] * 5 + [False]
    assert [d.remaining for d in decisions] == [4, 3, 2, 1, 0, 0]
    assert decisions[0].retry_after_seconds == 0
    assert decisions[5].retry_after_seconds == 50 * 60  # to the end of the window
    assert all(d.limit == 5 for d in decisions)


async def test_auth_15_other_keys_are_independent(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    limiter = PostgresRateLimiter(FakeClock(start_of_hour))
    async with session_factory() as db:
        for _ in range(6):
            await limiter.hit(db, "demo:ip:1.1.1.1", limit=5, window_seconds=3600)
        other = await limiter.hit(db, "demo:ip:2.2.2.2", limit=5, window_seconds=3600)
    assert other.allowed and other.remaining == 4


async def test_auth_15_window_rolls_over(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    clock = FakeClock(start_of_hour + timedelta(minutes=59, seconds=59))
    limiter = PostgresRateLimiter(clock)
    async with session_factory() as db:
        for _ in range(5):
            assert (await limiter.hit(db, "k", limit=5, window_seconds=3600)).allowed
        refused = await limiter.hit(db, "k", limit=5, window_seconds=3600)
        assert not refused.allowed
        assert refused.retry_after_seconds == 1
        clock.advance(seconds=1)  # exactly the next window
        again = await limiter.hit(db, "k", limit=5, window_seconds=3600)
    assert again.allowed and again.remaining == 4


async def test_auth_15_refused_events_are_counted(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    limiter = PostgresRateLimiter(FakeClock(start_of_hour))
    async with session_factory() as db:
        for _ in range(8):
            await limiter.hit(db, "k", limit=5, window_seconds=3600)
        count = await db.scalar(select(RateLimitCounter.count).where(RateLimitCounter.key == "k"))
    assert count == 8


async def test_auth_15_a_refused_hit_survives_the_callers_rollback(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    """A route that raises 429 rolls its own transaction back; the counter must stay."""
    limiter = PostgresRateLimiter(FakeClock(start_of_hour))
    async with session_factory() as db:
        for _ in range(6):
            await limiter.hit(db, "k", limit=5, window_seconds=3600)
        await db.rollback()
    async with session_factory() as db:
        count = await db.scalar(select(RateLimitCounter.count).where(RateLimitCounter.key == "k"))
    assert count == 6


async def test_auth_15_concurrent_hits_are_atomic(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    limiter = PostgresRateLimiter(FakeClock(start_of_hour))

    async def one() -> bool:
        async with session_factory() as db:
            return (await limiter.hit(db, "burst", limit=10, window_seconds=3600)).allowed

    results = await asyncio.gather(*(one() for _ in range(40)))
    assert sum(results) == 10
    async with session_factory() as db:
        count = await db.scalar(
            select(RateLimitCounter.count).where(RateLimitCounter.key == "burst")
        )
    assert count == 40


async def test_auth_15_invalid_arguments_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    limiter = PostgresRateLimiter()
    async with session_factory() as db:
        with pytest.raises(ValueError):
            await limiter.hit(db, "k", limit=0, window_seconds=60)
        with pytest.raises(ValueError):
            await limiter.hit(db, "k", limit=1, window_seconds=0)


async def test_auth_15_old_windows_can_be_purged(
    session_factory: async_sessionmaker[AsyncSession], start_of_hour: datetime
) -> None:
    clock = FakeClock(start_of_hour)
    limiter = PostgresRateLimiter(clock)
    async with session_factory() as db:
        await limiter.hit(db, "old", limit=5, window_seconds=3600)
        clock.advance(hours=30)
        await limiter.hit(db, "new", limit=5, window_seconds=3600)
        deleted = await limiter.purge_older_than(db, clock.now() - timedelta(hours=24))
        await db.commit()
        remaining = await db.scalar(select(func.count()).select_from(RateLimitCounter))
    assert deleted == 1
    assert remaining == 1
