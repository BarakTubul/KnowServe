"""Replace the file of a failed document (M3-05b, ADM-18).

A replacement is a new revision with its own job under a new storage key; the failed revision and
its partial artifacts are left alone and can never become current (SEC-07). ``document_id``, the
owner and the access rows do not change. The storage put, the limits, the idempotency row, the
object cleanup and the publish belong to the creation service (``UploadService.execute``); this
module owns the precondition and the rows.

The precondition is checked twice. ``check_replaceable`` runs before anything is stored, so a
wrong state costs no object. ``apply`` repeats it inside the creating transaction under row locks
on the document and on the failed revision's job, so two requests with different keys cannot both
start an attempt, and a retry that already flipped the job makes the replacement a 409.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core import audit
from knowserve_core.documents_access import document_not_found
from knowserve_core.ingestion_contract import AdminErrorCode, Operation, admin_error
from knowserve_core.models import Document, DocumentRevision, Job
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from .creation import (
    IdempotencyScope,
    PreparedRevision,
    UploadOutcome,
    UploadService,
    add_revision_with_job,
    request_hash,
)
from .document_views import JobWindows, build_outs, latest_revision_id
from .schemas import AdminDocumentOut

AUDIT_REPLACED = "admin.document.replaced"


def not_replaceable() -> AppError:
    return AppError(*admin_error(AdminErrorCode.DOCUMENT_NOT_REPLACEABLE))


async def _latest_revision(
    session: AsyncSession, document_id: uuid.UUID
) -> DocumentRevision | None:
    return (
        await session.execute(
            select(DocumentRevision)
            .where(
                DocumentRevision.document_id == document_id,
                DocumentRevision.id == latest_revision_id(),
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _checked_state(
    session: AsyncSession, document_id: uuid.UUID, *, lock: bool
) -> tuple[Document, DocumentRevision]:
    """The non-deleted document and its latest revision, or 404. 409 unless the document has no
    current revision, its latest revision is ``failed`` and its job (if any) is too.

    With ``lock`` the failed revision's job row is locked first and the document row second, the
    order the Worker's publication uses (docs/contracts/jobs-outbox.md, "Lock order"), so the two
    cannot deadlock. The job is not known until the revision is read, so the revision is read
    once without a lock, the locks are taken, and the state is read again: if the latest revision
    changed in between (another replacement won), the request is a 409."""
    first = await _latest_revision(session, document_id)
    if lock and first is not None and first.job_id is not None:
        await session.execute(select(Job.id).where(Job.id == first.job_id).with_for_update())
    doc_stmt = select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    if lock:
        doc_stmt = doc_stmt.with_for_update()
    document = (await session.execute(doc_stmt)).scalar_one_or_none()
    if document is None:
        raise document_not_found()
    revision = await _latest_revision(session, document_id) if lock else first
    if (
        revision is None
        or (first is not None and revision.id != first.id)
        or document.current_revision_id is not None
        or revision.status != "failed"
    ):
        raise not_replaceable()
    if revision.job_id is not None:
        job_status = (
            await session.execute(select(Job.status).where(Job.id == revision.job_id))
        ).scalar()
        if job_status != "failed":
            raise not_replaceable()
    return document, revision


async def _check_before_storing(
    service: UploadService,
    factory: async_sessionmaker[AsyncSession],
    admin_id: uuid.UUID,
    document_id: uuid.UUID,
    idempotency_key: str,
) -> None:
    """404 or 409 before anything is stored. A key that already has a stored result skips the
    state check: ``execute`` replays it (or rejects a reused key) even though the document is no
    longer replaceable. Unknown and deleted ids stay 404 for a replay too."""
    async with factory() as session:
        if await service.lookup(admin_id, idempotency_key) is None:
            await _checked_state(session, document_id, lock=False)
            return
        exists = (
            await session.execute(
                select(Document.id).where(Document.id == document_id, Document.deleted_at.is_(None))
            )
        ).first()
    if exists is None:
        raise document_not_found()


async def replace_failed_document_file(
    *,
    service: UploadService,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    admin_id: uuid.UUID,
    document_id: uuid.UUID,
    idempotency_key: str,
    filename: str | None,
    data: bytes,
) -> UploadOutcome:
    await _check_before_storing(service, factory, admin_id, document_id, idempotency_key)
    label = service.validate_pdf_upload(filename, data)
    scope = IdempotencyScope(
        idempotency_key,
        Operation.REPLACE_DOCUMENT,
        request_hash(
            Operation.REPLACE_DOCUMENT,
            document_id=str(document_id),
            file_sha256=hashlib.sha256(data).hexdigest(),
            filename=label,
        ),
    )
    windows = JobWindows.from_settings(settings)

    async def apply(session: AsyncSession, prepared: PreparedRevision) -> AdminDocumentOut:
        document, previous = await _checked_state(session, document_id, lock=True)
        previous_id = previous.id
        revision = await add_revision_with_job(session, prepared)
        document.updated_at = prepared.now
        await session.flush()
        await audit.record(
            session,
            AUDIT_REPLACED,
            user_id=admin_id,
            document_id=str(document_id),
            previous_revision_id=str(previous_id),
            revision_id=str(prepared.revision_id),
            size_bytes=prepared.size_bytes,
        )
        return (await build_outs(session, factory, [(document, revision)], windows))[0]

    return await service.execute(
        admin_id=admin_id,
        scope=scope,
        document_id=document_id,
        data=data,
        apply=apply,
        count_new_document=False,
    )
