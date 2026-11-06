"""Shared pytest fixtures (TEST-06): integration tests run on a real PostgreSQL + pgvector.

The test database comes from KS_TEST_DATABASE_URL (default: the compose `db` service, database
`knowserve_test`). If it is unreachable the integration tests FAIL; they are never silently skipped.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core.clock import FakeClock
from knowserve_core.db import create_engine, create_session_factory
from knowserve_core.models import Session, User
from knowserve_core.security import hash_token, new_csrf_secret, new_session_token
from knowserve_core.settings import normalize_database_url
from knowserve_core.testing import mint_emulator_token

DEFAULT_TEST_DB = (
    "postgresql+asyncpg://knowserve:knowserve_local_only@localhost:5433/knowserve_test"
)
ALEMBIC_INI = Path(__file__).parent / "packages" / "backend_core" / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = normalize_database_url(os.environ.get("KS_TEST_DATABASE_URL", DEFAULT_TEST_DB))
    host = urlsplit(url).hostname
    if host not in ("localhost", "127.0.0.1", "::1", "db"):
        # The fixtures DROP SCHEMA public CASCADE; never point them at a remote database.
        raise RuntimeError("KS_TEST_DATABASE_URL must be a local database (it is wiped each run)")
    return url


async def _reset_schema(url: str) -> None:
    engine = create_engine(url, null_pool=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> Iterator[str]:
    """Drop and recreate the test schema, then run `alembic upgrade head` (M0-AC03)."""
    asyncio.run(_reset_schema(database_url))
    os.environ["KS_DATABASE_URL"] = database_url
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield database_url


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(migrated_database, null_pool=True)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            # `departments` is seed data from migration 0002 and is never truncated.
            await conn.execute(
                text(
                    "TRUNCATE outbox, jobs, spike_vector_probe, users, audit_events, "
                    "rate_limit_counters, ai_usage_daily RESTART IDENTITY CASCADE"
                )
            )
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


# --- M1 shared fixtures (Owner-written; slices import nothing from each other) ---


@pytest.fixture(autouse=True)
def _restore_firebase_emulator_env():
    """The verifier exports FIREBASE_AUTH_EMULATOR_HOST process-wide; never leak it across tests."""
    before = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    yield
    if before is None:
        os.environ.pop("FIREBASE_AUTH_EMULATOR_HOST", None)
    else:
        os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = before


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_token():
    """Factory for emulator-style (unsigned) Firebase ID tokens: ``make_token("uid", ...)``."""
    return mint_emulator_token


@dataclass
class SessionHandle:
    """A created session: the plaintext cookie value and CSRF token a client would hold."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    cookie: str
    csrf_token: str
    cookies: dict[str, str]
    headers: dict[str, str]


@pytest_asyncio.fixture
async def make_user(session_factory: async_sessionmaker[AsyncSession], clock: FakeClock):
    """Create a ``demo``/``registered``/``admin`` user row. Returns the ``User``."""

    async def _make(
        kind: str = "registered",
        *,
        uid: str | None = None,
        email: str | None = None,
        created_at=None,
        department_id: uuid.UUID | None = None,
    ) -> User:
        uid = uid or f"uid-{uuid.uuid4().hex[:12]}"
        if email is None and kind != "demo":
            email = f"{uid}@example.test"
        async with session_factory() as session:
            user = User(
                firebase_uid=uid,
                kind=kind,
                email=email,
                created_at=created_at or clock.now(),
                last_active_department_id=department_id,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _make


@pytest_asyncio.fixture
async def make_session(
    session_factory: async_sessionmaker[AsyncSession], clock: FakeClock, request
):
    """Create a session row for a user and return the cookie/CSRF a client would send."""

    async def _make(
        user: User,
        *,
        provider: str = "password",
        ttl: timedelta = timedelta(hours=24),
        department_id: uuid.UUID | None = None,
        origin: str = "http://localhost:5173",
    ) -> SessionHandle:
        token = new_session_token()
        csrf = new_csrf_secret()
        async with session_factory() as session:
            row = Session(
                token_hash=hash_token(token),
                user_id=user.id,
                sign_in_provider=provider,
                active_department_id=department_id,
                csrf_secret=csrf,
                created_at=clock.now(),
                expires_at=clock.now() + ttl,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        cookies = {"ks_session": token}
        headers = {"X-CSRF-Token": csrf, "Origin": origin}
        return SessionHandle(user.id, row.id, token, csrf, cookies, headers)

    return _make
