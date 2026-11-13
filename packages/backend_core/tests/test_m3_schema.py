"""M3-01 tests: migration 0004 (chunks, revision-to-job link, Admin idempotency, import entries).

Covers ING-02, ING-17, ING-21, ADM-13, ADM-14 at the schema level. Behavior (the Worker pipeline,
the creation service) is tested by the slices that write it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core.ingestion_contract import EMBEDDING_DIMENSIONS
from knowserve_core.models import (
    AdminIdempotencyKey,
    Base,
    DocumentChunk,
    DocumentRevision,
    ImportBatchEntry,
    Job,
)
from knowserve_core.testing import make_document

pytestmark = [pytest.mark.m3, pytest.mark.integration]

VECTOR = [0.0] * EMBEDDING_DIMENSIONS


async def _revision(session: AsyncSession) -> DocumentRevision:
    doc = await make_document(session)
    revision = (
        await session.execute(
            text("SELECT id FROM document_revisions WHERE document_id = :d"), {"d": doc.id}
        )
    ).scalar_one()
    row = await session.get(DocumentRevision, revision)
    assert row is not None
    return row


def _chunk(revision: DocumentRevision, ordinal: int = 0, **kw: object) -> DocumentChunk:
    values: dict[str, object] = {
        "document_id": revision.document_id,
        "revision_id": revision.id,
        "page": 1,
        "ordinal": ordinal,
        "text": "Some text.",
        "token_count": 3,
        "embedding": VECTOR,
    }
    values.update(kw)
    return DocumentChunk(**values)


async def test_m3_schema_tables_and_columns_match_the_models(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        for table in (
            "document_chunks",
            "admin_idempotency_keys",
            "import_batch_entries",
            "document_revisions",
        ):
            db_columns = await conn.run_sync(
                lambda c, t=table: {col["name"] for col in inspect(c).get_columns(t)}
            )
            model_columns = {col.name for col in Base.metadata.tables[table].columns}
            assert db_columns == model_columns, table


async def test_m3_ing17_embedding_column_has_the_contract_width_and_no_vector_index(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as conn:
        width = (
            await conn.execute(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
        assert width == f"vector({EMBEDDING_DIMENSIONS})"
        # OPEN-31 D5: no approximate index in M3; M4 decides after measuring.
        methods = (
            await conn.execute(
                text(
                    "SELECT am.amname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "JOIN pg_am am ON am.oid = c.relam "
                    "WHERE i.indrelid = 'document_chunks'::regclass"
                )
            )
        ).scalars()
        assert not {m for m in methods if m in ("hnsw", "ivfflat")}


async def test_m3_ing02_chunk_must_belong_to_a_revision_of_the_same_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        revision = await _revision(session)
        other = await make_document(session)
        session.add(_chunk(revision, document_id=other.id))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_m3_ing02_chunk_ordinal_is_unique_per_revision_and_values_are_checked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        revision = await _revision(session)
        session.add(_chunk(revision, 0))
        session.add(_chunk(revision, 1, page=2))
        await session.flush()
        session.add(_chunk(revision, 1))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    for bad in ({"page": 0}, {"ordinal": -1}, {"token_count": 0}):
        async with session_factory() as session:
            revision = await _revision(session)
            session.add(_chunk(revision, **bad))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()


async def test_m3_chunks_are_removed_with_their_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        revision = await _revision(session)
        session.add(_chunk(revision))
        await session.flush()
        # The current pointer is not a cascade target; detach it, then delete the revision (M5).
        await session.execute(
            text("UPDATE documents SET current_revision_id = NULL WHERE id = :d"),
            {"d": revision.document_id},
        )
        await session.execute(
            text("DELETE FROM document_revisions WHERE id = :r"), {"r": revision.id}
        )
        left = (
            await session.execute(
                text("SELECT count(*) FROM document_chunks WHERE revision_id = :r"),
                {"r": revision.id},
            )
        ).scalar_one()
        assert left == 0
        await session.rollback()


async def test_m3_ing21_a_job_belongs_to_at_most_one_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await _revision(session)
        second = await _revision(session)
        third = await _revision(session)
        job = Job(job_type="ingest_revision", status="queued", attempts=0, correlation_id="c")
        session.add(job)
        await session.flush()
        first.job_id = job.id
        await session.flush()
        # Seeded revisions have no job: many NULLs are allowed.
        assert second.job_id is None and third.job_id is None
        second.job_id = job.id
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_m3_adm13_idempotency_key_is_unique_per_admin_and_checked(
    session_factory: async_sessionmaker[AsyncSession], make_user
) -> None:
    admin = await make_user("admin")
    other = await make_user("admin")

    def row(user_id: uuid.UUID, **kw: object) -> AdminIdempotencyKey:
        values: dict[str, object] = {
            "admin_user_id": user_id,
            "idempotency_key": "key-0001-abcd",
            "operation": "create_document",
            "request_hash": "a" * 64,
            "result_status": 202,
            "result": {"document_id": str(uuid.uuid4())},
        }
        values.update(kw)
        return AdminIdempotencyKey(**values)

    async with session_factory() as session:
        session.add(row(admin.id))
        session.add(row(other.id))  # the same key under another Admin is a different key
        await session.flush()
        session.add(row(admin.id))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    for bad in ({"operation": "delete_everything"}, {"request_hash": "short"}):
        async with session_factory() as session:
            session.add(row(admin.id, idempotency_key=f"key-{uuid.uuid4().hex}", **bad))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()


async def test_m3_adm14_import_entry_outcome_shape_and_uniqueness(
    session_factory: async_sessionmaker[AsyncSession], make_user
) -> None:
    admin = await make_user("admin")
    async with session_factory() as session:
        doc = await make_document(session)
        key = AdminIdempotencyKey(
            admin_user_id=admin.id,
            idempotency_key="import-key-0001",
            operation="confirm_import",
            request_hash="b" * 64,
            result_status=200,
            result={},
        )
        session.add(key)
        await session.flush()
        session.add(
            ImportBatchEntry(
                idempotency_key_id=key.id, entry_key="a.pdf", outcome="created", document_id=doc.id
            )
        )
        session.add(
            ImportBatchEntry(
                idempotency_key_id=key.id,
                entry_key="b.pdf",
                outcome="rejected",
                error_code="UNKNOWN_DEPARTMENT",
            )
        )
        await session.flush()
        for bad in (
            {"entry_key": "a.pdf", "outcome": "rejected", "error_code": "X"},  # duplicate entry
            {"entry_key": "c.pdf", "outcome": "created"},  # created without a document
            {"entry_key": "d.pdf", "outcome": "rejected"},  # rejected without a code
            {"entry_key": "e.pdf", "outcome": "created", "document_id": doc.id, "error_code": "X"},
            {"entry_key": "f.pdf", "outcome": "skipped", "error_code": "X"},
        ):
            async with session.begin_nested():
                session.add(ImportBatchEntry(idempotency_key_id=key.id, **bad))
                with pytest.raises(IntegrityError):
                    await session.flush()
        await session.rollback()


def test_m3_downgrade_0004_drops_only_the_m3_objects_and_upgrades_again(database_url: str) -> None:
    """Rollback of 0004 leaves 0003 intact; runs on its own disposable database."""
    import asyncio
    import os

    from alembic import command
    from alembic.config import Config

    from conftest import ALEMBIC_INI
    from knowserve_core.db import create_engine

    name = f"knowserve_test_dg4_{uuid.uuid4().hex[:8]}"
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

    async def state() -> tuple[set[str], set[str]]:
        eng = create_engine(url, null_pool=True)
        try:
            async with eng.connect() as conn:
                tables = await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
                columns = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'document_revisions'"
                    )
                )
                return set(tables.scalars()), set(columns.scalars())
        finally:
            await eng.dispose()

    added = {"document_chunks", "admin_idempotency_keys", "import_batch_entries"}
    previous = os.environ.get("KS_DATABASE_URL")
    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        os.environ["KS_DATABASE_URL"] = url
        cfg = Config(str(ALEMBIC_INI))
        command.upgrade(cfg, "head")
        tables, columns = asyncio.run(state())
        assert added <= tables and "job_id" in columns
        command.downgrade(cfg, "0003")
        tables, columns = asyncio.run(state())
        assert not added & tables and "job_id" not in columns
        assert {"documents", "document_revisions", "document_department_access"} <= tables
        command.upgrade(cfg, "head")
        tables, columns = asyncio.run(state())
        assert added <= tables and "job_id" in columns
    finally:
        if previous is None:
            os.environ.pop("KS_DATABASE_URL", None)
        else:
            os.environ["KS_DATABASE_URL"] = previous
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_m3_0004_upgrade_keeps_existing_m2_document_data(database_url: str) -> None:
    """Upgrading 0003 to 0004 with M2 rows present changes none of them (no destructive step)."""
    import asyncio
    import os

    from alembic import command
    from alembic.config import Config

    from conftest import ALEMBIC_INI
    from knowserve_core.db import create_engine

    name = f"knowserve_test_up4_{uuid.uuid4().hex[:8]}"
    admin_url = database_url.rsplit("/", 1)[0] + "/postgres"
    url = database_url.rsplit("/", 1)[0] + f"/{name}"
    doc_id, rev_id = uuid.uuid4(), uuid.uuid4()

    async def run(target: str, sql: str, params: dict | None = None, *, autocommit: bool = False):
        eng = create_engine(target, null_pool=True)
        try:
            async with eng.connect() as conn:
                if autocommit:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                result = await conn.execute(text(sql), params or {})
                rows = result.all() if result.returns_rows else []
                await conn.commit()
                return rows
        finally:
            await eng.dispose()

    previous = os.environ.get("KS_DATABASE_URL")
    asyncio.run(run(admin_url, f'CREATE DATABASE "{name}"', autocommit=True))
    try:
        os.environ["KS_DATABASE_URL"] = url
        cfg = Config(str(ALEMBIC_INI))
        command.upgrade(cfg, "0003")
        dept = asyncio.run(run(url, "SELECT id FROM departments LIMIT 1"))[0][0]
        asyncio.run(
            run(
                url,
                "INSERT INTO documents (id, title, filename, owner_department_id) "
                "VALUES (:d, 'Kept', 'kept.pdf', :o)",
                {"d": doc_id, "o": dept},
            )
        )
        asyncio.run(
            run(
                url,
                "INSERT INTO document_revisions (id, document_id, storage_key, status, "
                "page_count, size_bytes, content_type, ready_at) "
                "VALUES (:r, :d, 'k', 'ready', 2, 10, 'application/pdf', now())",
                {"r": rev_id, "d": doc_id},
            )
        )
        asyncio.run(
            run(
                url,
                "UPDATE documents SET current_revision_id = :r WHERE id = :d",
                {"r": rev_id, "d": doc_id},
            )
        )
        asyncio.run(
            run(
                url,
                "INSERT INTO document_department_access (document_id, department_id) "
                "VALUES (:d, :o)",
                {"d": doc_id, "o": dept},
            )
        )
        command.upgrade(cfg, "0004")
        row = asyncio.run(
            run(
                url,
                "SELECT d.title, d.current_revision_id, r.status, r.page_count, r.job_id, "
                "(SELECT count(*) FROM document_department_access WHERE document_id = d.id) "
                "FROM documents d JOIN document_revisions r ON r.document_id = d.id "
                "WHERE d.id = :d",
                {"d": doc_id},
            )
        )[0]
        assert tuple(row) == ("Kept", rev_id, "ready", 2, None, 1)
    finally:
        if previous is None:
            os.environ.pop("KS_DATABASE_URL", None)
        else:
            os.environ["KS_DATABASE_URL"] = previous
        asyncio.run(
            run(admin_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', autocommit=True)
        )
