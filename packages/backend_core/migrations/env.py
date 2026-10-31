"""Alembic environment: async engine, URL from KS_DATABASE_URL (ARCH-11, ARCH-12)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from knowserve_core.models import Base
from knowserve_core.settings import normalize_database_url

target_metadata = Base.metadata


def _database_url() -> str:
    url = context.config.get_main_option("sqlalchemy.url") or os.environ.get("KS_DATABASE_URL")
    if not url:
        raise RuntimeError("Set KS_DATABASE_URL to run migrations")
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
