"""M1-01 contract tests: schema 0002, seed departments, cascade rule, fixtures (M1-AC10 base)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core import audit
from knowserve_core.clock import FakeClock
from knowserve_core.models import User
from knowserve_core.security import hash_token, new_session_token

pytestmark = [pytest.mark.m1, pytest.mark.integration]


async def test_m1_schema_has_identity_tables_and_no_password_column(engine: AsyncEngine) -> None:
    """AUTH-01: no password or hash column exists anywhere in the schema."""
    async with engine.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        columns = (
            await conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        ).all()
    assert {
        "departments",
        "users",
        "sessions",
        "audit_events",
        "rate_limit_counters",
        "usage_counters",
        "ai_usage_daily",
    } <= tables
    forbidden = [
        (t, c)
        for t, c in columns
        if "password" in c.lower() or c.lower() in {"hashed_password", "pwd_hash"}
    ]
    assert forbidden == []


async def test_m1_departments_seeded_with_stable_ids(engine: AsyncEngine) -> None:
    """AUTH-20, D6: five fixed departments with stable ids and slugs."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id::text, slug, name FROM departments ORDER BY position")
            )
        ).all()
    assert [(r[1], r[2]) for r in rows] == [
        ("human-resources", "Human Resources"),
        ("finance", "Finance"),
        ("engineering", "Engineering"),
        ("legal", "Legal"),
        ("sales", "Sales"),
    ]
    assert rows[0][0] == "5bb20871-4372-57f0-9e45-9e20db142d70"


async def test_m1_users_unique_uid_and_email_demo_has_none(make_user) -> None:
    """AUTH-32: one user per uid and per email; Demo users carry no email."""
    await make_user("registered", uid="uid-a", email="a@example.test")
    with pytest.raises(IntegrityError):
        await make_user("registered", uid="uid-b", email="a@example.test")
    with pytest.raises(IntegrityError):
        await make_user("registered", uid="uid-a", email="other@example.test")
    await make_user("demo", uid="demo-1")
    await make_user("demo", uid="demo-2")  # many NULL emails are fine


async def test_m1_users_kind_is_constrained(make_user) -> None:
    with pytest.raises(IntegrityError):
        await make_user("superuser")


async def test_m1_session_fixture_stores_only_a_hash(
    make_user, make_session, engine: AsyncEngine
) -> None:
    """AUTH-06: the DB holds the hash, never the cookie value."""
    user = await make_user("registered")
    handle = await make_session(user)
    async with engine.connect() as conn:
        stored = await conn.scalar(text("SELECT token_hash FROM sessions"))
    assert stored == hash_token(handle.cookie)
    assert stored != handle.cookie


async def test_m1_session_expiry_is_absolute_in_the_fixture(
    make_user, make_session, engine: AsyncEngine, clock: FakeClock
) -> None:
    user = await make_user("registered")
    await make_session(user, ttl=timedelta(hours=24))
    async with engine.connect() as conn:
        delta = await conn.scalar(text("SELECT expires_at - created_at FROM sessions"))
    assert delta == timedelta(hours=24)


async def test_m1_dependents_cascade_with_the_user(
    make_user, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """ADR 0005: later tables reference users.id ON DELETE CASCADE; deleting a Demo user removes
    sessions and usage counters, the shape Demo cleanup (AUTH-35) relies on."""
    user = await make_user("demo", uid="demo-cascade")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO usage_counters (user_id, day, metric, count) "
                "VALUES (:u, CURRENT_DATE, 'ai_question', 3)"
            ),
            {"u": user.id},
        )
        await conn.execute(
            text(
                "INSERT INTO sessions (token_hash, user_id, sign_in_provider, csrf_secret, "
                "expires_at) VALUES (:h, :u, 'anonymous', 'c', now() + interval '1 day')"
            ),
            {"h": hash_token(new_session_token()), "u": user.id},
        )
    async with session_factory() as session:
        await session.delete(await session.get(User, user.id))
        await session.commit()
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM usage_counters")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM sessions")) == 0


async def test_m1_audit_record_redacts_secrets_in_details(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """MON-05, AUTH-21: tokens, cookies and CSRF values never reach audit_events."""
    jwt_like = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1In0.sig"
    async with session_factory() as session:
        await audit.record(
            session,
            "auth.session.denied",
            user_id=None,
            ip="203.0.113.9",
            provider="google.com",
            id_token=jwt_like,
            cookie="ks_session=abc",
            csrf_token="csrf-value",
            note=f"token was {jwt_like}",
        )
        await session.commit()
    async with engine.connect() as conn:
        details = await conn.scalar(text("SELECT details::text FROM audit_events"))
    assert details is not None
    for secret in (jwt_like, "ks_session=abc", "csrf-value"):
        assert secret not in details
    assert "google.com" in details
    uuid.UUID(str(await _one_id(engine)))


async def _one_id(engine: AsyncEngine) -> uuid.UUID:
    async with engine.connect() as conn:
        return await conn.scalar(text("SELECT id FROM audit_events"))
