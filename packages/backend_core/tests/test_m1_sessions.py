"""M1-02a: the session service (AUTH-06, AUTH-10, AUTH-14 token material, AUTH-33 revocation)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.clock import FakeClock
from knowserve_core.models import Session, User
from knowserve_core.security import hash_token
from knowserve_core.sessions import SessionService, UnknownDepartment

pytestmark = [pytest.mark.m1, pytest.mark.integration]

TTL = 24 * 3600


@pytest.fixture
def service(clock: FakeClock) -> SessionService:
    return SessionService(TTL, clock)


async def department_id(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with factory() as db:
        value = await db.scalar(text("SELECT id FROM departments ORDER BY position LIMIT 1"))
        assert value is not None
        return value


async def new_session(
    factory: async_sessionmaker[AsyncSession], service: SessionService, user: User, **kwargs
) -> tuple[str, Session]:
    async with factory() as db:
        token, row = await service.create_session(
            db, user, kwargs.pop("provider", "password"), **kwargs
        )
        await db.commit()
    return token, row


async def row_of(factory: async_sessionmaker[AsyncSession], session_id: uuid.UUID) -> Session:
    async with factory() as db:
        return (await db.execute(select(Session).where(Session.id == session_id))).scalar_one()


async def lookup(factory: async_sessionmaker[AsyncSession], service: SessionService, token: str):
    async with factory() as db:
        return await service.lookup_by_token(db, token)


async def test_auth_06_token_is_stored_only_as_a_hash_and_ids_are_never_reused(
    session_factory, service, make_user
) -> None:
    user = await make_user("registered")
    first_token, first = await new_session(session_factory, service, user)
    second_token, second = await new_session(session_factory, service, user)
    assert first_token != second_token
    assert first.id != second.id
    assert first.csrf_secret != second.csrf_secret
    assert len(first_token) >= 43  # 256 bits, URL-safe
    stored = await row_of(session_factory, first.id)
    assert stored.token_hash == hash_token(first_token)
    assert stored.token_hash != first_token
    assert first_token not in stored.csrf_secret
    async with session_factory() as db:
        dump = (await db.execute(text("SELECT sessions::text FROM sessions"))).scalars().all()
    assert not any(first_token in row or second_token in row for row in dump)


async def test_auth_10_session_is_accepted_until_24_hours_and_not_after(
    session_factory, service, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    token, row = await new_session(session_factory, service, user)
    assert row.expires_at == clock.now() + timedelta(seconds=TTL)

    clock.advance(seconds=TTL - 1)
    assert await lookup(session_factory, service, token) is not None
    clock.advance(seconds=1)  # exactly 24 h: expired
    assert await lookup(session_factory, service, token) is None
    clock.advance(seconds=1)
    assert await lookup(session_factory, service, token) is None


async def test_auth_10_use_never_extends_expiry_or_writes_anything(
    session_factory, service, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    token, row = await new_session(session_factory, service, user)
    before = await row_of(session_factory, row.id)
    for _ in range(5):
        clock.advance(hours=4)
        assert await lookup(session_factory, service, token) is not None
    after = await row_of(session_factory, row.id)
    assert after.expires_at == before.expires_at
    assert (after.created_at, after.revoked_at, after.csrf_secret, after.token_hash) == (
        before.created_at,
        before.revoked_at,
        before.csrf_secret,
        before.token_hash,
    )
    columns = {c.name for c in Session.__table__.columns}
    assert not {"last_seen_at", "last_used_at", "refreshed_at"} & columns


def test_auth_10_service_has_no_refresh_operation() -> None:
    assert not [name for name in dir(SessionService) if "refresh" in name or "extend" in name]


async def test_auth_10_ttl_comes_from_configuration(
    session_factory, clock: FakeClock, make_user
) -> None:
    short = SessionService(120, clock)
    user = await make_user("demo")
    token, row = await new_session(session_factory, short, user, provider="anonymous")
    assert row.expires_at - row.created_at == timedelta(seconds=120)
    clock.advance(seconds=121)
    assert await lookup(session_factory, short, token) is None


async def test_auth_10_tampered_or_unknown_tokens_are_rejected(
    session_factory, service, make_user
) -> None:
    user = await make_user("registered")
    token, _ = await new_session(session_factory, service, user)
    for bad in (
        "",
        "x",
        token[:-1] + ("A" if token[-1] != "A" else "B"),
        token + "x",
        token.upper(),
    ):
        assert await lookup(session_factory, service, bad) is None


async def test_auth_09_lookup_returns_the_identity(session_factory, service, make_user) -> None:
    dept = await department_id(session_factory)
    user = await make_user("admin", uid="uid-admin", email="a@example.test")
    token, row = await new_session(session_factory, service, user, department_id=dept)
    identity = await lookup(session_factory, service, token)
    assert identity is not None
    assert identity.kind == "admin" and identity.is_admin
    assert identity.user_id == user.id
    assert identity.firebase_uid == "uid-admin"
    assert identity.session_id == row.id
    assert identity.sign_in_provider == "password"
    assert identity.email == "a@example.test"
    assert identity.active_department_id == dept
    assert identity.expires_at == row.expires_at
    assert identity.csrf_token == row.csrf_secret


async def test_sec_03_kind_is_read_from_the_users_row_each_time(
    session_factory, service, make_user
) -> None:
    user = await make_user("registered")
    token, _ = await new_session(session_factory, service, user)
    assert (await lookup(session_factory, service, token)).kind == "registered"  # type: ignore[union-attr]
    async with session_factory() as db:
        await db.execute(text("UPDATE users SET kind = 'admin' WHERE id = :id"), {"id": user.id})
        await db.commit()
    assert (await lookup(session_factory, service, token)).kind == "admin"  # type: ignore[union-attr]


async def test_auth_33_revoked_session_is_rejected_and_revoke_all_counts_live_ones(
    session_factory, service, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    other = await make_user("registered")
    t1, s1 = await new_session(session_factory, service, user)
    t2, _ = await new_session(session_factory, service, user)
    t3, _ = await new_session(session_factory, service, user)
    t_other, _ = await new_session(session_factory, service, other)

    async with session_factory() as db:
        assert await service.revoke_session(db, s1.id) is True
        assert await service.revoke_session(db, s1.id) is False  # already revoked
        await db.commit()
    assert await lookup(session_factory, service, t1) is None

    async with session_factory() as db:
        assert await service.revoke_all_for_user(db, user.id) == 2
        await db.commit()
    assert await lookup(session_factory, service, t2) is None
    assert await lookup(session_factory, service, t3) is None
    assert await lookup(session_factory, service, t_other) is not None
    async with session_factory() as db:
        assert await service.revoke_all_for_user(db, user.id) == 0


async def test_auth_33_expired_sessions_are_not_counted_by_revoke_all(
    session_factory, service, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    await new_session(session_factory, service, user)
    clock.advance(seconds=TTL + 1)
    await new_session(session_factory, service, user)
    async with session_factory() as db:
        assert await service.revoke_all_for_user(db, user.id) == 1


async def test_auth_10_disabled_user_session_is_rejected(
    session_factory, service, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    token, _ = await new_session(session_factory, service, user)
    async with session_factory() as db:
        await db.execute(
            text("UPDATE users SET disabled_at = :now WHERE id = :id"),
            {"now": clock.now(), "id": user.id},
        )
        await db.commit()
    assert await lookup(session_factory, service, token) is None


async def test_auth_17_set_active_department_persists_on_session_and_user(
    session_factory, service, make_user
) -> None:
    dept = await department_id(session_factory)
    user = await make_user("registered")
    token, row = await new_session(session_factory, service, user)
    assert (await lookup(session_factory, service, token)).active_department_id is None  # type: ignore[union-attr]
    async with session_factory() as db:
        await service.set_active_department(
            db, session_id=row.id, user_id=user.id, department_id=dept
        )
        await db.commit()
    assert (await lookup(session_factory, service, token)).active_department_id == dept  # type: ignore[union-attr]
    async with session_factory() as db:
        remembered = await db.scalar(
            select(User.last_active_department_id).where(User.id == user.id)
        )
    assert remembered == dept


async def test_auth_17_unknown_department_is_refused_and_changes_nothing(
    session_factory, service, make_user
) -> None:
    user = await make_user("registered")
    token, row = await new_session(session_factory, service, user)
    async with session_factory() as db:
        with pytest.raises(UnknownDepartment):
            await service.set_active_department(
                db, session_id=row.id, user_id=user.id, department_id=uuid.uuid4()
            )
    assert (await lookup(session_factory, service, token)).active_department_id is None  # type: ignore[union-attr]
