"""M2-01 tests: schema 0003, visibility predicate (SEC-07), uniform 404 (SEC-02, DOC-05, Q7)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core.documents_access import (
    document_not_found,
    parse_document_id,
    visible_documents,
)
from knowserve_core.models import DocumentRevision
from knowserve_core.testing import DEPARTMENT_IDS, make_document
from knowserve_core.web import AppError

pytestmark = [pytest.mark.m2, pytest.mark.documents, pytest.mark.integration]

FIN = uuid.UUID(DEPARTMENT_IDS["finance"])
ENG = uuid.UUID(DEPARTMENT_IDS["engineering"])


async def _visible_ids(session: AsyncSession, dept: uuid.UUID) -> set[uuid.UUID]:
    rows = (await session.execute(visible_documents(dept))).all()
    return {row[0].id for row in rows}


async def test_m2_ac14_schema_has_document_tables(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert {"documents", "document_revisions", "document_department_access"} <= tables
    assert version is not None and version >= "0003"


async def test_sec07_states_matrix(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as s:
        ok = await make_document(s, status="ready")
        await make_document(s, status="queued")
        await make_document(s, status="processing")
        await make_document(s, status="failed")
        await make_document(s, status="ready", deleted=True)
        await make_document(s, status=None)
        await s.commit()
        assert await _visible_ids(s, FIN) == {ok.id}


async def test_sec04_owner_label_grants_nothing_and_access_rows_do(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        doc = await make_document(s, owner="finance", allowed=("engineering",))
        await s.commit()
        assert await _visible_ids(s, FIN) == set()
        assert await _visible_ids(s, ENG) == {doc.id}


async def test_sec05_org_wide_minus_one_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        doc = await make_document(s, allowed=tuple(DEPARTMENT_IDS))
        await s.commit()
        for dept_id in DEPARTMENT_IDS.values():
            assert doc.id in await _visible_ids(s, uuid.UUID(dept_id))
        await s.execute(
            text(
                "DELETE FROM document_department_access WHERE document_id=:d AND department_id=:p"
            ),
            {"d": doc.id, "p": ENG},
        )
        await s.commit()
        assert doc.id not in await _visible_ids(s, ENG)
        assert doc.id in await _visible_ids(s, FIN)


async def test_doc10_soft_delete_applies_on_next_query(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        doc = await make_document(s, allowed=("finance",))
        await s.commit()
        assert doc.id in await _visible_ids(s, FIN)
        await s.execute(text("UPDATE documents SET deleted_at = now() WHERE id=:d"), {"d": doc.id})
        await s.commit()
        assert await _visible_ids(s, FIN) == set()


async def test_current_revision_must_belong_to_same_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        a = await make_document(s)
        b = await make_document(s)
        await s.commit()
        rev_b = (
            await s.execute(
                text("SELECT id FROM document_revisions WHERE document_id=:d"), {"d": b.id}
            )
        ).scalar_one()
        with pytest.raises(IntegrityError):
            await s.execute(
                text("UPDATE documents SET current_revision_id=:r WHERE id=:d"),
                {"r": rev_b, "d": a.id},
            )
        await s.rollback()


async def test_ready_revision_requires_page_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        doc = await make_document(s, status=None)
        s.add(
            DocumentRevision(
                document_id=doc.id,
                storage_key="k",
                status="ready",
                size_bytes=1,
                content_type="application/pdf",
            )
        )
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()


def test_q7_malformed_id_gets_the_uniform_404() -> None:
    ref = document_not_found()
    with pytest.raises(AppError) as exc:
        parse_document_id("not-a-uuid")
    err = exc.value
    assert (err.status_code, err.code, err.message) == (ref.status_code, ref.code, ref.message)
    assert (ref.status_code, ref.code) == (404, "DOCUMENT_NOT_FOUND")
    assert parse_document_id(str(FIN)) == FIN


def test_m2_downgrade_0003_removes_document_tables_and_upgrades_again(database_url: str) -> None:
    """Rollback of 0003 leaves 0002 intact; runs on its own disposable database."""
    import asyncio
    import os

    from alembic import command
    from alembic.config import Config

    from conftest import ALEMBIC_INI
    from knowserve_core.db import create_engine

    name = f"knowserve_test_dg_{uuid.uuid4().hex[:8]}"
    admin_url = database_url.rsplit("/", 1)[0] + "/postgres"
    url = database_url.rsplit("/", 1)[0] + f"/{name}"

    async def admin(sql: str) -> None:
        eng = create_engine(admin_url, null_pool=True)
        try:
            async with eng.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text(sql))
        finally:
            await eng.dispose()

    async def tables() -> set[str]:
        eng = create_engine(url, null_pool=True)
        try:
            async with eng.connect() as conn:
                rows = await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
                return set(rows.scalars())
        finally:
            await eng.dispose()

    doc_tables = {"documents", "document_revisions", "document_department_access"}
    previous = os.environ.get("KS_DATABASE_URL")
    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        os.environ["KS_DATABASE_URL"] = url
        cfg = Config(str(ALEMBIC_INI))
        command.upgrade(cfg, "head")
        assert doc_tables <= asyncio.run(tables())
        command.downgrade(cfg, "0002")
        remaining = asyncio.run(tables())
        assert not doc_tables & remaining
        assert {"departments", "users", "sessions"} <= remaining
        command.upgrade(cfg, "head")
        assert doc_tables <= asyncio.run(tables())
    finally:
        if previous is None:
            os.environ.pop("KS_DATABASE_URL", None)
        else:
            os.environ["KS_DATABASE_URL"] = previous
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
