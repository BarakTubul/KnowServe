"""M1-11 Demo cleanup tests: AUTH-35 (idempotent, bounded, race-safe, counts-only), SEC-14 base.

Dependents of a Demo user are modelled with a temporary table that references ``users(id)`` with
ON DELETE CASCADE, as the conversation tables of M2/M4 will (docs/adr/0005-m1-data-model.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core import demo_cleanup
from knowserve_core.clock import FakeClock
from knowserve_core.models import User
from knowserve_core.settings import Settings

pytestmark = [pytest.mark.m1, pytest.mark.integration]
Factory = async_sessionmaker[AsyncSession]


def make_settings(database_url: str, **overrides: Any) -> Settings:
    return Settings(_env_file=None, database_url=database_url, **overrides)  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def dependents(engine: AsyncEngine) -> AsyncIterator[None]:
    """A stand-in for conversation rows: cascades on user delete, like the real tables will."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS tmp_cleanup_dependents"))
        await conn.execute(
            text(
                "CREATE TABLE tmp_cleanup_dependents (id serial PRIMARY KEY, "
                "user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE)"
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS tmp_cleanup_dependents"))


async def scalar(factory: Factory, sql: str, **params: Any) -> Any:
    async with factory() as s:
        return (await s.execute(text(sql), params)).scalar_one()


async def user_ids(factory: Factory) -> set[uuid.UUID]:
    async with factory() as s:
        return set((await s.execute(text("SELECT id FROM users"))).scalars())


async def add_dependent(factory: Factory, user: User) -> None:
    async with factory() as s, s.begin():
        await s.execute(
            text("INSERT INTO tmp_cleanup_dependents (user_id) VALUES (:u)"), {"u": user.id}
        )


async def test_auth35_only_the_49h_demo_row_is_deleted_with_its_dependents(
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    make_user: Any,
    make_session: Any,
    dependents: None,
) -> None:
    now = clock.now()
    d47 = await make_user("demo", created_at=now - timedelta(hours=47))
    d49 = await make_user("demo", created_at=now - timedelta(hours=49))
    converted = await make_user("registered", created_at=now - timedelta(hours=100))
    admin = await make_user("admin", created_at=now - timedelta(hours=100))
    for u in (d47, d49, converted, admin):
        await add_dependent(session_factory, u)
        await make_session(u)
    async with session_factory() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO usage_counters (user_id, day, metric, count) VALUES (:u, :d, 'ai', 1)"
            ),
            {"u": d49.id, "d": now.date()},
        )

    result = await demo_cleanup.run(session_factory, make_settings(database_url), clock)

    assert result.deleted_users == 1 and result.failed_batches == 0 and not result.capped
    assert await user_ids(session_factory) == {d47.id, converted.id, admin.id}
    # Cascade removed the sessions, usage counters and the fixture dependent of the 49 h row only.
    assert await scalar(session_factory, "SELECT count(*) FROM sessions") == 3
    assert await scalar(session_factory, "SELECT count(*) FROM usage_counters") == 0
    assert await scalar(session_factory, "SELECT count(*) FROM tmp_cleanup_dependents") == 3
    assert (
        await scalar(
            session_factory,
            "SELECT count(*) FROM tmp_cleanup_dependents WHERE user_id = :u",
            u=d49.id,
        )
        == 0
    )


async def test_auth35_exact_boundary_keeps_row_at_48h_and_deletes_just_past_it(
    session_factory: Factory, database_url: str, clock: FakeClock, make_user: Any
) -> None:
    now = clock.now()
    at_limit = await make_user("demo", created_at=now - timedelta(hours=48))
    past = await make_user("demo", created_at=now - timedelta(hours=48, seconds=1))
    await demo_cleanup.run(session_factory, make_settings(database_url), clock)
    assert await user_ids(session_factory) == {at_limit.id}
    assert past.id not in await user_ids(session_factory)


async def test_auth35_converted_row_older_than_48h_is_kept(
    session_factory: Factory, database_url: str, clock: FakeClock, make_user: Any
) -> None:
    converted = await make_user("registered", created_at=clock.now() - timedelta(hours=500))
    result = await demo_cleanup.run(session_factory, make_settings(database_url), clock)
    assert result.deleted_users == 0
    assert await user_ids(session_factory) == {converted.id}


async def test_auth35_run_twice_second_run_deletes_nothing(
    session_factory: Factory, database_url: str, clock: FakeClock, make_user: Any
) -> None:
    for _ in range(3):
        await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    keep = await make_user("demo", created_at=clock.now() - timedelta(hours=1))
    settings = make_settings(database_url)
    first = await demo_cleanup.run(session_factory, settings, clock)
    second = await demo_cleanup.run(session_factory, settings, clock)
    assert (first.deleted_users, second.deleted_users, second.batches) == (3, 0, 0)
    assert await user_ids(session_factory) == {keep.id}


async def test_auth35_batches_are_bounded_by_batch_size_and_the_per_run_cap(
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    make_user: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for _ in range(5):
        await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    settings = make_settings(database_url, demo_cleanup_batch_size=2)
    result = await demo_cleanup.run(session_factory, settings, clock)
    assert (result.deleted_users, result.batches, result.capped) == (5, 3, False)

    for _ in range(5):
        await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    monkeypatch.setattr(demo_cleanup, "MAX_BATCHES_PER_RUN", 2)
    capped = await demo_cleanup.run(session_factory, settings, clock)
    assert (capped.deleted_users, capped.batches, capped.capped) == (4, 2, True)
    # The next run resumes where the capped one stopped.
    rest = await demo_cleanup.run(session_factory, settings, clock)
    assert (rest.deleted_users, rest.capped) == (1, False)
    assert await user_ids(session_factory) == set()


async def test_auth35_failing_batch_rolls_back_alone_and_the_next_run_resumes(
    session_factory: Factory,
    engine: AsyncEngine,
    database_url: str,
    clock: FakeClock,
    make_user: Any,
) -> None:
    # Oldest first: the first batch of 2 holds the poisoned user, the later batches are healthy.
    poisoned = await make_user("demo", created_at=clock.now() - timedelta(hours=90))
    buddy = await make_user("demo", created_at=clock.now() - timedelta(hours=89))
    healthy = [
        await make_user("demo", created_at=clock.now() - timedelta(hours=80 - i)) for i in range(3)
    ]
    async with engine.begin() as conn:
        # No ON DELETE rule: deleting the poisoned user fails with a foreign key violation.
        await conn.execute(text("DROP TABLE IF EXISTS tmp_cleanup_blocker"))
        await conn.execute(
            text(
                "CREATE TABLE tmp_cleanup_blocker "
                "(user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT)"
            )
        )
        await conn.execute(text("INSERT INTO tmp_cleanup_blocker VALUES (:u)"), {"u": poisoned.id})
    try:
        settings = make_settings(database_url, demo_cleanup_batch_size=2)
        first = await demo_cleanup.run(session_factory, settings, clock)
        # The poisoned batch (poisoned + buddy) rolled back as a whole; the healthy rows went.
        assert first.failed_batches == 1 and first.deleted_users == 3
        assert await user_ids(session_factory) == {poisoned.id, buddy.id}
        assert {u.id for u in healthy}.isdisjoint(await user_ids(session_factory))

        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tmp_cleanup_blocker"))
        second = await demo_cleanup.run(session_factory, settings, clock)
        assert second.failed_batches == 0 and second.deleted_users == 2
        assert await user_ids(session_factory) == set()
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS tmp_cleanup_blocker"))


async def test_auth35_run_gives_up_after_repeated_failing_batches(
    session_factory: Factory,
    engine: AsyncEngine,
    database_url: str,
    clock: FakeClock,
    make_user: Any,
) -> None:
    users = [
        await make_user("demo", created_at=clock.now() - timedelta(hours=60 + i)) for i in range(5)
    ]
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS tmp_cleanup_blocker"))
        await conn.execute(
            text(
                "CREATE TABLE tmp_cleanup_blocker "
                "(user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT)"
            )
        )
        for u in users:
            await conn.execute(text("INSERT INTO tmp_cleanup_blocker VALUES (:u)"), {"u": u.id})
    try:
        settings = make_settings(database_url, demo_cleanup_batch_size=1)
        result = await demo_cleanup.run(session_factory, settings, clock)
        assert result.failed_batches == demo_cleanup.MAX_FAILED_BATCHES_PER_RUN
        assert result.deleted_users == 0 and len(await user_ids(session_factory)) == 5
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS tmp_cleanup_blocker"))


async def _lock_and_convert(factory: Factory, user_id: uuid.UUID, hold: float = 0.0) -> bool:
    """What a conversion does: lock the row, flip kind, commit. False when the row is gone."""
    async with factory() as s, s.begin():
        row = (
            await s.execute(text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user_id})
        ).first()
        if row is None:
            return False
        if hold:
            await asyncio.sleep(hold)
        await s.execute(
            text("UPDATE users SET kind = 'registered', converted_at = now() WHERE id = :id"),
            {"id": user_id},
        )
        return True


async def test_auth35_conversion_holding_the_lock_wins_and_the_row_is_kept(
    session_factory: Factory, database_url: str, clock: FakeClock, make_user: Any
) -> None:
    user = await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    settings = make_settings(database_url)
    converting = asyncio.create_task(_lock_and_convert(session_factory, user.id, hold=0.6))
    await asyncio.sleep(0.2)  # the conversion now holds the row lock, kind still 'demo'
    during = await demo_cleanup.run(session_factory, settings, clock)  # SKIP LOCKED leaves it
    assert during.deleted_users == 0
    assert await converting is True
    after = await demo_cleanup.run(session_factory, settings, clock)  # now 'registered'
    assert after.deleted_users == 0
    assert await scalar(session_factory, "SELECT kind FROM users WHERE id = :i", i=user.id) == (
        "registered"
    )


async def test_auth35_cleanup_holding_the_lock_wins_and_conversion_sees_no_row(
    session_factory: Factory, database_url: str, clock: FakeClock, make_user: Any
) -> None:
    user = await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    cutoff = clock.now() - timedelta(hours=48)
    async with session_factory() as s, s.begin():
        ids = list(
            (
                await s.execute(
                    demo_cleanup._SELECT_BATCH, {"cutoff": cutoff, "skip": [], "batch": 10}
                )
            ).scalars()
        )
        assert ids == [user.id]
        converting = asyncio.create_task(_lock_and_convert(session_factory, user.id))
        await asyncio.sleep(0.3)
        assert not converting.done()  # blocked on the lock held by the cleanup transaction
        await s.execute(demo_cleanup._DELETE_BATCH, {"ids": ids})
    assert await converting is False
    assert await user_ids(session_factory) == set()


@pytest.mark.parametrize("round_", range(8))
async def test_auth35_conversion_racing_cleanup_has_exactly_one_outcome(
    session_factory: Factory, database_url: str, clock: FakeClock, make_user: Any, round_: int
) -> None:
    user = await make_user("demo", created_at=clock.now() - timedelta(hours=60))
    await make_user("demo", created_at=clock.now() - timedelta(hours=60))  # a second victim
    settings = make_settings(database_url, demo_cleanup_batch_size=1)
    jobs = [
        _lock_and_convert(session_factory, user.id),
        demo_cleanup.run(session_factory, settings, clock),
    ]
    if round_ % 2:
        jobs.reverse()
    results = await asyncio.gather(*jobs)
    converted = next(r for r in results if isinstance(r, bool))
    async with session_factory() as s:
        row = (
            await s.execute(text("SELECT kind FROM users WHERE id = :id"), {"id": user.id})
        ).first()
    if converted:
        # Conversion won: the row exists as 'registered' and was never deleted.
        assert row is not None and row.kind == "registered"
    else:
        # Cleanup won: the row is gone, and conversion saw that instead of resurrecting it.
        assert row is None
    # A later run never touches a converted row.
    await demo_cleanup.run(session_factory, settings, clock)
    async with session_factory() as s:
        later = (
            await s.execute(text("SELECT kind FROM users WHERE id = :id"), {"id": user.id})
        ).first()
    assert (later is not None) == converted


async def test_auth35_old_rate_limit_counters_are_purged_recent_ones_kept(
    session_factory: Factory, database_url: str, clock: FakeClock
) -> None:
    now = clock.now()
    async with session_factory() as s, s.begin():
        for key, age in (("old", timedelta(days=3)), ("recent", timedelta(hours=2))):
            await s.execute(
                text(
                    "INSERT INTO rate_limit_counters (key, window_start, count) VALUES (:k, :w, 1)"
                ),
                {"k": key, "w": now - age},
            )
    result = await demo_cleanup.run(session_factory, make_settings(database_url), clock)
    assert result.purged_rate_limit_counters == 1
    async with session_factory() as s:
        keys = set((await s.execute(text("SELECT key FROM rate_limit_counters"))).scalars())
    assert keys == {"recent"}


async def test_auth35_logs_and_audit_carry_counts_only(
    session_factory: Factory,
    database_url: str,
    clock: FakeClock,
    make_user: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    victim = await make_user(
        "demo", uid="uid-secret-victim", created_at=clock.now() - timedelta(hours=60)
    )
    other = await make_user(
        "registered",
        uid="uid-secret-other",
        email="someone@private.test",
        created_at=clock.now() - timedelta(hours=60),
    )
    await demo_cleanup.run(session_factory, make_settings(database_url), clock)

    async with session_factory() as s:
        events = (
            await s.execute(
                text("SELECT event, user_id, details FROM audit_events WHERE event = :e"),
                {"e": demo_cleanup.AUDIT_EVENT},
            )
        ).all()
    assert len(events) == 1 and events[0].user_id is None
    details = events[0].details
    assert set(details) == {
        "deleted_users",
        "batches",
        "failed_batches",
        "purged_rate_limit_counters",
        "capped",
    }
    assert all(isinstance(v, int | bool) for v in details.values())
    assert details["deleted_users"] == 1

    blob = json.dumps(details) + "\n".join(
        r.getMessage() + json.dumps(r.__dict__, default=str) for r in caplog.records
    )
    for secret in (
        "uid-secret-victim",
        "uid-secret-other",
        "someone@private.test",
        str(victim.id),
        str(other.id),
    ):
        assert secret not in blob
    cleanup_logs = [r for r in caplog.records if r.name == "knowserve.demo_cleanup"]
    assert len(cleanup_logs) == 1 and cleanup_logs[0].__dict__["deleted_users"] == 1
