"""Document routes (M2). The list is a 501 stub until M2-02; metadata and bytes are M2-03.

Order of checks (docs/milestones/M2/plan.md 6.3): session (401), active department (409), then the
document query (404 ``DOCUMENT_NOT_FOUND`` with one fixed body for every cause).
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core.documents_access import (
    document_not_found,
    parse_document_id,
    visible_documents,
)
from knowserve_core.identity import Identity
from knowserve_core.models import Department, Document, DocumentRevision
from knowserve_core.object_store import (
    ByteRange,
    ObjectNotFound,
    ObjectStore,
    ObjectStoreError,
)
from knowserve_core.web import AppError

from ..auth.deps import get_db, require_active_department
from ..schemas import (
    DocumentListResponse,
    DocumentMetadata,
    DocumentOwnerDepartment,
    error_responses,
    not_implemented,
)

router = APIRouter(tags=["documents"])
logger = logging.getLogger("knowserve.documents")

DOCUMENT_LIMIT_DEFAULT = 20
DOCUMENT_LIMIT_MAX = 50


@router.get(
    "/v1/documents",
    response_model=DocumentListResponse,
    responses=error_responses(401, 409, 422),
)
async def list_documents(
    _: Annotated[Identity, Depends(require_active_department)],
    q: Annotated[
        str | None, Query(max_length=200, description="Title or filename substring")
    ] = None,
    owner_department_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=DOCUMENT_LIMIT_MAX)] = DOCUMENT_LIMIT_DEFAULT,
    cursor: Annotated[str | None, Query(max_length=512, description="Opaque")] = None,
) -> DocumentListResponse:
    raise not_implemented()


# --- shared lookup -------------------------------------------------------------------------------


@dataclass(frozen=True)
class VisibleDocument:
    document: Document
    revision: DocumentRevision
    owner_name: str


async def load_visible(db: AsyncSession, identity: Identity, raw_id: str) -> VisibleDocument:
    """The one lookup for metadata and bytes: parse, then ``visible_documents`` for the session's
    active department. Every failure is the same ``DOCUMENT_NOT_FOUND`` (SEC-02, DOC-05)."""
    document_id = parse_document_id(raw_id)
    assert identity.active_department_id is not None  # guaranteed by require_active_department
    stmt = (
        visible_documents(identity.active_department_id)
        .add_columns(Department.name)
        .join_from(Document, Department, Department.id == Document.owner_department_id)
        .where(Document.id == document_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise document_not_found()
    return VisibleDocument(document=row[0], revision=row[1], owner_name=row[2])


def get_object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store


@router.get(
    "/v1/documents/{document_id}",
    response_model=DocumentMetadata,
    responses=error_responses(401, 404, 409, 422),
)
async def get_document(
    document_id: str,
    identity: Annotated[Identity, Depends(require_active_department)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int | None, Query(ge=1)] = None,
) -> DocumentMetadata:
    found = await load_visible(db, identity, document_id)
    page_count = found.revision.page_count or 0
    # Only after the visibility lookup: a caller who cannot see the document learns nothing from
    # the page check (DOC-09).
    if page is not None and page > page_count:
        raise RequestValidationError(
            [
                {
                    "loc": ("query", "page"),
                    "msg": "page is outside the document",
                    "type": "value_error",
                }
            ]
        )
    doc = found.document
    return DocumentMetadata(
        id=doc.id,
        title=doc.title,
        filename=doc.filename,
        owner_department=DocumentOwnerDepartment(id=doc.owner_department_id, name=found.owner_name),
        page_count=page_count,
    )


# --- bytes ---------------------------------------------------------------------------------------

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]")


def safe_filename(name: str) -> str:
    """ASCII only, no path or quoting characters, never empty, always ends in ``.pdf``."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_FILENAME.sub("_", base).strip(" .") or "document"
    return cleaned if cleaned.lower().endswith(".pdf") else f"{cleaned}.pdf"


class RangeUnsatisfiable(Exception):
    pass


def resolve_range(header: str | None, size: int) -> ByteRange | None:
    """Single byte range against the object size (DOC-11, Q2).

    ``None`` means "serve the whole body": no header, or one that is not a single well-formed
    ``bytes=`` range (multiple ranges are unsupported and ignored, as RFC 9110 allows).
    Raises ``RangeUnsatisfiable`` for a well-formed range outside the object.
    """
    if header is None:
        return None
    match = _RANGE_RE.fullmatch(header.strip())
    if match is None:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:  # suffix: the last N bytes
        count = int(last)
        if count == 0 or size == 0:
            raise RangeUnsatisfiable
        return ByteRange(max(size - count, 0), size - 1)
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:
        return None  # invalid spec: ignore the header
    if start >= size:
        raise RangeUnsatisfiable
    return ByteRange(start, min(end, size - 1))


async def _body(store: ObjectStore, key: str, byte_range: ByteRange | None) -> AsyncIterator[bytes]:
    try:
        async for chunk in store.stream(key, byte_range):
            yield chunk
    except (ObjectNotFound, ObjectStoreError) as exc:
        # Headers are already sent; end the body early. The client sees a short read and retries.
        logger.error("document stream aborted", extra={"error_type": type(exc).__name__})


@router.get(
    "/v1/documents/{document_id}/content",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The PDF"},
        206: {"content": {"application/pdf": {}}, "description": "A single byte range"},
        **error_responses(401, 404, 409, 416, 503),
    },
)
async def get_document_content(
    document_id: str,
    identity: Annotated[Identity, Depends(require_active_department)],
    db: Annotated[AsyncSession, Depends(get_db)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
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
    # Authorization is evaluated on every request, including every range request (SEC-06, DOC-11).
    found = await load_visible(db, identity, document_id)
    key = found.revision.storage_key
    etag = f'"{found.revision.id}"'
    try:
        size = await store.size(key)
    except ObjectNotFound:
        logger.error("document bytes missing", extra={"document_id": str(found.document.id)})
        raise document_not_found() from None
    except ObjectStoreError:
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable") from None

    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="{safe_filename(found.document.filename)}"',
        "Accept-Ranges": "bytes",
        "ETag": etag,
    }
    # If-Range: honour Range only while the validator still matches this revision's strong ETag.
    use_range = range_header if if_range is None or if_range.strip() == etag else None
    try:
        byte_range = resolve_range(use_range, size)
    except RangeUnsatisfiable:
        raise AppError(
            416,
            "RANGE_NOT_SATISFIABLE",
            "The requested range cannot be served",
            headers={"Content-Range": f"bytes */{size}"},
        ) from None

    if byte_range is None:
        headers["Content-Length"] = str(size)
        status = 200
    else:
        headers["Content-Length"] = str(byte_range.length)
        headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{size}"
        status = 206
    return StreamingResponse(
        _body(store, key, byte_range),
        status_code=status,
        media_type="application/pdf",
        headers=headers,
    )
