"""M3-02c seed ingestion tests (OPEN-28 Q8, OPEN-31 D4; M3-AC21). Real PostgreSQL, fake object
store and embedder, real extraction. Local only: nothing here reaches a cloud service."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core.embeddings import FakeEmbeddingProvider
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS, make_document
from knowserve_core.testing_fixtures import pdf_corrupt, pdf_two_pages
from knowserve_worker.seed_ingest import guard, ingest_seeded

pytestmark = [pytest.mark.m3, pytest.mark.worker, pytest.mark.integration]

Factory = async_sessionmaker[AsyncSession]
FINANCE = uuid.UUID(DEPARTMENT_IDS["finance"])


def make_settings(url: str, **kw: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,  # pyright: ignore[reportCallIssue]
        database_url=url,
        env="local",
        embedding_provider="fake",
        **kw,
    )


class Seeded:
    def __init__(self, factory: Factory, url: str) -> None:
        self.factory = factory
        self.store = FakeObjectStore()
        self.provider = FakeEmbeddingProvider()
        self.settings = make_settings(url)

    async def seed(self, pdf: bytes | None = None, **kw: Any) -> tuple[uuid.UUID, uuid.UUID]:
        """A document as the M2 seed creates it: ready revision, no chunks, no job."""
        async with self.factory() as s, s.begin():
            doc = await make_document(s, status="ready", **kw)
            row = (
                await s.execute(
                    text("SELECT id, storage_key FROM document_revisions WHERE document_id = :d"),
                    {"d": doc.id},
                )
            ).one()
        if pdf is not None:
            await self.store.put(row.storage_key, pdf, "application/pdf")
        return doc.id, row.id

    async def run(self) -> dict[uuid.UUID, str]:
        return (
            await ingest_seeded(self.factory, self.store, self.provider, self.settings)
        ).outcomes

    async def one(self, sql: str, **params: Any) -> Any:
        async with self.factory() as s:
            return (await s.execute(text(sql), params)).one()

    async def chunk_count(self, revision_id: uuid.UUID) -> int:
        row = await self.one(
            "SELECT count(*) AS n FROM document_chunks WHERE revision_id = :r", r=revision_id
        )
        return row.n


@pytest_asyncio.fixture
async def seeded(
    engine: AsyncEngine, session_factory: Factory, database_url: str
) -> AsyncIterator[Seeded]:
    yield Seeded(session_factory, database_url)


async def test_m3_ac21_seeded_revisions_are_indexed_with_ids_and_state_unchanged(
    seeded: Seeded,
) -> None:
    doc_id, rev_id = await seeded.seed(pdf_two_pages())
    before_rev = await seeded.one("SELECT * FROM document_revisions WHERE id = :i", i=rev_id)
    before_doc = await seeded.one("SELECT * FROM documents WHERE id = :i", i=doc_id)
    assert await seeded.run() == {rev_id: "ingested"}
    after_rev = await seeded.one("SELECT * FROM document_revisions WHERE id = :i", i=rev_id)
    after_doc = await seeded.one("SELECT * FROM documents WHERE id = :i", i=doc_id)
    for column in ("id", "document_id", "status", "phase", "page_count", "ready_at", "storage_key"):
        assert getattr(after_rev, column) == getattr(before_rev, column), column
    assert after_doc.current_revision_id == before_doc.current_revision_id == rev_id
    assert after_rev.index_identity and after_rev.embedding_model == "fake-embedding"
    assert after_rev.job_id is not None
    assert await seeded.chunk_count(rev_id) == 2
    job = await seeded.one("SELECT * FROM jobs WHERE id = :i", i=after_rev.job_id)
    assert (job.status, job.attempts, job.job_type) == ("done", 1, "ingest_revision")
    outbox = await seeded.one("SELECT status FROM outbox WHERE job_id = :i", i=after_rev.job_id)
    assert outbox.status == "published"  # it ran in process; nothing is left to publish


async def test_m3_ac21_second_run_changes_nothing(seeded: Seeded) -> None:
    _, rev_id = await seeded.seed(pdf_two_pages())
    await seeded.run()
    chunks = await seeded.one(
        "SELECT array_agg(id ORDER BY ordinal) AS ids FROM document_chunks WHERE revision_id = :r",
        r=rev_id,
    )
    jobs = await seeded.one("SELECT count(*) AS n FROM jobs")
    assert await seeded.run() == {}  # nothing is selected any more
    again = await seeded.one(
        "SELECT array_agg(id ORDER BY ordinal) AS ids FROM document_chunks WHERE revision_id = :r",
        r=rev_id,
    )
    assert again.ids == chunks.ids
    assert (await seeded.one("SELECT count(*) AS n FROM jobs")).n == jobs.n


async def test_m3_ac21_failed_reindex_keeps_the_revision_ready_and_can_be_rerun(
    seeded: Seeded,
) -> None:
    doc_id, rev_id = await seeded.seed(pdf_corrupt())
    assert await seeded.run() == {rev_id: "failed:INVALID_PDF"}
    rev = await seeded.one("SELECT * FROM document_revisions WHERE id = :i", i=rev_id)
    assert (rev.status, rev.failure_reason) == ("ready", None)
    assert await seeded.chunk_count(rev_id) == 0
    first_job = rev.job_id
    assert (await seeded.one("SELECT status FROM jobs WHERE id = :i", i=first_job)).status == (
        "failed"
    )
    # The cause is fixed (the object is replaced); the rerun picks the revision up again.
    await seeded.store.put(rev.storage_key, pdf_two_pages(), "application/pdf")
    assert await seeded.run() == {rev_id: "ingested"}
    rev = await seeded.one("SELECT * FROM document_revisions WHERE id = :i", i=rev_id)
    assert rev.job_id != first_job and rev.status == "ready"
    assert await seeded.chunk_count(rev_id) == 2


async def test_m3_seed_ingest_leaves_uploads_deleted_documents_and_live_jobs_alone(
    seeded: Seeded,
) -> None:
    # A revision still being processed by its own job is not a seed revision.
    async with seeded.factory() as s, s.begin():
        doc = await make_document(s, status="queued")
        await s.execute(
            text("UPDATE documents SET current_revision_id = NULL WHERE id = :d"), {"d": doc.id}
        )
    deleted_doc, _ = await seeded.seed(pdf_two_pages())
    async with seeded.factory() as s, s.begin():
        await s.execute(
            text("UPDATE documents SET deleted_at = now() WHERE id = :d"), {"d": deleted_doc}
        )
    assert await seeded.run() == {}
    assert (await seeded.one("SELECT count(*) AS n FROM document_chunks")).n == 0
    assert (await seeded.one("SELECT count(*) AS n FROM jobs")).n == 0


@pytest.mark.parametrize(
    ("lease", "expected"),
    [
        ("now() + interval '5 minutes'", "in_progress"),  # another run holds it
        ("now() - interval '5 minutes'", "ingested"),  # a killed run: pick it up again
        ("NULL", "ingested"),
    ],
)
async def test_m3_seed_ingest_only_a_live_lease_counts_as_in_progress(
    seeded: Seeded, lease: str, expected: str
) -> None:
    _, rev_id = await seeded.seed(pdf_two_pages())
    async with seeded.factory() as s, s.begin():
        job_id = (
            await s.execute(
                text(
                    "INSERT INTO jobs (job_type, status, correlation_id, claimed_by, "
                    f"lease_expires_at) VALUES ('ingest_revision', 'processing', 'x', 'dead', "
                    f"{lease}) RETURNING id"
                )
            )
        ).scalar_one()
        await s.execute(
            text("UPDATE document_revisions SET job_id = :j WHERE id = :r"),
            {"j": job_id, "r": rev_id},
        )
    assert await seeded.run() == {rev_id: expected}
    assert await seeded.chunk_count(rev_id) == (0 if expected == "in_progress" else 2)


async def test_m3_seed_ingest_a_done_job_on_a_chunkless_revision_is_run_again(
    seeded: Seeded,
) -> None:
    _, rev_id = await seeded.seed(pdf_two_pages())
    assert await seeded.run() == {rev_id: "ingested"}
    async with seeded.factory() as s, s.begin():
        await s.execute(text("DELETE FROM document_chunks"))  # e.g. chunks were cleaned up
    assert await seeded.run() == {rev_id: "ingested"}
    assert await seeded.chunk_count(rev_id) == 2


def test_m3_seed_ingest_refuses_production_without_the_explicit_flag() -> None:
    prod = Settings(  # type: ignore[call-arg]
        _env_file=None,  # pyright: ignore[reportCallIssue]
        database_url="postgresql://u:p@localhost/db",
        env="production",
        embedding_provider="openai",
        openai_api_key="sk-test",
        object_store="r2",
        qstash_token="t",
        qstash_current_signing_key="a",
        qstash_next_signing_key="b",
        worker_public_url="https://w.test",
    )
    assert guard(prod, []) is not None
    assert guard(prod, ["--allow-production"]) is None
    assert guard(make_settings("postgresql://u:p@localhost/db"), []) is None


async def test_m3_seed_flag_ingest_runs_the_worker_command_after_seeding(
    seeded: Seeded,
    database_url: str,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``python -m knowserve_api.seed.documents --ingest`` seeds, then calls the ingest command;
    without the flag it does not (the M2 behavior is unchanged)."""
    import knowserve_worker.seed_ingest as seed_ingest
    from knowserve_api.seed import documents as seed

    calls: list[int] = []

    async def fake_ingest(argv: list[str] | None = None) -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(seed_ingest, "ingest_from_env", fake_ingest)
    monkeypatch.setenv("KS_DATABASE_URL", database_url)
    monkeypatch.setenv("KS_OBJECT_STORE", "filesystem")
    monkeypatch.setenv("KS_OBJECT_STORE_PATH", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["seed"])
    assert await seed._run() == 0 and calls == []
    monkeypatch.setattr("sys.argv", ["seed", "--ingest"])
    assert await seed._run() == 0 and calls == [1]


def test_m3_seed_ingest_guard_also_covers_r2_and_fake_embeddings_on_a_remote_database() -> None:
    local = make_settings("postgresql://u:p@localhost/db")
    assert guard(local, []) is None
    remote_fake = make_settings("postgresql://u:p@db.example.com/db")
    assert guard(remote_fake, []) is not None
    assert guard(remote_fake, ["--allow-production"]) is None
    r2 = make_settings(
        "postgresql://u:p@localhost/db",
        object_store="r2",
        r2_endpoint="https://x.test",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
    )
    assert guard(r2, []) is not None
