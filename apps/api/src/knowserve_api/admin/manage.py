"""Admin document management: list, detail, access, delete, retry (M3-05a).

Every route needs a session (401) and the Admin role (403); mutations also need the Origin and the
CSRF token. The document id is checked after those, and a malformed, unknown or deleted id is the
same 404 ``DOCUMENT_NOT_FOUND``. Nothing here depends on the active department (SEC-17).

Audit rows (ADM-17) carry ids and counts only: never a file name, title, text or storage key.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core import audit
from knowserve_core.documents_access import document_not_found
from knowserve_core.identity import Identity
from knowserve_core.ingestion_contract import AdminErrorCode, admin_error
from knowserve_core.job_recovery import JobNotFoundError, NotRetryableError, retry_job
from knowserve_core.models import (
    Department,
    Document,
    DocumentDepartmentAccess,
    DocumentRevision,
)
from knowserve_core.qstash import Publisher
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from ..auth.deps import get_db, require_admin
from ..documents.router import decode_cursor, encode_cursor
from .deps import AdminDocumentId, require_admin_csrf
from .document_views import (
    JobWindows,
    admin_documents,
    build_outs,
    load_out,
)
from .schemas import (
    AccessUpdateRequest,
    AdminDocumentList,
    AdminDocumentOut,
    RevisionStatus,
    admin_error_responses,
)

router = APIRouter(tags=["admin"])

AUDIT_ACCESS_CHANGED = "admin.document.access_changed"
AUDIT_DELETED = "admin.document.deleted"
AUDIT_RETRIED = "admin.document.retried"


def _factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _publisher(request: Request) -> Publisher:
    return request.app.state.publisher


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _out_or_404(
    request: Request, db: AsyncSession, document_id: uuid.UUID
) -> AdminDocumentOut:
    out = await load_out(
        db, _factory(request), document_id, JobWindows.from_settings(_settings(request))
    )
    if out is None:
        raise document_not_found()
    return out


@router.get(
    "/documents",
    response_model=AdminDocumentList,
    responses=admin_error_responses(401, 403, 422),
)
async def admin_list_documents(
    request: Request,
    _: Annotated[Identity, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: RevisionStatus | None = None,
) -> AdminDocumentList:
    """Every non-deleted document with its latest revision status (ADM-02, ADM-09). Needs no
    active department (SEC-17 applies to the user routes, not here). Order: newest first."""
    position = decode_cursor(cursor) if cursor else None
    stmt = admin_documents()
    if status is not None:
        stmt = stmt.where(DocumentRevision.status == status)
    if q and q.strip():
        pattern = f"%{_like_escape(q.strip())}%"
        stmt = stmt.where(
            or_(
                Document.title.ilike(pattern, escape="\\"),
                Document.filename.ilike(pattern, escape="\\"),
            )
        )
    if position is not None:
        last_at, last_id = position
        stmt = stmt.where(
            or_(
                Document.created_at < last_at,
                and_(Document.created_at == last_at, Document.id < last_id),
            )
        )
    stmt = stmt.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
    rows = [(d, r) for d, r in (await db.execute(stmt)).all()]

    has_more = len(rows) > limit
    page = rows[:limit]
    items = await build_outs(
        db, _factory(request), page, JobWindows.from_settings(_settings(request))
    )
    next_cursor = encode_cursor(page[-1][0].created_at, page[-1][0].id) if has_more else None
    return AdminDocumentList(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/documents/{document_id}",
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404),
)
async def admin_get_document(
    request: Request,
    _: Annotated[Identity, Depends(require_admin)],
    document_id: AdminDocumentId,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminDocumentOut:
    return await _out_or_404(request, db, document_id)


@router.patch(
    "/documents/{document_id}/access",
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404, 422),
)
async def update_access(
    request: Request,
    identity: Annotated[Identity, Depends(require_admin_csrf)],
    document_id: AdminDocumentId,
    body: AccessUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminDocumentOut:
    """Replace the allowed departments in one update. No job, no re-embedding (ADM-07).

    The list is exactly what the Admin sent: an empty list is rejected and nothing is derived
    from the owner department or from the previous access (ADM-05, SEC-04, SEC-05)."""
    wanted = set(body.allowed_department_ids)
    async with _factory(request)() as session, session.begin():
        # Locking the row serializes this against a concurrent delete, so a deleted document is
        # never changed and the audit row always describes what happened.
        document = (
            await session.execute(
                select(Document)
                .where(Document.id == document_id, Document.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if document is None:
            raise document_not_found()
        if not wanted:
            raise AppError(*admin_error(AdminErrorCode.ALLOWED_DEPARTMENTS_EMPTY))
        known = set(
            (
                await session.execute(select(Department.id).where(Department.id.in_(wanted)))
            ).scalars()
        )
        if known != wanted:
            raise AppError(*admin_error(AdminErrorCode.UNKNOWN_DEPARTMENT))
        current = set(
            (
                await session.execute(
                    select(DocumentDepartmentAccess.department_id).where(
                        DocumentDepartmentAccess.document_id == document_id
                    )
                )
            ).scalars()
        )
        removed = current - wanted
        added = wanted - current
        if removed:
            await session.execute(
                delete(DocumentDepartmentAccess).where(
                    DocumentDepartmentAccess.document_id == document_id,
                    DocumentDepartmentAccess.department_id.in_(removed),
                )
            )
        for department_id in added:
            session.add(
                DocumentDepartmentAccess(document_id=document_id, department_id=department_id)
            )
        await session.execute(
            update(Document).where(Document.id == document_id).values(updated_at=func.now())
        )
        await audit.record(
            session,
            AUDIT_ACCESS_CHANGED,
            user_id=identity.user_id,
            document_id=str(document_id),
            allowed_count=len(wanted),
            added_department_ids=sorted(str(d) for d in added),
            removed_department_ids=sorted(str(d) for d in removed),
        )
    return await _out_or_404(request, db, document_id)


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    responses=admin_error_responses(401, 403, 404),
)
async def delete_document(
    request: Request,
    identity: Annotated[Identity, Depends(require_admin_csrf)],
    document_id: AdminDocumentId,
) -> None:
    """Soft delete only (ADM-08, OPEN-31 D7): ``deleted_at`` is set and nothing else changes.

    No row is removed, no job is created, objects and chunks stay until M5. ``deleted_at`` keeps
    the first value, so a repeated DELETE changes nothing and writes no second audit row; it
    answers 404 like any deleted id (Q7)."""
    async with _factory(request)() as session, session.begin():
        deleted = (
            await session.execute(
                update(Document)
                .where(Document.id == document_id, Document.deleted_at.is_(None))
                .values(deleted_at=func.now(), updated_at=func.now())
                .returning(Document.id)
            )
        ).first()
        if deleted is None:
            raise document_not_found()
        await audit.record(
            session, AUDIT_DELETED, user_id=identity.user_id, document_id=str(document_id)
        )


@router.post(
    "/documents/{document_id}/retry",
    status_code=202,
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404, 409),
)
async def retry_document(
    request: Request,
    identity: Annotated[Identity, Depends(require_admin_csrf)],
    document_id: AdminDocumentId,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminDocumentOut:
    """Manual retry (ADM-16). 409 ``DOCUMENT_NOT_RETRYABLE`` for a ready revision, a done job or a
    job with an active lease.

    The retry itself is ``job_recovery.retry_job``: it republishes a lost outbox row or requeues
    the same job, never creates a second job, and repeats every guard inside the UPDATE that
    performs it, so of two concurrent retries one wins and the other gets 409."""
    factory = _factory(request)
    settings = _settings(request)
    windows = JobWindows.from_settings(settings)
    row = (await db.execute(admin_documents().where(Document.id == document_id))).first()
    if row is None:
        raise document_not_found()
    revision: DocumentRevision = row[1]
    revision_id, job_id = revision.id, revision.job_id
    # The latest revision's job is the only one that may be retried. A ready revision is done.
    if revision.status == "ready" or job_id is None:
        raise AppError(*admin_error(AdminErrorCode.DOCUMENT_NOT_RETRYABLE))
    try:
        result = await retry_job(
            factory,
            _publisher(request),
            job_id,
            grace_seconds=windows.grace_seconds,
            stuck_after_seconds=windows.stuck_after_seconds,
            publish_timeout=settings.publish_timeout_seconds,
        )
    except (JobNotFoundError, NotRetryableError):
        raise AppError(*admin_error(AdminErrorCode.DOCUMENT_NOT_RETRYABLE)) from None
    async with factory() as session, session.begin():
        await audit.record(
            session,
            AUDIT_RETRIED,
            user_id=identity.user_id,
            document_id=str(document_id),
            revision_id=str(revision_id),
            job_id=str(job_id),
            action=result.action,
            published=result.published,
        )
    # The identity lookup read this session before the retry; start from a clean snapshot.
    await db.rollback()
    return await _out_or_404(request, db, document_id)
