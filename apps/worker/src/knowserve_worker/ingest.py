"""The ``ingest_revision`` job handler (M3-02b; ING-02, 05, 07, 09, 10, 15, 17, 18, 19, 23).

One attempt runs these stages from the start (no checkpoints, OPEN-31 D9) and sets the revision
``phase`` before each: ``fetching``, ``extracting``, ``chunking``, ``embedding``, ``publishing``.
Nothing is written to ``document_chunks`` until every batch has embedded, and publication is one
transaction (fence, deletion check, chunks, revision ``ready``, current pointer, index identity).

Reindex mode (OPEN-31 D4): for a revision that is already ``ready`` and has no chunks the handler
only writes the chunks and the index identity. Status, phase, page count, current pointer and ids
stay as they are, and a failure never fails the revision (the terminal hook skips ``ready``
revisions). A ``ready`` revision that already has chunks is left alone, so a second run, or a
reclaim after a crash between publication and the job's ``done``, changes nothing.

Privacy: logs and errors carry ids, phases and counts only. No document text, chunk text, storage
key or vector is ever logged, and extraction detail strings are not copied into log lines.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.chunking import Chunk, chunk_pages
from knowserve_core.embeddings import EmbeddingError, EmbeddingProvider
from knowserve_core.ingestion_contract import FailureCode, build_index_identity
from knowserve_core.job_hooks import NonRetryableJobError, RetryableJobError
from knowserve_core.models import DocumentChunk
from knowserve_core.object_store import ObjectNotFound, ObjectStore, ObjectStoreError
from knowserve_core.pdf_extraction import (
    ExtractedDocument,
    PdfExtractionError,
    extract_pdf_async,
)
from knowserve_core.settings import Settings

logger = logging.getLogger("knowserve.worker.ingest")

Factory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class _Revision:
    id: uuid.UUID
    document_id: uuid.UUID
    storage_key: str
    status: str
    deleted: bool
    chunk_count: int


_LOAD = text(
    """
    SELECT r.id, r.document_id, r.storage_key, r.status, d.deleted_at IS NOT NULL AS deleted,
           (SELECT count(*) FROM document_chunks c WHERE c.revision_id = r.id) AS chunk_count
    FROM document_revisions r JOIN documents d ON d.id = r.document_id
    WHERE r.job_id = :job_id
    """
)
_PHASE = text(
    """
    UPDATE document_revisions
    SET status = 'processing', phase = :phase, failure_reason = NULL
    WHERE id = :id AND status <> 'ready'
    """
)
_LOCK_DOCUMENT = text(
    "SELECT deleted_at IS NOT NULL AS deleted FROM documents WHERE id = :id FOR UPDATE"
)
_DELETE_CHUNKS = text("DELETE FROM document_chunks WHERE revision_id = :id")
_COUNT_CHUNKS = text("SELECT count(*) FROM document_chunks WHERE revision_id = :id")
_PUBLISH_REVISION = text(
    """
    UPDATE document_revisions
    SET status = 'ready', phase = NULL, failure_reason = NULL, page_count = :page_count,
        ready_at = now(), embedding_model = :model, index_identity = :identity
    WHERE id = :id
    """
)
_REINDEX_REVISION = text(
    "UPDATE document_revisions SET embedding_model = :model, index_identity = :identity "
    "WHERE id = :id"
)
_SET_POINTER = text(
    """
    UPDATE documents SET current_revision_id = :revision_id, updated_at = now()
    WHERE id = :id AND deleted_at IS NULL
      AND (current_revision_id IS NULL OR current_revision_id = :revision_id)
    """
)


class IngestHandler:
    def __init__(
        self,
        factory: Factory,
        store: ObjectStore,
        provider: EmbeddingProvider,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._store = store
        self._provider = provider
        self._settings = settings

    async def __call__(self, ctx: Any) -> None:
        revision = await self._load(ctx)
        reindex = revision.status == "ready"
        log = {"job_id": str(ctx.job_id), "revision_id": str(revision.id)}
        if reindex and (revision.chunk_count > 0 or revision.deleted):
            logger.info("ingest: nothing to do", extra=log)
            return
        if revision.deleted:
            raise NonRetryableJobError(FailureCode.DOCUMENT_DELETED)

        await self._phase(ctx, revision, "fetching", reindex)
        data = await self._fetch(revision)

        await self._phase(ctx, revision, "extracting", reindex)
        document = await self._extract(data)
        del data

        await self._phase(ctx, revision, "chunking", reindex)
        chunks = await self._chunk(document)

        await self._phase(ctx, revision, "embedding", reindex)
        vectors = await self._embed(chunks)

        await self._phase(ctx, revision, "publishing", reindex)
        await self._publish(ctx, revision, document, chunks, vectors, reindex)
        logger.info("ingest: published", extra={**log, "chunks": len(chunks), "reindex": reindex})

    # ------------------------------------------------------------------ stages

    async def _load(self, ctx: Any) -> _Revision:
        async with self._factory() as session:
            row = (await session.execute(_LOAD, {"job_id": ctx.job_id})).first()
        if row is None:
            # A signed job with no revision is a data problem; retrying cannot fix it.
            logger.error("ingest job has no revision", extra={"job_id": str(ctx.job_id)})
            raise NonRetryableJobError(FailureCode.INTERNAL_ERROR)
        return _Revision(
            row.id, row.document_id, row.storage_key, row.status, row.deleted, row.chunk_count
        )

    async def _phase(self, ctx: Any, revision: _Revision, phase: str, reindex: bool) -> None:
        """Fenced phase write. Reindex mode leaves the ready revision untouched."""
        async with ctx.fenced_session() as session:
            if not reindex:
                await session.execute(_PHASE, {"id": revision.id, "phase": phase})

    async def _fetch(self, revision: _Revision) -> bytes:
        limit = self._settings.upload_max_pdf_bytes
        parts: list[bytes] = []
        size = 0
        try:
            async for part in self._store.stream(revision.storage_key):
                size += len(part)
                if size > limit:
                    raise NonRetryableJobError(FailureCode.INVALID_PDF)
                parts.append(part)
        except ObjectNotFound:
            # The object is written before the rows that point at it, so a missing object will
            # not appear on a retry. No code fits exactly; INVALID_PDF tells the Admin to upload
            # a different file, which is the fix.
            raise NonRetryableJobError(FailureCode.INVALID_PDF) from None
        except ObjectStoreError:
            raise RetryableJobError(FailureCode.STORAGE_UNAVAILABLE) from None
        return b"".join(parts)

    async def _extract(self, data: bytes) -> ExtractedDocument:
        try:
            return await extract_pdf_async(
                data,
                timeout_seconds=self._settings.pdf_extraction_timeout_seconds,
                max_pages=self._settings.upload_max_pdf_pages,
            )
        except PdfExtractionError as exc:
            logger.warning("extraction failed", extra={"failure_code": exc.code.value})
            if exc.retryable:
                raise RetryableJobError(exc.code) from None
            raise NonRetryableJobError(exc.code) from None

    async def _chunk(self, document: ExtractedDocument) -> list[Chunk]:
        chunks = await asyncio.to_thread(
            chunk_pages,
            document.pages,
            chunk_size_tokens=self._settings.chunk_size_tokens,
            chunk_overlap_tokens=self._settings.chunk_overlap_tokens,
        )
        if not chunks:
            raise NonRetryableJobError(FailureCode.NO_EXTRACTABLE_TEXT)
        return chunks

    async def _embed(self, chunks: list[Chunk]) -> list[list[float]]:
        # The provider batches and retries; nothing is written until all vectors exist.
        try:
            vectors = await self._provider.embed([c.text for c in chunks])
        except EmbeddingError:
            raise RetryableJobError(FailureCode.EMBEDDING_FAILED) from None
        if len(vectors) != len(chunks) or any(len(v) != self._provider.dimensions for v in vectors):
            raise RetryableJobError(FailureCode.EMBEDDING_FAILED)
        return vectors

    async def _publish(
        self,
        ctx: Any,
        revision: _Revision,
        document: ExtractedDocument,
        chunks: list[Chunk],
        vectors: list[list[float]],
        reindex: bool,
    ) -> None:
        identity = build_index_identity(
            self._provider.model,
            self._provider.dimensions,
            self._settings.chunk_size_tokens,
            self._settings.chunk_overlap_tokens,
        )
        params = {"id": revision.id, "model": self._provider.model, "identity": identity}
        # 1. Still ours? The fence locks the job row, so a reclaim waits for this transaction.
        async with ctx.fenced_session() as session:
            # 2. Lock the document row: a soft delete either landed before this (we stop) or
            #    waits until we commit (D7).
            deleted = (await session.execute(_LOCK_DOCUMENT, {"id": revision.document_id})).scalar()
            if deleted:
                if reindex:
                    return
                raise NonRetryableJobError(FailureCode.DOCUMENT_DELETED)
            if reindex:
                existing = (await session.execute(_COUNT_CHUNKS, {"id": revision.id})).scalar_one()
                if existing:
                    return  # another run already wrote them
            else:
                await session.execute(_DELETE_CHUNKS, {"id": revision.id})
            session.add_all(
                DocumentChunk(
                    document_id=revision.document_id,
                    revision_id=revision.id,
                    page=chunk.page_number,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            )
            await session.flush()
            if reindex:
                await session.execute(_REINDEX_REVISION, params)
            else:
                await session.execute(
                    _PUBLISH_REVISION, {**params, "page_count": document.page_count}
                )
                pointer = await session.execute(
                    _SET_POINTER, {"id": revision.document_id, "revision_id": revision.id}
                )
                if pointer.rowcount != 1:  # type: ignore[attr-defined]
                    # Another revision is already current (replacing a ready document is M5).
                    logger.warning(
                        "ingest: current revision left unchanged",
                        extra={
                            "job_id": str(ctx.job_id),
                            "document_id": str(revision.document_id),
                            "revision_id": str(revision.id),
                        },
                    )


Handler = Callable[[Any], Awaitable[None]]


def lazy_ingest_handler(
    factory: Factory,
    settings: Settings,
    store_builder: Callable[[], ObjectStore],
    provider_builder: Callable[[], EmbeddingProvider],
) -> Handler:
    """Build the store and provider on the first job, so a Worker without R2 or OpenAI settings
    (and every non-ingest job) still starts. A configuration error is logged without its
    values and fails the attempt with a retryable code, so it ends ``failed`` with a Retry button
    instead of hanging."""
    built: list[IngestHandler] = []

    async def handler(ctx: Any) -> None:
        if not built:
            try:
                built.append(IngestHandler(factory, store_builder(), provider_builder(), settings))
            except (ValueError, RuntimeError) as exc:
                logger.error("ingest is not configured", extra={"reason": type(exc).__name__})
                raise RetryableJobError(FailureCode.INTERNAL_ERROR) from None
        await built[0](ctx)

    return handler
