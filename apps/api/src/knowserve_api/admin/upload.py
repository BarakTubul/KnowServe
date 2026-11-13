"""Single PDF upload (M3-03) and failed-document file replacement (M3-05b, still a stub).

The create route is thin: authorization and CSRF come from the dependencies, everything else is in
``creation.UploadService`` so the ZIP import and the replace route share one implementation.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from pydantic import BeforeValidator

from knowserve_core.identity import Identity
from knowserve_core.ingestion_contract import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_KEY_PATTERN,
    AdminErrorCode,
)
from knowserve_core.web import AppError

from ..schemas import not_implemented
from .creation import UploadService, get_upload_service
from .deps import AdminDocumentId, require_admin_csrf, require_uploads_enabled
from .schemas import AdminDocumentOut, admin_error_responses
from .validation import read_upload

router = APIRouter(tags=["admin"])

IdempotencyKey = Annotated[
    str, Header(alias=IDEMPOTENCY_KEY_HEADER, pattern=IDEMPOTENCY_KEY_PATTERN)
]


# The only fields the create route accepts. Anything else (status, ids, job or revision fields) is
# rejected, never silently ignored, so a client cannot believe it set them (mass assignment).
def _blank_values_are_no_departments(value: object) -> object:
    """A form cannot send an empty list; a client that sends the field with no value (``""``)
    means "none chosen", which is ``ALLOWED_DEPARTMENTS_EMPTY`` rather than a generic 422."""
    if isinstance(value, list):
        return [item for item in value if not (isinstance(item, str) and not item.strip())]
    if isinstance(value, str) and not value.strip():
        return []
    return value


AllowedDepartmentIds = Annotated[
    list[uuid.UUID] | None, BeforeValidator(_blank_values_are_no_departments), Form()
]

CREATE_FORM_FIELDS = frozenset({"file", "title", "owner_department_id", "allowed_department_ids"})


async def reject_unknown_form_fields(request: Request, allowed: frozenset[str]) -> None:
    form = await request.form()
    if not set(form.keys()) <= allowed:
        raise AppError(422, "VALIDATION_ERROR", "Unexpected field in the request")


@router.post(
    "/documents",
    status_code=202,
    response_model=AdminDocumentOut,
    responses=admin_error_responses(401, 403, 409, 413, 422, 429, 503),
)
async def create_document(
    request: Request,
    admin: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    service: Annotated[UploadService, Depends(get_upload_service)],
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    owner_department_id: Annotated[uuid.UUID, Form()],
    # A list field: send `allowed_department_ids` once per department. Optional in the schema so
    # the route can answer with the stable codes ALLOWED_DEPARTMENTS_MISSING and _EMPTY (ADM-05).
    allowed_department_ids: AllowedDepartmentIds = None,
) -> AdminDocumentOut:
    """Validate, store in R2, then write document, revision, access, job and outbox in one
    transaction (ADM-03). The response is 202: processing continues in the Worker."""
    await reject_unknown_form_fields(request, CREATE_FORM_FIELDS)
    data = await read_upload(
        file,
        request.app.state.settings.upload_max_pdf_bytes,
        AdminErrorCode.FILE_TOO_LARGE,
    )
    outcome = await service.create_document(
        admin_id=admin.user_id,
        idempotency_key=idempotency_key,
        filename=file.filename,
        data=data,
        title=title,
        owner_department_id=owner_department_id,
        allowed_department_ids=allowed_department_ids,
    )
    return outcome.document


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
