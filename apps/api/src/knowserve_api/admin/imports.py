"""ZIP import: preview and confirm (M3-04). Stubs until then.

Preview creates no row, object or job (ADM-12). Confirm receives the ZIP again and re-validates
everything (finding F1, ADM-11).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from knowserve_core.identity import Identity

from ..schemas import not_implemented
from .deps import require_admin_csrf, require_uploads_enabled
from .schemas import ImportConfirmResponse, ImportPreviewResponse, admin_error_responses
from .upload import IdempotencyKey

router = APIRouter(tags=["admin"])


@router.post(
    "/imports/preview",
    response_model=ImportPreviewResponse,
    responses=admin_error_responses(401, 403, 413, 422, 503),
)
async def preview_import(
    _: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    file: Annotated[UploadFile, File()],
) -> ImportPreviewResponse:
    raise not_implemented()


@router.post(
    "/imports/confirm",
    response_model=ImportConfirmResponse,
    responses=admin_error_responses(401, 403, 409, 413, 422, 429, 503),
)
async def confirm_import(
    _: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
) -> ImportConfirmResponse:
    """Partial success is a 200 with per-file results (ADM-14)."""
    raise not_implemented()
