"""Admin document views: the one place that builds ``DocumentProcessingStatus`` (M3-05a).

The list, the detail, the access update, retry, the status stream and the replace route (M3-05b)
all answer from here, so the status of a document and what the Admin may do with it
(``can_retry``, ``can_replace``) are decided in one function and the frontend keeps no second
policy (ADM-16, ADM-18). Everything is read from the database: the latest revision of a document
(ADM-02), and for a revision that is not ready, the delivery state of its job
(``knowserve_core.job_recovery``).

Admin queries never go through ``visible_documents``; they exist only behind the Admin role and
never feed a user route (SEC-17, SEC-07).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.ingestion_contract import FailureCode, failure_message
from knowserve_core.job_recovery import JobView, get_job_view
from knowserve_core.models import (
    Department,
    Document,
    DocumentDepartmentAccess,
    DocumentRevision,
)
from knowserve_core.settings import Settings

from ..schemas import DepartmentOut
from .schemas import AdminDocumentOut, DocumentProcessingStatus

# Delivery states of a failed revision's job that mean "nothing is running": the Worker marked the
# job ``failed`` together with the revision (M3-AC06). Any other state means an attempt is queued,
# publishing or running, so the file must not be replaced under it (ADM-18).
_IDLE_JOB_STATES = frozenset({"failed"})


def latest_revision_id():  # type: ignore[no-untyped-def]
    """Correlated scalar subquery: the newest revision of ``documents`` (ADM-02 shows the latest
    revision, not the current one)."""
    return (
        select(DocumentRevision.id)
        .where(DocumentRevision.document_id == Document.id)
        .order_by(DocumentRevision.created_at.desc(), DocumentRevision.id.desc())
        .limit(1)
        .correlate(Document)
        .scalar_subquery()
    )


def admin_documents() -> Select[Document, DocumentRevision]:
    """Every non-deleted document with its latest revision, regardless of any department."""
    return (
        select(Document, DocumentRevision)
        .join(DocumentRevision, DocumentRevision.id == latest_revision_id())
        .where(Document.deleted_at.is_(None))
    )


@dataclass(frozen=True)
class JobWindows:
    """The two delivery thresholds ``job_recovery`` needs, from settings."""

    grace_seconds: int
    stuck_after_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> JobWindows:
        return cls(settings.publish_grace_seconds, settings.stuck_after_seconds)


async def load_job_view(
    factory: async_sessionmaker[AsyncSession], revision: DocumentRevision, windows: JobWindows
) -> JobView | None:
    """The delivery view of the revision's job. A ``ready`` revision has nothing to show."""
    if revision.status == "ready" or revision.job_id is None:
        return None
    return await get_job_view(
        factory,
        revision.job_id,
        grace_seconds=windows.grace_seconds,
        stuck_after_seconds=windows.stuck_after_seconds,
    )


def failure_code_of(revision: DocumentRevision) -> FailureCode | None:
    """The stored reason as a ``FailureCode``; an unknown stored value reads as INTERNAL_ERROR."""
    if revision.status != "failed":
        return None
    try:
        return FailureCode(revision.failure_reason)
    except ValueError:
        return FailureCode.INTERNAL_ERROR


def compute_actions(
    document: Document, revision: DocumentRevision, job: JobView | None
) -> tuple[bool, bool]:
    """``(can_retry, can_replace)``, the only action policy (ADM-16, ADM-18).

    * Retry: the latest revision is not ready and its job is in a state ``retry_job`` accepts
      (failed, or stuck, or a publish failure). A terminal reason such as ``NO_EXTRACTABLE_TEXT``
      still allows one attempt (FE-ADM-06); the UI shows Replace first for those.
    * Replace: the document has no current revision, its latest revision is ``failed`` and no job
      is active.

    Each mutation checks its own precondition again inside the operation, whatever these flags
    said when the screen loaded.
    """
    if document.deleted_at is not None:
        return False, False
    can_retry = (
        revision.status != "ready"
        and revision.job_id is not None
        and job is not None
        and job.retry_action is not None
    )
    can_replace = (
        document.current_revision_id is None
        and revision.status == "failed"
        and (job is None or job.delivery_state in _IDLE_JOB_STATES)
    )
    return can_retry, can_replace


def processing_status(
    document: Document, revision: DocumentRevision, job: JobView | None
) -> DocumentProcessingStatus:
    code = failure_code_of(revision)
    can_retry, can_replace = compute_actions(document, revision, job)
    return DocumentProcessingStatus(
        document_id=document.id,
        revision_id=revision.id,
        status=revision.status,  # type: ignore[arg-type]
        phase=revision.phase if revision.status == "processing" else None,  # type: ignore[arg-type]
        failure_code=code,
        failure_message=failure_message(code.value) if code else None,
        delivery_state=job.delivery_state if job else None,
        can_retry=can_retry,
        can_replace=can_replace,
    )


async def load_status(
    factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID, windows: JobWindows
) -> DocumentProcessingStatus | None:
    """The current status of one non-deleted document, or None. Used by every stream tick."""
    async with factory() as session:
        row = (await session.execute(admin_documents().where(Document.id == document_id))).first()
    if row is None:
        return None
    document, revision = row
    job = await load_job_view(factory, revision, windows)
    return processing_status(document, revision, job)


async def build_outs(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    rows: Sequence[tuple[Document, DocumentRevision]],
    windows: JobWindows,
) -> list[AdminDocumentOut]:
    """Full Admin documents for already-loaded ``(document, revision)`` rows, in order."""
    if not rows:
        return []
    ids = [document.id for document, _ in rows]
    departments = {
        d.id: DepartmentOut(id=d.id, slug=d.slug, name=d.name)
        for d in (await session.execute(select(Department).order_by(Department.position)))
        .scalars()
        .all()
    }
    allowed: dict[uuid.UUID, list[DepartmentOut]] = {document_id: [] for document_id in ids}
    access = (
        await session.execute(
            select(DocumentDepartmentAccess.document_id, Department.id)
            .join(Department, Department.id == DocumentDepartmentAccess.department_id)
            .where(DocumentDepartmentAccess.document_id.in_(ids))
            .order_by(Department.position)
        )
    ).all()
    for document_id, department_id in access:
        allowed[document_id].append(departments[department_id])

    outs: list[AdminDocumentOut] = []
    for document, revision in rows:
        job = await load_job_view(factory, revision, windows)
        status = processing_status(document, revision, job)
        outs.append(
            AdminDocumentOut(
                **status.model_dump(),
                title=document.title,
                filename=document.filename,
                owner_department=departments[document.owner_department_id],
                allowed_departments=allowed[document.id],
                page_count=revision.page_count,
                size_bytes=revision.size_bytes,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
        )
    return outs


async def load_out(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    windows: JobWindows,
) -> AdminDocumentOut | None:
    """One full Admin document (non-deleted), or None."""
    row = (
        await session.execute(
            admin_documents()
            .where(Document.id == document_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        return None
    return (await build_outs(session, factory, [(row[0], row[1])], windows))[0]
