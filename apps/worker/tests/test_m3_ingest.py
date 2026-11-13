"""M3-02b ingest_revision handler tests (ING-02, 05, 07, 09, 10, 17, 18, 19, 23; M3-AC05..09, 18,
21). Real PostgreSQL with pgvector, a fake object store, the fake embedder and real PyMuPDF
extraction on the M3-01 fixture PDFs. The job is delivered through the signed Worker endpoint.
No real OpenAI call and no real R2 call."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from conftest import sign_qstash_delivery
from knowserve_core.documents_access import visible_documents
from knowserve_core.embeddings import FakeEmbeddingProvider
from knowserve_core.ingestion_contract import (
    EMBEDDING_DIMENSIONS,
    INGEST_JOB_TYPE,
    PHASES,
    build_index_identity,
)
from knowserve_core.jobs import enqueue_job
from knowserve_core.object_store import FakeObjectStore, ObjectStoreError
from knowserve_core.qstash import FakePublisher
from knowserve_core.settings import Settings
from knowserve_core.testing import DEPARTMENT_IDS, make_document
from knowserve_core.testing_fixtures import (
    pdf_corrupt,
    pdf_encrypted,
    pdf_image_only,
    pdf_many_pages,
    pdf_two_pages,
    pdf_with_nul_in_text,
)
from knowserve_worker.app import create_app

pytestmark = [pytest.mark.m3, pytest.mark.worker, pytest.mark.integration]

CURRENT = "local-only-qstash-current-key-not-a-secret"
NEXT = "local-only-qstash-next-key-not-a-secret"
PUBLIC_URL = "https://worker.test"
RUN_URL = PUBLIC_URL + "/internal/jobs/run"
FINANCE = uuid.UUID(DEPARTMENT_IDS["finance"])
Factory = async_sessionmaker[AsyncSession]


class SpyStore(FakeObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0
        self.on_read: Any = None

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.writes += 1
        await super().put(key, data, content_type)

    async def delete(self, key: str) -> None:
        self.writes += 1
        await super().delete(key)

    async def stream(self, key: str, byte_range: Any = None) -> AsyncIterator[bytes]:
        if self.on_read:
            await self.on_read()
        async for part in super().stream(key, byte_range):
            yield part


class SpyProvider(FakeEmbeddingProvider):
    """Records the revision phase at the moment of the embedding call, runs a hook, may fail."""

    def __init__(self) -> None:
        super().__init__(EMBEDDING_DIMENSIONS)
        self.on_embed: Any = None
        self.texts: list[str] = []

    async def embed(self, texts: Any) -> list[list[float]]:
        self.texts.extend(texts)
        if self.on_embed:
            await self.on_embed()
        return await super().embed(texts)


class Harness:
    def __init__(self, engine: AsyncEngine, factory: Factory, url: str) -> None:
        self.engine, self.factory, self.url = engine, factory, url
        self.store = SpyStore()
        self.provider = SpyProvider()

    def app(self, **settings: Any) -> Any:
        values: dict[str, Any] = {
            "database_url": self.url,
            "env": "local",
            "qstash_current_signing_key": CURRENT,
            "qstash_next_signing_key": NEXT,
            "worker_public_url": PUBLIC_URL,
            "embedding_provider": "fake",
        }
        values.update(settings)
        return create_app(
            settings=Settings(_env_file=None, **values),  # type: ignore[call-arg]
            engine=self.engine,
            publisher=FakePublisher(),
            object_store=self.store,
            embedding_provider=self.provider,
            heartbeat_interval=0.1,
        )

    def client(self, app: Any) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL, timeout=60)

    async def deliver(self, client: httpx.AsyncClient, job_id: uuid.UUID) -> httpx.Response:
        body = json.dumps({"schema_version": 1, "job_id": str(job_id)}).encode()
        token = sign_qstash_delivery(body, CURRENT, RUN_URL)
        return await client.post(
            "/internal/jobs/run", content=body, headers={"Upstash-Signature": token}
        )

    async def make(
        self, pdf: bytes | None, *, status: str = "queued", allowed: tuple[str, ...] = ("finance",)
    ) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """A document with one revision and its ingest job. Returns (document, revision, job)."""
        async with self.factory() as s, s.begin():
            doc = await make_document(s, status=status, allowed=allowed)
            if status == "queued":
                # As the upload path creates it: no current revision until publication.
                await s.execute(
                    text("UPDATE documents SET current_revision_id = NULL WHERE id = :d"),
                    {"d": doc.id},
                )
            job = await enqueue_job(s, INGEST_JOB_TYPE)
            row = (
                await s.execute(
                    text(
                        "UPDATE document_revisions SET job_id = :j WHERE document_id = :d "
                        "RETURNING id, storage_key"
                    ),
                    {"j": job.id, "d": doc.id},
                )
            ).one()
        if pdf is not None:
            await self.store.put(row.storage_key, pdf, "application/pdf")
        return doc.id, row.id, job.id

    async def one(self, sql: str, **params: Any) -> Any:
        async with self.factory() as s:
            return (await s.execute(text(sql), params)).one()

    async def revision(self, revision_id: uuid.UUID) -> Any:
        return await self.one("SELECT * FROM document_revisions WHERE id = :i", i=revision_id)

    async def job(self, job_id: uuid.UUID) -> Any:
        return await self.one("SELECT * FROM jobs WHERE id = :i", i=job_id)

    async def chunks(self, revision_id: uuid.UUID) -> list[Any]:
        async with self.factory() as s:
            return list(
                (
                    await s.execute(
                        text(
                            "SELECT page, ordinal, text, token_count, document_id "
                            "FROM document_chunks WHERE revision_id = :i ORDER BY ordinal"
                        ),
                        {"i": revision_id},
                    )
                ).all()
            )

    async def visible(self, dept: uuid.UUID = FINANCE) -> list[uuid.UUID]:
        async with self.factory() as s:
            rows = (await s.execute(visible_documents(dept))).all()
        return [row[0].id for row in rows]

    async def sql(self, statement: str, **params: Any) -> None:
        async with self.factory() as s, s.begin():
            await s.execute(text(statement), params)


@pytest_asyncio.fixture
async def h(
    engine: AsyncEngine, session_factory: Factory, database_url: str
) -> AsyncIterator[Harness]:
    yield Harness(engine, session_factory, database_url)


# ----------------------------------------------------------------------------- happy path


async def test_ing17_happy_path_publishes_atomically_with_phases_and_identity(h: Harness) -> None:
    doc_id, rev_id, job_id = await h.make(pdf_two_pages())
    phases: list[str | None] = []

    async def record() -> None:
        phases.append((await h.revision(rev_id)).phase)

    h.store.on_read = record
    h.provider.on_embed = record
    assert await h.visible() == []
    h.store.writes = 0
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    assert phases == ["fetching", "embedding"]  # each phase is written before its stage
    assert tuple(PHASES) == ("fetching", "extracting", "chunking", "embedding", "publishing")

    revision = await h.revision(rev_id)
    assert (revision.status, revision.phase, revision.failure_reason) == ("ready", None, None)
    assert revision.page_count == 2 and revision.ready_at is not None
    assert revision.embedding_model == "fake-embedding"
    assert revision.index_identity == build_index_identity(
        "fake-embedding", EMBEDDING_DIMENSIONS, 512, 64
    )
    doc = await h.one("SELECT current_revision_id FROM documents WHERE id = :d", d=doc_id)
    assert doc.current_revision_id == rev_id
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("done", 1)
    assert await h.visible() == [doc_id]
    assert h.store.writes == 0  # the Worker only reads (OPEN-31 D6)


async def test_ing02_chunks_are_page_bound_and_carry_document_revision_and_page(
    h: Harness,
) -> None:
    doc_id, rev_id, job_id = await h.make(pdf_two_pages())
    async with h.client(h.app()) as c:
        await h.deliver(c, job_id)
    chunks = await h.chunks(rev_id)
    assert [c.ordinal for c in chunks] == list(range(len(chunks))) and len(chunks) == 2
    assert {c.page for c in chunks} == {1, 2}
    assert all(c.document_id == doc_id and c.token_count >= 1 for c in chunks)
    assert "twenty days" in chunks[0].text and "Expenses" in chunks[1].text


async def test_ing18_nul_characters_never_reach_the_database(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_with_nul_in_text())
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    chunks = await h.chunks(rev_id)
    assert chunks and all("\x00" not in c.text for c in chunks)


# ----------------------------------------------------------------------------- terminal failures


@pytest.mark.parametrize(
    ("pdf", "settings", "code"),
    [
        (pdf_image_only(), {}, "NO_EXTRACTABLE_TEXT"),
        (pdf_corrupt(), {}, "INVALID_PDF"),
        (pdf_encrypted(), {}, "PDF_ENCRYPTED"),
        (pdf_many_pages(3), {"upload_max_pdf_pages": 2}, "TOO_MANY_PAGES"),
    ],
)
async def test_ing23_terminal_reasons_fail_at_once_without_chunks_or_retries(
    h: Harness, pdf: bytes, settings: dict[str, Any], code: str
) -> None:
    doc_id, rev_id, job_id = await h.make(pdf)
    async with h.client(h.app(**settings)) as c:
        first = await h.deliver(c, job_id)
        second = await h.deliver(c, job_id)
    assert first.status_code == 500 and second.json() == {"result": "failed"}
    revision = await h.revision(rev_id)
    assert (revision.status, revision.failure_reason, revision.phase) == ("failed", code, None)
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("failed", 1)  # no backoff retry (ING-23)
    assert await h.chunks(rev_id) == []
    assert await h.visible() == []
    assert (await h.store.size(revision.storage_key)) > 0  # the file is kept (OPEN-17)
    doc = await h.one("SELECT current_revision_id FROM documents WHERE id = :d", d=doc_id)
    assert doc.current_revision_id is None


# ----------------------------------------------------------------------------- retryable failures


async def test_ing09_storage_failure_is_retried_to_the_cap_then_failed(h: Harness) -> None:
    _, rev_id, job_id = await h.make(None)  # no object in the store
    async with h.client(h.app()) as c:
        codes = [(await h.deliver(c, job_id)).status_code for _ in range(4)]
        after = await h.deliver(c, job_id)
    assert codes == [500, 500, 500, 500] and after.json() == {"result": "failed"}
    job = await h.job(job_id)
    assert (job.status, job.attempts) == ("failed", 4)
    revision = await h.revision(rev_id)
    assert (revision.status, revision.failure_reason) == ("failed", "STORAGE_UNAVAILABLE")


async def test_ing09_store_error_maps_to_storage_unavailable(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())

    async def boom() -> None:
        raise ObjectStoreError("network")

    h.store.on_read = boom
    async with h.client(h.app(job_max_attempts=1)) as c:
        await h.deliver(c, job_id)
    assert (await h.revision(rev_id)).failure_reason == "STORAGE_UNAVAILABLE"


async def test_ing09_embedding_failure_writes_nothing_and_is_retryable(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())
    h.provider = SpyProvider()
    h.provider._fail_after = 1
    async with h.client(h.app()) as c:
        first = await h.deliver(c, job_id)
    assert first.status_code == 500
    job = await h.job(job_id)
    assert (job.status, job.last_error) == ("queued", "EMBEDDING_FAILED")
    assert await h.chunks(rev_id) == []
    assert (await h.revision(rev_id)).status == "processing"
    async with h.client(h.app()) as c:
        h.provider._fail_after = None
        h.provider.calls = 0
        retry = await h.deliver(c, job_id)
    assert retry.json() == {"result": "done"}  # a later attempt succeeds from the start
    assert (await h.revision(rev_id)).status == "ready"


async def test_ing09_missing_openai_configuration_fails_the_attempt_not_the_worker(
    h: Harness, engine: AsyncEngine
) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())
    app = create_app(
        settings=Settings(  # type: ignore[call-arg]
            _env_file=None,  # pyright: ignore[reportCallIssue]
            database_url=h.url,
            env="local",
            qstash_current_signing_key=CURRENT,
            qstash_next_signing_key=NEXT,
            worker_public_url=PUBLIC_URL,
            embedding_provider="openai",  # and no KS_OPENAI_API_KEY
            job_max_attempts=1,
        ),
        engine=engine,
        publisher=FakePublisher(),
        object_store=h.store,
    )
    async with h.client(app) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    revision = await h.revision(rev_id)
    assert (revision.status, revision.failure_reason) == ("failed", "INTERNAL_ERROR")


# ----------------------------------------------------------------------------- idempotency


async def test_ing10_retry_from_scratch_replaces_stale_chunks(h: Harness) -> None:
    """An earlier attempt left chunks behind. The retry ends with one run's chunk set."""
    doc_id, rev_id, job_id = await h.make(pdf_two_pages())
    stale = "[" + ",".join(["0"] * EMBEDDING_DIMENSIONS) + "]"
    for ordinal in range(5):
        await h.sql(
            "INSERT INTO document_chunks (document_id, revision_id, page, ordinal, text, "
            "token_count, embedding) VALUES (:d, :r, 1, :o, 'stale', 1, CAST(:e AS vector))",
            d=doc_id,
            r=rev_id,
            o=ordinal,
            e=stale,
        )
    async with h.client(h.app()) as c:
        await h.deliver(c, job_id)
    chunks = await h.chunks(rev_id)
    assert len(chunks) == 2 and all(c.text != "stale" for c in chunks)


async def test_ing10_duplicate_concurrent_deliveries_leave_one_runs_chunks(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())

    async def slow() -> None:
        await asyncio.sleep(0.4)

    h.provider.on_embed = slow
    async with h.client(h.app()) as c:
        responses = await asyncio.gather(*(h.deliver(c, job_id) for _ in range(5)))
    assert {r.status_code for r in responses} <= {200, 409}
    assert len(await h.chunks(rev_id)) == 2
    assert (await h.job(job_id)).attempts == 1


async def test_ing19_crash_after_publish_before_done_is_a_no_op_on_reclaim(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())
    async with h.client(h.app()) as c:
        await h.deliver(c, job_id)
        before = await h.revision(rev_id)
        # Simulate the worker dying after publication, before `done` was written.
        await h.sql(
            "UPDATE jobs SET status='processing', claimed_by='dead', "
            "lease_expires_at = now() - interval '1 minute' WHERE id = :i",
            i=job_id,
        )
        embeds = len(h.provider.texts)
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    assert len(h.provider.texts) == embeds  # nothing was re-embedded
    after = await h.revision(rev_id)
    assert (after.ready_at, after.status) == (before.ready_at, "ready")
    assert len(await h.chunks(rev_id)) == 2


# ----------------------------------------------------------------------------- races


async def test_ing17_delete_during_processing_publishes_nothing(h: Harness) -> None:
    doc_id, rev_id, job_id = await h.make(pdf_two_pages())

    async def delete_now() -> None:
        await h.sql("UPDATE documents SET deleted_at = now() WHERE id = :d", d=doc_id)

    h.provider.on_embed = delete_now
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    assert await h.chunks(rev_id) == []
    revision = await h.revision(rev_id)
    assert (revision.status, revision.failure_reason) == ("failed", "DOCUMENT_DELETED")
    doc = await h.one("SELECT current_revision_id FROM documents WHERE id = :d", d=doc_id)
    assert doc.current_revision_id is None
    assert (await h.job(job_id)).status == "failed" and (await h.job(job_id)).attempts == 1
    assert await h.visible() == []


async def test_ing17_document_deleted_before_the_job_starts_is_not_fetched(h: Harness) -> None:
    doc_id, rev_id, job_id = await h.make(pdf_two_pages())
    await h.sql("UPDATE documents SET deleted_at = now() WHERE id = :d", d=doc_id)
    reads: list[int] = []

    async def spy() -> None:
        reads.append(1)

    h.store.on_read = spy
    async with h.client(h.app()) as c:
        await h.deliver(c, job_id)
    assert reads == [] and await h.chunks(rev_id) == []
    assert (await h.revision(rev_id)).failure_reason == "DOCUMENT_DELETED"


async def test_ing15_stale_worker_cannot_publish_after_losing_the_claim(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())

    async def lose_claim() -> None:
        await h.sql(
            "UPDATE jobs SET claimed_by = 'usurper', attempts = 2, "
            "lease_expires_at = now() + interval '5 minutes' WHERE id = :i",
            i=job_id,
        )

    h.provider.on_embed = lose_claim
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 409
    assert await h.chunks(rev_id) == []
    revision = await h.revision(rev_id)
    assert revision.status == "processing" and revision.page_count is None
    job = await h.job(job_id)
    assert (job.status, job.claimed_by) == ("processing", "usurper")


async def test_ing15_stale_handler_phase_write_changes_nothing(h: Harness) -> None:
    """The claim is lost while fetching. The next phase write is fenced and writes nothing, and
    nothing later (chunks, publication) happens either."""
    _, rev_id, job_id = await h.make(pdf_two_pages())

    async def lose_claim() -> None:
        await h.sql(
            "UPDATE jobs SET claimed_by = 'usurper', attempts = 2, "
            "lease_expires_at = now() + interval '5 minutes' WHERE id = :i",
            i=job_id,
        )

    h.store.on_read = lose_claim
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 409
    revision = await h.revision(rev_id)
    assert (revision.status, revision.phase) == ("processing", "fetching")  # not "extracting"
    assert await h.chunks(rev_id) == []
    assert h.provider.texts == []  # it never got as far as embedding


def test_ing15_ingest_handler_writes_only_through_the_fenced_session() -> None:
    """Gate against a forgotten fence: the handler module opens no transaction of its own."""
    import inspect

    import knowserve_worker.ingest as ingest

    source = inspect.getsource(ingest)
    assert ".begin()" not in source and "ctx.fenced_session()" in source


# ----------------------------------------------------------------------------- reindex mode (Q8)


async def test_ing17_reindex_writes_chunks_and_identity_and_leaves_everything_else(
    h: Harness,
) -> None:
    doc_id, rev_id, job_id = await h.make(pdf_two_pages(), status="ready")
    before_rev = await h.revision(rev_id)
    before_doc = await h.one("SELECT * FROM documents WHERE id = :d", d=doc_id)
    seen: list[list[uuid.UUID]] = []

    async def still_visible() -> None:
        seen.append(await h.visible())

    h.provider.on_embed = still_visible
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    assert seen == [[doc_id]] and await h.visible() == [doc_id]  # visible throughout

    after_rev = await h.revision(rev_id)
    for column in ("id", "document_id", "status", "phase", "page_count", "ready_at", "storage_key"):
        assert getattr(after_rev, column) == getattr(before_rev, column), column
    assert after_rev.embedding_model == "fake-embedding" and after_rev.index_identity
    after_doc = await h.one("SELECT * FROM documents WHERE id = :d", d=doc_id)
    assert after_doc.current_revision_id == before_doc.current_revision_id
    assert len(await h.chunks(rev_id)) == 2


async def test_ing17_second_reindex_run_changes_nothing(h: Harness) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages(), status="ready")
    async with h.client(h.app()) as c:
        await h.deliver(c, job_id)
        first_chunks = await h.chunks(rev_id)
        embeds = len(h.provider.texts)
        await h.sql(
            "UPDATE jobs SET status='queued', attempts=0, claimed_by=NULL WHERE id = :i", i=job_id
        )
        await h.deliver(c, job_id)
    assert len(h.provider.texts) == embeds  # not even re-embedded
    assert await h.chunks(rev_id) == first_chunks


@pytest.mark.parametrize("pdf", [pdf_image_only(), pdf_corrupt(), None])
async def test_ing17_failed_reindex_never_fails_a_ready_revision(
    h: Harness, pdf: bytes | None
) -> None:
    doc_id, rev_id, job_id = await h.make(pdf, status="ready")
    async with h.client(h.app(job_max_attempts=1)) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    assert (await h.job(job_id)).status == "failed"
    revision = await h.revision(rev_id)
    assert (revision.status, revision.failure_reason) == ("ready", None)
    assert await h.chunks(rev_id) == [] and await h.visible() == [doc_id]


async def test_ing17_reindex_of_a_deleted_document_does_nothing(h: Harness) -> None:
    doc_id, rev_id, job_id = await h.make(pdf_two_pages(), status="ready")
    await h.sql("UPDATE documents SET deleted_at = now() WHERE id = :d", d=doc_id)
    async with h.client(h.app()) as c:
        response = await h.deliver(c, job_id)
    assert response.json() == {"result": "done"}
    assert await h.chunks(rev_id) == []
    assert (await h.revision(rev_id)).status == "ready"


# ----------------------------------------------------------------------------- hygiene


async def test_mon05_logs_carry_no_document_text_keys_or_vectors(
    h: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    _, rev_id, job_id = await h.make(pdf_two_pages())
    key = (await h.revision(rev_id)).storage_key
    async with h.client(h.app()) as c:
        await h.deliver(c, job_id)
    bad_id, bad_rev, bad_job = await h.make(pdf_image_only())
    async with h.client(h.app()) as c:
        await h.deliver(c, bad_job)
    logged = capsys.readouterr().out
    for secret in ("twenty days", "Expenses are reimbursed", key, "0.0442"):
        assert secret not in logged
    assert str(rev_id) in logged  # ids are fine
