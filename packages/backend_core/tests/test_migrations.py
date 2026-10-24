"""M0-AC03 / ARCH-11 / STACK-12: migration on PostgreSQL+pgvector, with a vector round trip."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_core.db import check_database

pytestmark = [pytest.mark.m0, pytest.mark.integration]


async def test_m0_ac03_migration_creates_extension_and_tables(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        ext = await conn.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
        tables = set(
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )
    assert ext == "vector"
    assert {"jobs", "outbox", "spike_vector_probe", "alembic_version"} <= tables


async def test_m0_ac03_pgvector_insert_and_distance_query(engine: AsyncEngine) -> None:
    near = "[1,0,0,0,0,0,0,0]"
    far = "[0,0,0,0,0,0,0,1]"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO spike_vector_probe (embedding) VALUES (:a), (:b)"),
            {"a": near, "b": far},
        )
        nearest = await conn.scalar(
            text(
                "SELECT embedding::text FROM spike_vector_probe "
                "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 1"
            ),
            {"q": "[0.9,0.1,0,0,0,0,0,0]"},
        )
    assert nearest == "[1,0,0,0,0,0,0,0]"


async def test_arch_13_check_database_true_when_reachable(engine: AsyncEngine) -> None:
    assert await check_database(engine) is True


async def test_arch_13_check_database_false_when_unreachable() -> None:
    from knowserve_core.db import create_engine

    dead = create_engine("postgresql+asyncpg://x:y@127.0.0.1:1/none", null_pool=True)
    assert await check_database(dead) is False
    await dead.dispose()
