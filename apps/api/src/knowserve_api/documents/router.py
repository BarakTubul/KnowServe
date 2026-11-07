"""Document library routes (M2). The list is real (M2-02); metadata and bytes are 501 until M2-03.

Order of checks (docs/milestones/M2/plan.md 6.3): session (401), active department (409), then the
document query (404 ``DOCUMENT_NOT_FOUND`` with one fixed body for every cause).
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core.documents_access import visible_documents
from knowserve_core.identity import Identity
from knowserve_core.models import Department, Document
from knowserve_core.web import AppError

from ..auth.deps import get_db, require_active_department
from ..schemas import (
    DocumentListItem,
    DocumentListResponse,
    DocumentMetadata,
    DocumentOwnerDepartment,
    error_responses,
    not_implemented,
)

router = APIRouter(tags=["documents"])

DOCUMENT_LIMIT_DEFAULT = 20
DOCUMENT_LIMIT_MAX = 50


def _invalid(message: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message)


def encode_cursor(created_at: datetime, document_id: uuid.UUID) -> str:
    """Opaque, URL-safe position (last ``created_at``, ``id``); carries no document data."""
    raw = json.dumps([created_at.isoformat(), str(document_id)], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Strict inverse of ``encode_cursor``; anything else is a controlled 422, never a 500."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if not (
            isinstance(data, list) and len(data) == 2 and all(isinstance(x, str) for x in data)
        ):
            raise ValueError
        created_at = datetime.fromisoformat(data[0])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, uuid.UUID(data[1])
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise _invalid("Invalid cursor") from None


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get(
    "/v1/documents",
    response_model=DocumentListResponse,
    responses=error_responses(401, 409, 422),
)
async def list_documents(
    identity: Annotated[Identity, Depends(require_active_department)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[
        str | None, Query(max_length=200, description="Title or filename substring")
    ] = None,
    owner_department_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=DOCUMENT_LIMIT_MAX)] = DOCUMENT_LIMIT_DEFAULT,
    cursor: Annotated[str | None, Query(max_length=512, description="Opaque")] = None,
) -> DocumentListResponse:
    # The department comes from the session only (SEC-06); filters and the cursor narrow the
    # predicate and run before the limit, so paging never changes what is visible.
    assert identity.active_department_id is not None
    owner_id = None
    if owner_department_id is not None:
        try:
            owner_id = uuid.UUID(owner_department_id)
        except ValueError:
            raise _invalid("Invalid owner_department_id") from None
    position = decode_cursor(cursor) if cursor else None

    stmt = (
        visible_documents(identity.active_department_id)
        .join(Department, Department.id == Document.owner_department_id)
        .add_columns(Department.name)
    )
    if owner_id is not None:
        stmt = stmt.where(Document.owner_department_id == owner_id)
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
    rows = (await db.execute(stmt)).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    items = [
        DocumentListItem(
            id=doc.id,
            title=doc.title,
            filename=doc.filename,
            owner_department=DocumentOwnerDepartment(id=doc.owner_department_id, name=owner_name),
            page_count=rev.page_count or 0,
        )
        for doc, rev, owner_name in page
    ]
    next_cursor = encode_cursor(page[-1][0].created_at, page[-1][0].id) if has_more else None
    return DocumentListResponse(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/v1/documents/{document_id}",
    response_model=DocumentMetadata,
    responses=error_responses(401, 404, 409),
)
async def get_document(
    document_id: str,
    _: Annotated[Identity, Depends(require_active_department)],
    page: Annotated[int | None, Query(ge=1)] = None,
) -> DocumentMetadata:
    raise not_implemented()


@router.get(
    "/v1/documents/{document_id}/content",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The PDF"},
        206: {"content": {"application/pdf": {}}, "description": "A single byte range"},
        **error_responses(401, 404, 409, 416),
    },
)
async def get_document_content(
    document_id: str,
    _: Annotated[Identity, Depends(require_active_department)],
    range_header: Annotated[
        str | None,
        Header(alias="Range", description="A single byte range, for example `bytes=0-1023`"),
    ] = None,
    if_range: Annotated[
        str | None,
        Header(
            alias="If-Range", description="Validator for `Range`; mismatch returns the full body"
        ),
    ] = None,
) -> Response:
    raise not_implemented()
