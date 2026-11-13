"""Admin document management: list, detail, access, delete, retry (M3-05a). Stubs until then."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from knowserve_core.identity import Identity

from ..auth.deps import require_admin
from ..schemas import not_implemented
from .deps import require_admin_csrf
from .schemas import (
    AccessUpdateRequest,
    AdminDocumentList,
    AdminDocumentOut,
    RevisionStatus,
    admin_error_responses,
)

router = APIRouter(tags=["admin"])


@router.get(
    "/documents",
    response_model=AdminDocumentList,
    responses=admin_error_responses(401, 403, 422),
)
async def admin_list_documents(
    _: Annotated[Identity, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: RevisionStatus | None = None,
) -> AdminDocumentList:
    """Every non-deleted document with its latest revision status (ADM-02, ADM-09). Needs no
    active department (SEC-17 applies to the user routes, not here). Order: newest first."""
    raise not_implemented()


@router.get(
    "/documents/{document_id}",
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404),
)
async def admin_get_document(
    document_id: uuid.UUID, _: Annotated[Identity, Depends(require_admin)]
) -> AdminDocumentOut:
    raise not_implemented()


@router.patch(
    "/documents/{document_id}/access",
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404, 422),
)
async def update_access(
    document_id: uuid.UUID,
    body: AccessUpdateRequest,
    _: Annotated[Identity, Depends(require_admin_csrf)],
) -> AdminDocumentOut:
    """Replace the allowed departments in one update. No job, no re-embedding (ADM-07)."""
    raise not_implemented()


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    responses=admin_error_responses(401, 403, 404),
)
async def delete_document(
    document_id: uuid.UUID, _: Annotated[Identity, Depends(require_admin_csrf)]
) -> None:
    """Soft delete only (ADM-08, OPEN-31 D7). Objects and chunks stay until M5."""
    raise not_implemented()


@router.post(
    "/documents/{document_id}/retry",
    status_code=202,
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404, 409),
)
async def retry_document(
    document_id: uuid.UUID, _: Annotated[Identity, Depends(require_admin_csrf)]
) -> AdminDocumentOut:
    """Manual retry (ADM-16). 409 ``DOCUMENT_NOT_RETRYABLE`` for a done or actively leased job."""
    raise not_implemented()
