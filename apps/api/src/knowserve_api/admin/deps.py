"""Shared dependencies of the Admin routes (M3-01)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends

from knowserve_core.documents_access import parse_document_id
from knowserve_core.identity import Identity
from knowserve_core.ingestion_contract import AdminErrorCode, admin_error
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from ..auth.deps import get_settings_dep, require_csrf


async def require_admin_csrf(identity: Annotated[Identity, Depends(require_csrf)]) -> Identity:
    """Admin mutations: a session (401), then Origin and the CSRF token, then the Admin role (403).
    Every Admin POST, PATCH and DELETE uses this, multipart ones included (AUTH-14, ADM-01)."""
    if identity.kind != "admin":
        raise AppError(403, "FORBIDDEN", "Forbidden")
    return identity


async def require_uploads_enabled(settings: Annotated[Settings, Depends(get_settings_dep)]) -> None:
    """Routes that produce new uploads answer 503 ``UPLOADS_DISABLED`` while
    ``KS_UPLOADS_ENABLED`` is false (OPEN-31 D14). Reads, access changes, delete and retry do not
    use this, and running jobs are never cancelled."""
    if not settings.uploads_enabled:
        raise AppError(*admin_error(AdminErrorCode.UPLOADS_DISABLED))


async def admin_document_id(document_id: str) -> uuid.UUID:
    """The ``{document_id}`` path value. A malformed id is the same 404 ``DOCUMENT_NOT_FOUND`` as
    an unknown or deleted one (Q7, OPEN-28). Declare it after the auth dependency in a route
    signature: FastAPI resolves dependencies in order, so 401 and 403 come first."""
    return parse_document_id(document_id)


AdminDocumentId = Annotated[uuid.UUID, Depends(admin_document_id)]
