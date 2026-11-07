"""PostgreSQL fixed-window rate limiter (AUTH-15, ADR 0005). No Redis; safe on several instances.

One ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` per hit, so concurrent callers never lose an
update. Refused events are counted too.

The counter is written in its own short transaction on the session's engine, not in the caller's.
That matters for two reasons: a refused hit must survive when the route then fails with 429 and
rolls back, and the row lock must not be held until a long caller transaction ends. If the session
is not bound to an engine (a test with a bare connection), the hit joins the caller's transaction.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from .clock import Clock, SystemClock
from .models import RateLimitCounter
from .ratelimit import RateDecision


class PostgresRateLimiter:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or SystemClock()

    async def hit(
        self, session: AsyncSession, key: str, *, limit: int, window_seconds: int
    ) -> RateDecision:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        now = self._clock.now()
        epoch = int(now.timestamp())
        start_epoch = epoch - epoch % window_seconds
        window_start = datetime.fromtimestamp(start_epoch, UTC)
        stmt = (
            pg_insert(RateLimitCounter)
            .values(key=key, window_start=window_start, count=1)
            .on_conflict_do_update(
                index_elements=[RateLimitCounter.key, RateLimitCounter.window_start],
                set_={"count": RateLimitCounter.count + 1},
            )
            .returning(RateLimitCounter.count)
        )
        # Rows of this key from earlier windows are dead; drop them so a key never outlives its
        # window by more than the next hit (the Demo cleanup sweeps keys that never return).
        expire = delete(RateLimitCounter).where(
            RateLimitCounter.key == key, RateLimitCounter.window_start < window_start
        )
        bind = session.bind
        if isinstance(bind, AsyncEngine):
            async with bind.begin() as conn:
                count = (await conn.execute(stmt)).scalar_one()
                await conn.execute(expire)
        else:
            count = (await session.execute(stmt)).scalar_one()
            await session.execute(expire)
        allowed = count <= limit
        retry_after = (
            0 if allowed else max(1, math.ceil(start_epoch + window_seconds - now.timestamp()))
        )
        return RateDecision(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after_seconds=retry_after,
        )

    async def purge_older_than(self, session: AsyncSession, cutoff: datetime) -> int:
        """Delete windows that started before ``cutoff``; the caller commits. Returns the count."""
        result = await session.execute(
            delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
