"""M2-05 tests: deterministic generator, idempotent seed, varied access (M2-AC15, SEC-04/05)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_api.seed.documents import DATA_DIR, pdf_page_count, seed_documents
from knowserve_api.seed.pdf import build_pdf, render
from knowserve_api.seed.specs import ALL_DEPARTMENTS, SEED_DOCUMENTS
from knowserve_core.documents_access import visible_documents
from knowserve_core.models import Document, DocumentDepartmentAccess, DocumentRevision
from knowserve_core.object_store import FakeObjectStore, FilesystemObjectStore
from knowserve_core.testing import DEPARTMENT_IDS

pytestmark = [pytest.mark.m2, pytest.mark.documents]

BY_SLUG = {d.slug: d for d in SEED_DOCUMENTS}


def test_m2_ac15_generator_is_deterministic() -> None:
    first = build_pdf("T", ["alpha beta", "gamma"], 2)
    assert first == build_pdf("T", ["alpha beta", "gamma"], 2)
    assert first.startswith(b"%PDF-1.4") and first.endswith(b"%%EOF\n")
    assert pdf_page_count(first) == 2


def test_m2_ac15_committed_pdfs_match_generator() -> None:
    for spec in SEED_DOCUMENTS:
        committed = (DATA_DIR / spec.filename).read_bytes()
        assert committed == render(spec), f"{spec.filename} is stale; run knowserve_api.seed.pdf"
        assert pdf_page_count(committed) == spec.pages
        assert len(committed) < 50_000


def test_m2_ac15_seed_shape_and_ids() -> None:
    assert 3 <= len(SEED_DOCUMENTS) <= 5
    assert len({d.document_id for d in SEED_DOCUMENTS}) == len(SEED_DOCUMENTS)
    assert BY_SLUG["seed-company-handbook"].allowed == ALL_DEPARTMENTS
    # Ids are stable across processes: pin one so a namespace edit fails loudly.
    assert str(BY_SLUG["seed-incident-runbook"].document_id) == str(
        uuid.uuid5(
            uuid.UUID("6d8218b5-7a4f-4e6e-bfbc-c9a54d2ca581"), "document:seed-incident-runbook"
        )
    )
    owner_c = BY_SLUG["seed-contract-review-checklist"]
    assert owner_c.owner not in owner_c.allowed


@pytest.mark.integration
async def test_m2_ac15_seed_is_idempotent_and_varied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = FakeObjectStore()
    first = await seed_documents(session_factory, store)
    assert set(first.values()) == {"created"}
    async with session_factory() as s:
        snapshot = await _snapshot(s)
    bytes_before = {k: await _read(store, k) for k in (d.storage_key for d in SEED_DOCUMENTS)}

    second = await seed_documents(session_factory, store)
    assert set(second.values()) == {"unchanged"}
    async with session_factory() as s:
        assert await _snapshot(s) == snapshot
        # No chunks and no jobs (Q8): the seed only writes documents.
        for table in ("jobs", "outbox"):
            assert await s.scalar(text(f"SELECT count(*) FROM {table}")) == 0
    assert bytes_before == {k: await _read(store, k) for k in bytes_before}
    assert all(
        bytes_before[d.storage_key] == (DATA_DIR / d.filename).read_bytes() for d in SEED_DOCUMENTS
    )


@pytest.mark.integration
async def test_sec04_sec05_seed_visibility_per_department(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_documents(session_factory, FakeObjectStore())
    expected: dict[str, set[str]] = {dept: set() for dept in DEPARTMENT_IDS}
    for spec in SEED_DOCUMENTS:
        for dept in spec.allowed:
            expected[dept].add(spec.slug)
    async with session_factory() as s:
        for dept, dept_id in DEPARTMENT_IDS.items():
            rows = (await s.execute(visible_documents(uuid.UUID(dept_id)))).all()
            titles = {row[0].title for row in rows}
            assert titles == {BY_SLUG[slug].title for slug in expected[dept]}, dept
            for _doc, rev in rows:
                assert rev.status == "ready" and rev.page_count and rev.page_count >= 1
        # Owner Legal is not a reader of its own document, Sales is.
        assert expected["legal"] == {"seed-company-handbook"}
        assert "seed-contract-review-checklist" in expected["sales"]


@pytest.mark.integration
async def test_m2_ac15_seed_never_overwrites_existing_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec = BY_SLUG["seed-incident-runbook"]
    store = FakeObjectStore()
    await store.put(spec.storage_key, b"somebody else's bytes", "application/pdf")
    outcomes = await seed_documents(session_factory, store, specs=[spec])
    assert outcomes[spec.slug] == "object_conflict"
    assert await _read(store, spec.storage_key) == b"somebody else's bytes"
    async with session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(Document)) == 0


@pytest.mark.integration
async def test_m2_ac15_seed_keeps_existing_rows_untouched(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec = BY_SLUG["seed-budget-planning"]
    store = FakeObjectStore()
    await seed_documents(session_factory, store, specs=[spec])
    async with session_factory() as s:
        await s.execute(
            text("UPDATE documents SET title = 'Edited by hand' WHERE id = :i"),
            {"i": spec.document_id},
        )
        await s.execute(
            text(
                "DELETE FROM document_department_access "
                "WHERE document_id = :i AND department_id = :d"
            ),
            {"i": spec.document_id, "d": DEPARTMENT_IDS["engineering"]},
        )
        await s.commit()
    # A hand-edited access set is not the seed shape: flagged, never success, never repaired.
    assert (await seed_documents(session_factory, store, specs=[spec]))[spec.slug] == "incomplete"
    async with session_factory() as s:
        assert await s.scalar(select(Document.title)) == "Edited by hand"
        assert await s.scalar(select(func.count()).select_from(DocumentDepartmentAccess)) == 1


@pytest.mark.integration
async def test_m2_ac15_seed_repairs_missing_object_without_touching_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec = BY_SLUG["seed-incident-runbook"]
    await seed_documents(session_factory, FakeObjectStore(), specs=[spec])
    fresh = FakeObjectStore()  # the object is gone, rows remain
    assert (await seed_documents(session_factory, fresh, specs=[spec]))[spec.slug] == "unchanged"
    assert await _read(fresh, spec.storage_key) == (DATA_DIR / spec.filename).read_bytes()


@pytest.mark.integration
async def test_m2_ac15_seed_through_filesystem_store_twice(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = FilesystemObjectStore(tmp_path)
    await seed_documents(session_factory, store)
    before = _tree(tmp_path)
    assert len(before) == len(SEED_DOCUMENTS)
    await seed_documents(session_factory, store)
    assert before == _tree(tmp_path)


def _tree(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*.pdf")}


async def _read(store: FakeObjectStore | FilesystemObjectStore, key: str) -> bytes:
    return b"".join([chunk async for chunk in store.stream(key)])


async def _snapshot(s: AsyncSession) -> tuple[list[tuple[object, ...]], ...]:
    docs = (await s.execute(select(Document).order_by(Document.id))).scalars().all()
    revs = (await s.execute(select(DocumentRevision).order_by(DocumentRevision.id))).scalars().all()
    acc = (
        (
            await s.execute(
                select(DocumentDepartmentAccess).order_by(
                    DocumentDepartmentAccess.document_id, DocumentDepartmentAccess.department_id
                )
            )
        )
        .scalars()
        .all()
    )
    return (
        [(d.id, d.title, d.current_revision_id, d.updated_at) for d in docs],
        [(r.id, r.storage_key, r.size_bytes, r.ready_at, r.page_count) for r in revs],
        [(a.document_id, a.department_id) for a in acc],
    )


# --- production job behavior (M2-05, M2-00c): R2 settings, refusal before the migration ----------


async def test_m2_ac15_r2_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowserve_api.seed.documents import r2_config_from_env

    for name in (
        "KS_R2_ENDPOINT",
        "KS_R2_BUCKET",
        "KS_R2_ACCESS_KEY_ID",
        "KS_R2_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    empty = r2_config_from_env()
    assert (empty.endpoint, empty.bucket, empty.access_key_id, empty.secret_access_key) == (
        None,
        None,
        None,
        None,
    )
    monkeypatch.setenv("KS_R2_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("KS_R2_BUCKET", "bucket")
    monkeypatch.setenv("KS_R2_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("KS_R2_SECRET_ACCESS_KEY", "key-secret")
    full = r2_config_from_env()
    assert (full.endpoint, full.bucket) == ("https://acct.r2.cloudflarestorage.com", "bucket")
    assert (full.access_key_id, full.secret_access_key) == ("key-id", "key-secret")


@pytest.mark.parametrize("kind", ["fake", "filesystem", "r2"])
async def test_m2_ac15_production_seed_refuses_a_missing_or_non_r2_store_without_printing_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    from knowserve_api.seed.documents import _run

    monkeypatch.setenv("KS_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/none")
    monkeypatch.setenv("KS_ENV", "production")
    monkeypatch.setenv("KS_OBJECT_STORE", kind)
    for name in (
        "KS_R2_ENDPOINT",
        "KS_R2_BUCKET",
        "KS_R2_ACCESS_KEY_ID",
        "KS_R2_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    assert await _run() == 2
    err = capsys.readouterr().err
    assert "document seed refused" in err
    assert "u:p@" not in err


@pytest.mark.integration
async def test_m2_ac15_seed_refuses_until_migration_0003_has_created_the_tables(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowserve_api.seed.documents import _run, schema_ready
    from knowserve_core.db import create_engine

    name = f"knowserve_test_seed_{uuid.uuid4().hex[:8]}"
    base = database_url.rsplit("/", 1)[0]

    async def admin(sql: str) -> None:
        eng = create_engine(base + "/postgres", null_pool=True)
        try:
            async with eng.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text(sql))
        finally:
            await eng.dispose()

    await admin(f'CREATE DATABASE "{name}"')
    try:
        empty = create_engine(f"{base}/{name}", null_pool=True)
        try:
            assert await schema_ready(empty) is False
        finally:
            await empty.dispose()
        monkeypatch.setenv("KS_DATABASE_URL", f"{base}/{name}")
        monkeypatch.setenv("KS_ENV", "local")
        monkeypatch.setenv("KS_OBJECT_STORE", "fake")
        assert await _run() == 2
        assert "migration 0003 has not run" in capsys.readouterr().err
    finally:
        await admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.mark.integration
async def test_m2_ac15_schema_is_ready_on_the_migrated_test_database(engine: object) -> None:
    from knowserve_api.seed.documents import schema_ready

    assert await schema_ready(engine) is True  # type: ignore[arg-type]
