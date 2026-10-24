"""Shared pytest fixtures (TEST-06): integration tests run on a real PostgreSQL + pgvector.

The test database comes from KS_TEST_DATABASE_URL (default: the compose `db` service, database
`knowserve_test`). If it is unreachable the integration tests FAIL; they are never silently skipped.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core.db import create_engine, create_session_factory
from knowserve_core.settings import normalize_database_url

DEFAULT_TEST_DB = (
    "postgresql+asyncpg://knowserve:knowserve_local_only@localhost:5433/knowserve_test"
)
ALEMBIC_INI = Path(__file__).parent / "packages" / "backend_core" / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
    return normalize_database_url(os.environ.get("KS_TEST_DATABASE_URL", DEFAULT_TEST_DB))


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
            await conn.execute(
                text("TRUNCATE outbox, jobs, spike_vector_probe RESTART IDENTITY CASCADE")
            )
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)
