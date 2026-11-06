"""PostgreSQL implementation of the daily AI quota and global AI guard (AUTH-36, COST-02/03).

One transaction on the session's engine (like ``ratelimit_pg``), so the decision never depends on
the caller's transaction and row locks stay short. Inside it:

1. ensure the global ``ai_usage_daily`` row and the user's ``usage_counters`` row exist;
2. ``UPDATE ... SET used = used + 1 WHERE used < limit`` on the global row (this takes its row
   lock, so concurrent callers queue and can never exceed the limit);
3. the same conditional update on the user's counter;
4. if either update matched nothing, roll the whole transaction back: a refusal consumes nothing.

The global row is always locked first, so there is no lock-order deadlock. If the session is not
bound to an engine (a test with a bare connection) the work joins the caller's transaction in a
savepoint.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from .clock import Clock, SystemClock
from .identity import IdentityKind
from .models import AiUsageDaily, UsageCounter
from .quotas import QuotaDecision
from .settings import Settings

AI_QUESTION_METRIC = "ai_question"


class _Refused(Exception):
    """Raised inside the transaction to roll it back; carries the decision."""

    def __init__(self, decision: QuotaDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


def seconds_until_next_utc_day(now: datetime) -> int:
    now = now.astimezone(UTC)
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return max(1, math.ceil((midnight - now).total_seconds()))


class PostgresQuotaService:
    def __init__(self, settings: Settings, clock: Clock | None = None) -> None:
        self._settings = settings
        self._clock: Clock = clock or SystemClock()

    def user_limit(self, kind: IdentityKind) -> int:
        if kind == "demo":
            return self._settings.quota_demo_daily
        if kind == "admin":
            return self._settings.quota_admin_daily
        return self._settings.quota_registered_daily

    async def consume_ai_question(
        self, session: AsyncSession, *, user_id: uuid.UUID, kind: IdentityKind
    ) -> QuotaDecision:
        now = self._clock.now()
        retry = seconds_until_next_utc_day(now)
        global_limit = self._settings.ai_global_daily_quota
        user_limit = self.user_limit(kind)
        if self._settings.ai_kill_switch:
            return QuotaDecision(False, "kill_switch", global_limit, 0, retry)
        day = now.astimezone(UTC).date()
        bind = session.bind
        try:
            if isinstance(bind, AsyncEngine):
                async with bind.begin() as conn:
                    return await self._consume(conn, user_id, day, global_limit, user_limit, retry)
            async with session.begin_nested():
                return await self._consume(session, user_id, day, global_limit, user_limit, retry)
        except _Refused as refused:
            return refused.decision

    async def _consume(
        self,
        conn: AsyncConnection | AsyncSession,
        user_id: uuid.UUID,
        day: date,
        global_limit: int,
        user_limit: int,
        retry: int,
    ) -> QuotaDecision:
        await conn.execute(pg_insert(AiUsageDaily).values(day=day, used=0).on_conflict_do_nothing())
        await conn.execute(
            pg_insert(UsageCounter)
            .values(user_id=user_id, day=day, metric=AI_QUESTION_METRIC, count=0)
            .on_conflict_do_nothing()
        )
        used_global = await _scalar(
            conn,
            update(AiUsageDaily)
            .where(AiUsageDaily.day == day, AiUsageDaily.used < global_limit)
            .values(used=AiUsageDaily.used + 1)
            .returning(AiUsageDaily.used),
        )
        if used_global is None:
            used = (
                await conn.execute(select(AiUsageDaily.used).where(AiUsageDaily.day == day))
            ).scalar_one()
            raise _Refused(QuotaDecision(False, "global_quota", global_limit, used, retry))
        used_user = await _scalar(
            conn,
            update(UsageCounter)
            .where(
                UsageCounter.user_id == user_id,
                UsageCounter.day == day,
                UsageCounter.metric == AI_QUESTION_METRIC,
                UsageCounter.count < user_limit,
            )
            .values(count=UsageCounter.count + 1)
            .returning(UsageCounter.count),
        )
        if used_user is None:
            used = (
                await conn.execute(
                    select(UsageCounter.count).where(
                        UsageCounter.user_id == user_id,
                        UsageCounter.day == day,
                        UsageCounter.metric == AI_QUESTION_METRIC,
                    )
                )
            ).scalar_one()
            raise _Refused(QuotaDecision(False, "user_quota", user_limit, used, retry))
        return QuotaDecision(True, "ok", user_limit, used_user, retry)


async def _scalar(conn: AsyncConnection | AsyncSession, stmt: Any) -> int | None:
    return (await conn.execute(stmt)).scalar_one_or_none()
