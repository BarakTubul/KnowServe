"""Document status stream, Admin only (M3-05a). Stub until then."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from knowserve_core.identity import Identity

from ..auth.deps import require_admin
from ..schemas import not_implemented
from .deps import AdminDocumentId
from .schemas import admin_error_responses

router = APIRouter(tags=["admin"])

_SSE_RESPONSE = {
    200: {
        "description": (
            "Server-sent events for one document. `event: status` carries "
            "DocumentProcessingStatus as JSON, sent on connect and on every change. A comment "
            "line keeps the connection open. `event: end` carries "
            '`{"reason": "terminal" | "timeout"}`; on "timeout" the client reconnects.'
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


@router.get(
    "/documents/{document_id}/events",
    responses={**_SSE_RESPONSE, **admin_error_responses(401, 403, 404)},
)
async def document_events(
    _: Annotated[Identity, Depends(require_admin)], document_id: AdminDocumentId
) -> None:
    raise not_implemented()
