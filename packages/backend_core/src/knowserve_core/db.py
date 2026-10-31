"""Async SQLAlchemy engine and session helpers (ARCH-02)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def _connect_args(database_url: str) -> dict[str, int]:
    # Neon's pooled endpoint is PgBouncer in transaction mode: no reusable prepared statements.
    host = urlsplit(database_url).hostname or ""
    return {"statement_cache_size": 0} if "-pooler" in host else {}


def create_engine(database_url: str, *, null_pool: bool = False) -> AsyncEngine:
    connect_args = _connect_args(database_url)
    if null_pool:
        return create_async_engine(database_url, poolclass=NullPool, connect_args=connect_args)
    return create_async_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One explicit transaction: commits on success, rolls back on error."""
    async with factory() as session, session.begin():
        yield session


async def check_database(engine: AsyncEngine) -> bool:
    """Readiness probe (ARCH-13). Returns False instead of raising."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
