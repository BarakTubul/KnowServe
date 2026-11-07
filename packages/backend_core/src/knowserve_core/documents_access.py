"""The document visibility predicate and the uniform 404 (SEC-07, SEC-02, DOC-05, Q7).

``visible_documents`` is the single place that decides what a department may see. The library
list, the metadata route, the bytes route and (M4) the retriever all start from it, so SEC-08 can
filter in SQL before similarity. Callers pass the department from the session, never from the
request (SEC-06).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from .models import Document, DocumentDepartmentAccess, DocumentRevision
from .web import AppError

DOCUMENT_NOT_FOUND_CODE = "DOCUMENT_NOT_FOUND"
# One fixed message for every cause: forbidden, unknown, deleted, not ready, malformed id.
DOCUMENT_NOT_FOUND_MESSAGE = "This document is not available."


def document_not_found() -> AppError:
    """The only 404 the document routes may raise."""
    return AppError(404, DOCUMENT_NOT_FOUND_CODE, DOCUMENT_NOT_FOUND_MESSAGE)


def parse_document_id(raw: str) -> uuid.UUID:
    """Malformed ids get the same 404 as unknown ones (Q7)."""
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise document_not_found() from None


def visible_documents(department_id: uuid.UUID) -> Select[Document, DocumentRevision]:
    """Documents the department may see, with their current ready revision.

    Visible means: not soft-deleted, current revision set and ``ready``, and an access row for
    ``department_id``. Extend the returned select (filters, order, limit) but never replace it.
    """
    return (
        select(Document, DocumentRevision)
        .join(
            DocumentRevision,
            (DocumentRevision.id == Document.current_revision_id)
            & (DocumentRevision.document_id == Document.id),
        )
        .join(
            DocumentDepartmentAccess,
            DocumentDepartmentAccess.document_id == Document.id,
        )
        .where(
            Document.deleted_at.is_(None),
            DocumentRevision.status == "ready",
            DocumentDepartmentAccess.department_id == department_id,
        )
    )
