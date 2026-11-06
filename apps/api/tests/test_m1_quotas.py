"""M1-10: daily AI quotas, the global AI guard and the kill switch (AUTH-36, COST-02/03, INFRA-10).

Service tests run against the real database. The HTTP tests use a throwaway router added to a
test-built app only (never ``create_app``, never the OpenAPI snapshot).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.app import create_app
from knowserve_api.auth.deps import get_identity
from knowserve_api.quota_deps import consume_ai_question
from knowserve_core.clock import FakeClock
from knowserve_core.firebase_verifier import EMULATOR_ENV_VAR
from knowserve_core.identity import Identity, IdentityKind
from knowserve_core.models import AiUsageDaily, UsageCounter, User
from knowserve_core.quotas import QuotaDecision, quota_error
from knowserve_core.quotas_pg import PostgresQuotaService, seconds_until_next_utc_day
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEFAULT_PROJECT_ID

pytestmark = [pytest.mark.m1, pytest.mark.api, pytest.mark.integration]

ORIGIN = "http://localhost:5173"
NOON = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_project_id": DEFAULT_PROJECT_ID,
        "firebase_auth_emulator_host": "localhost:9099",
        "api_allowed_origins": [ORIGIN],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def clock() -> FakeClock:
    """Override the shared fixture so sessions (make_session) and the app share one clock."""
    return FakeClock(NOON)


@pytest.fixture
def day_clock(clock: FakeClock) -> FakeClock:
    return clock


@pytest.fixture(autouse=True)
def _restore_emulator_env() -> Iterator[None]:
    """The real verifier exports the SDK's emulator variable (process-wide); never leak it."""
    saved = os.environ.get(EMULATOR_ENV_VAR)
    yield
    if saved is None:
        os.environ.pop(EMULATOR_ENV_VAR, None)
    else:
        os.environ[EMULATOR_ENV_VAR] = saved


async def consume(
    factory: async_sessionmaker[AsyncSession],
    service: PostgresQuotaService,
    user: User,
    kind: Any | None = None,
) -> QuotaDecision:
    async with factory() as session:
        return await service.consume_ai_question(
            session, user_id=user.id, kind=cast(IdentityKind, kind or user.kind)
        )


async def counts(factory: async_sessionmaker[AsyncSession], user: User) -> tuple[int, int]:
    """(global used, user count) summed over all days."""
    async with factory() as session:
        used = (await session.execute(select(AiUsageDaily.used))).scalars().all()
        mine = (
            (
                await session.execute(
                    select(UsageCounter.count).where(UsageCounter.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
    return sum(used), sum(mine)


# --- per-user limits (AUTH-36) -----------------------------------------------------------------


@pytest.mark.parametrize(("kind", "limit"), [("demo", 20), ("registered", 100), ("admin", 100)])
async def test_auth_36_user_limit_allows_n_and_refuses_next(
    kind: str,
    limit: int,
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(make_settings(ai_global_daily_quota=1000), day_clock)
    user = await make_user(kind)
    for i in range(limit):
        decision = await consume(session_factory, service, user)
        assert decision.allowed and decision.reason == "ok"
        assert decision.used == i + 1 and decision.limit == limit
    refused = await consume(session_factory, service, user)
    assert not refused.allowed and refused.reason == "user_quota"
    assert refused.used == limit and refused.limit == limit
    assert await counts(session_factory, user) == (limit, limit)


async def test_auth_36_limits_are_configurable(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(
        make_settings(
            quota_demo_daily=2,
            quota_registered_daily=3,
            quota_admin_daily=4,
            ai_global_daily_quota=1000,
        ),
        day_clock,
    )
    for kind, limit in (("demo", 2), ("registered", 3), ("admin", 4)):
        user = await make_user(kind)
        results = [
            (await consume(session_factory, service, user)).allowed for _ in range(limit + 1)
        ]
        assert results == [True] * limit + [False]


async def test_auth_36_utc_day_rollover(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(
        make_settings(quota_demo_daily=2, ai_global_daily_quota=1000), day_clock
    )
    user = await make_user("demo")
    assert (await consume(session_factory, service, user)).allowed
    assert (await consume(session_factory, service, user)).allowed
    assert not (await consume(session_factory, service, user)).allowed
    day_clock.set(datetime(2026, 3, 10, 23, 59, 59, tzinfo=UTC))
    assert not (await consume(session_factory, service, user)).allowed
    day_clock.set(datetime(2026, 3, 11, 0, 0, 0, tzinfo=UTC))
    again = await consume(session_factory, service, user)
    assert again.allowed and again.used == 1


async def test_auth_36_retry_after_is_seconds_to_next_utc_midnight(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(
        make_settings(quota_demo_daily=1, ai_global_daily_quota=1000), day_clock
    )
    user = await make_user("demo")
    await consume(session_factory, service, user)
    refused = await consume(session_factory, service, user)
    assert refused.retry_after_seconds == 12 * 3600
    day_clock.set(datetime(2026, 3, 10, 23, 59, 30, tzinfo=UTC))
    assert (await consume(session_factory, service, user)).retry_after_seconds == 30
    assert seconds_until_next_utc_day(datetime(2026, 3, 10, 0, 0, 0, tzinfo=UTC)) == 86400
    assert seconds_until_next_utc_day(datetime(2026, 3, 10, 23, 59, 59, 500000, tzinfo=UTC)) == 1


async def test_auth_36_converted_demo_user_keeps_one_counter_and_registered_limit(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(make_settings(ai_global_daily_quota=1000), day_clock)
    user = await make_user("demo")
    for _ in range(20):
        assert (await consume(session_factory, service, user, "demo")).allowed
    assert not (await consume(session_factory, service, user, "demo")).allowed
    # Conversion keeps the same user id; only the kind (and so the limit) changes.
    after = await consume(session_factory, service, user, "registered")
    assert after.allowed and after.used == 21 and after.limit == 100
    async with session_factory() as session:
        rows = (
            (await session.execute(select(UsageCounter).where(UsageCounter.user_id == user.id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].count == 21 and rows[0].metric == "ai_question"


# --- global guard and kill switch (COST-02, COST-03, INFRA-10) ---------------------------------


async def test_cost_03_global_quota_refuses_everyone_and_consumes_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(make_settings(ai_global_daily_quota=100), day_clock)
    users = [await make_user("registered") for _ in range(5)]
    for i in range(100):
        assert (await consume(session_factory, service, users[i % 5])).allowed
    fresh = await make_user("admin")
    before = await counts(session_factory, users[0])
    for user in (*users, fresh):
        refused = await consume(session_factory, service, user)
        assert not refused.allowed and refused.reason == "global_quota"
        assert refused.used == 100 and refused.limit == 100
    assert await counts(session_factory, users[0]) == before
    assert await counts(session_factory, fresh) == (100, 0)
    # The next UTC day starts a new global total.
    day_clock.advance(days=1)
    assert (await consume(session_factory, service, fresh)).allowed


async def test_cost_03_refused_user_quota_does_not_consume_global(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(
        make_settings(quota_demo_daily=1, ai_global_daily_quota=10), day_clock
    )
    user = await make_user("demo")
    await consume(session_factory, service, user)
    for _ in range(3):
        assert (await consume(session_factory, service, user)).reason == "user_quota"
    assert await counts(session_factory, user) == (1, 1)


async def test_cost_03_precedence_kill_switch_then_global_then_user(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    user = await make_user("demo")
    # User quota and global quota both exhausted: global wins.
    service = PostgresQuotaService(
        make_settings(quota_demo_daily=1, ai_global_daily_quota=1), day_clock
    )
    assert (await consume(session_factory, service, user)).allowed
    assert (await consume(session_factory, service, user)).reason == "global_quota"
    # Kill switch on top of both: kill switch wins, and touches nothing.
    killed = PostgresQuotaService(
        make_settings(quota_demo_daily=1, ai_global_daily_quota=1, ai_kill_switch=True), day_clock
    )
    other = await make_user("registered")
    decision = await consume(session_factory, killed, other)
    assert decision.reason == "kill_switch" and not decision.allowed
    assert await counts(session_factory, other) == (1, 0)
    # User quota only (global has room): user wins.
    roomy = PostgresQuotaService(
        make_settings(quota_demo_daily=1, ai_global_daily_quota=10), day_clock
    )
    assert (await consume(session_factory, roomy, user)).reason == "user_quota"


def test_cost_02_error_mapping_codes() -> None:
    def decision(reason: Any, allowed: bool = False) -> QuotaDecision:
        return QuotaDecision(allowed, reason, 1, 1, 42)

    assert quota_error(decision("ok", True)) is None
    user_err = quota_error(decision("user_quota"))
    assert user_err is not None
    assert (user_err.status_code, user_err.code) == (429, "QUOTA_EXCEEDED")
    assert "42" in user_err.message
    for reason in ("global_quota", "kill_switch"):
        err = quota_error(decision(reason))
        assert err is not None
        assert (err.status_code, err.code) == (503, "AI_UNAVAILABLE")


# --- concurrency (COST-02) ---------------------------------------------------------------------


async def test_cost_02_concurrent_consumes_never_exceed_user_limit(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(
        make_settings(quota_demo_daily=20, ai_global_daily_quota=1000), day_clock
    )
    user = await make_user("demo")
    for _ in range(15):
        await consume(session_factory, service, user)
    results = await asyncio.gather(*(consume(session_factory, service, user) for _ in range(60)))
    assert sum(r.allowed for r in results) == 5
    assert await counts(session_factory, user) == (20, 20)


async def test_cost_02_concurrent_consumes_never_exceed_global_limit(
    session_factory: async_sessionmaker[AsyncSession],
    make_user: Callable[..., Any],
    day_clock: FakeClock,
) -> None:
    service = PostgresQuotaService(
        make_settings(quota_registered_daily=100, ai_global_daily_quota=30), day_clock
    )
    users = [await make_user("registered") for _ in range(6)]
    results = await asyncio.gather(
        *(consume(session_factory, service, users[i % 6]) for i in range(60))
    )
    assert sum(r.allowed for r in results) == 30
    assert {r.reason for r in results if not r.allowed} == {"global_quota"}
    async with session_factory() as session:
        used = (await session.execute(select(AiUsageDaily.used))).scalar_one()
        total = sum((await session.execute(select(UsageCounter.count))).scalars().all())
    assert used == 30 and total == 30


# --- HTTP: dependency and graceful degradation (INFRA-10) --------------------------------------


router = APIRouter(prefix="/_q")


@router.post("/ask")
async def t_ask(_: Annotated[QuotaDecision, Depends(consume_ai_question)]) -> dict:
    return {"ok": True}


@router.get("/library")
async def t_library(identity: Annotated[Identity, Depends(get_identity)]) -> dict:
    return {"kind": identity.kind}


def build_app(engine: AsyncEngine, clock: FakeClock, **settings: Any) -> FastAPI:
    app = create_app(
        make_settings(**settings),
        engine=engine,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
    )
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def make_client(
    engine: AsyncEngine, day_clock: FakeClock
) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def _make(**settings: Any) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=build_app(engine, day_clock, **settings))
        client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


async def test_auth_36_http_quota_exceeded_is_429(
    make_client: Callable[..., httpx.AsyncClient],
    make_user: Callable[..., Any],
    make_session: Callable[..., Any],
) -> None:
    client = make_client(quota_demo_daily=2, ai_global_daily_quota=100)
    handle = await make_session(await make_user("demo"), ttl=timedelta(days=3))
    for _ in range(2):
        assert (await client.post("/_q/ask", headers=ck(handle))).status_code == 200
    refused = await client.post("/_q/ask", headers=ck(handle))
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert (await client.post("/_q/ask")).status_code == 401


async def test_infra_10_kill_switch_refuses_ai_but_not_other_routes(
    make_client: Callable[..., httpx.AsyncClient],
    make_user: Callable[..., Any],
    make_session: Callable[..., Any],
) -> None:
    client = make_client(ai_kill_switch=True, quota_demo_daily=0)
    user = await make_user("demo")
    handle = await make_session(user)
    refused = await client.post("/_q/ask", headers=ck(handle))
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "AI_UNAVAILABLE"
    assert (await client.get("/_q/library", headers=ck(handle))).status_code == 200
    assert (await client.get("/health/live")).status_code == 200


async def test_cost_03_http_global_quota_is_503_for_everyone(
    make_client: Callable[..., httpx.AsyncClient],
    make_user: Callable[..., Any],
    make_session: Callable[..., Any],
) -> None:
    client = make_client(ai_global_daily_quota=3)
    handles = [await make_session(await make_user(k)) for k in ("demo", "registered", "admin")]
    for handle in handles:
        assert (await client.post("/_q/ask", headers=ck(handle))).status_code == 200
    for handle in handles:
        refused = await client.post("/_q/ask", headers=ck(handle))
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "AI_UNAVAILABLE"
        assert (await client.get("/_q/library", headers=ck(handle))).status_code == 200


async def test_cost_02_dependency_uses_injected_quota_service(
    engine: AsyncEngine,
    day_clock: FakeClock,
    make_user: Callable[..., Any],
    make_session: Callable[..., Any],
) -> None:
    class Denying:
        async def consume_ai_question(
            self, session: AsyncSession, *, user_id: uuid.UUID, kind: Any
        ) -> QuotaDecision:
            return QuotaDecision(False, "global_quota", 0, 0, 5)

    app = build_app(engine, day_clock)
    app.state.quota_service = Denying()
    handle = await make_session(await make_user("registered"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        refused = await client.post("/_q/ask", headers=ck(handle))
    assert refused.status_code == 503


def ck(handle: Any) -> dict[str, str]:
    return {"Cookie": f"ks_session={handle.cookie}"}
