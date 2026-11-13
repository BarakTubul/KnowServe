"""Single PDF upload and failed-document file replacement (M3-03, M3-05b). Stubs until then."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile

from knowserve_core.identity import Identity
from knowserve_core.ingestion_contract import IDEMPOTENCY_KEY_HEADER, IDEMPOTENCY_KEY_PATTERN

from ..schemas import not_implemented
from .deps import AdminDocumentId, require_admin_csrf, require_uploads_enabled
from .schemas import AdminDocumentOut, admin_error_responses

router = APIRouter(tags=["admin"])

IdempotencyKey = Annotated[
    str, Header(alias=IDEMPOTENCY_KEY_HEADER, pattern=IDEMPOTENCY_KEY_PATTERN)
]


@router.post(
    "/documents",
    status_code=202,
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 409, 413, 422, 429, 503),
)
async def create_document(
    _: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    owner_department_id: Annotated[uuid.UUID, Form()],
    # A list field: send `allowed_department_ids` once per department. Optional in the schema so
    # the route can answer with the stable codes ALLOWED_DEPARTMENTS_MISSING and _EMPTY (ADM-05).
    allowed_department_ids: Annotated[list[uuid.UUID] | None, Form()] = None,
) -> AdminDocumentOut:
    """Validate, store in R2, then write document, revision, access, job and outbox in one
    transaction (ADM-03). The response is 202: processing continues in the Worker."""
    raise not_implemented()


@router.post(
    "/documents/{document_id}/replace",
    status_code=202,
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 404, 409, 413, 422, 429, 503),
)
async def replace_failed_document(
    _: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    document_id: AdminDocumentId,
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
) -> AdminDocumentOut:
    """Replace the file of a document with no current revision whose latest revision failed
    (ADM-18). 409 ``DOCUMENT_NOT_REPLACEABLE`` for any other state."""
    raise not_implemented()
