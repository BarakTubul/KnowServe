"""Document library routes (M2). Contract stubs written in M2-01; 501 until M2-02 and M2-03.

Order of checks (docs/milestones/M2/plan.md 6.3): session (401), active department (409), then the
document query (404 ``DOCUMENT_NOT_FOUND`` with one fixed body for every cause).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from knowserve_core.identity import Identity

from ..auth.deps import require_active_department
from ..schemas import (
    DocumentListResponse,
    DocumentMetadata,
    error_responses,
    not_implemented,
)

router = APIRouter(tags=["documents"])

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
) -> Response:
    raise not_implemented()
