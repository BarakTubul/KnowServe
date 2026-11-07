"""M1 request and response models: the shared API contract (docs/contracts/auth-session.md).

Owner-written in M1-01. Slices implement the routes behind these models; changing a model needs
Owner approval and regenerating ``docs/contracts/openapi.json`` (WF-03).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from knowserve_core.web import AppError, ErrorEnvelope


class DepartmentOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class IdentityResponse(BaseModel):
    """The current identity (AUTH-09). Returned by every session-creating endpoint too."""

    kind: Literal["demo", "registered", "admin"]
    user_id: uuid.UUID
    email: str | None = None
    display_name: str | None = None
    sign_in_provider: Literal["password", "google.com", "anonymous"]
    active_department: DepartmentOut | None = None
    expires_at: datetime
    # Per-session CSRF token; send it as X-CSRF-Token on every mutation (AUTH-14).
    csrf_token: str


class IdTokenRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=8192)


class DepartmentsResponse(BaseModel):
    departments: list[DepartmentOut]


class SetDepartmentRequest(BaseModel):
    department_id: uuid.UUID


class RevokeAllResponse(BaseModel):
    revoked: int


class AdminPingResponse(BaseModel):
    status: Literal["ok"]


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries that document the shared error envelope."""
    return {status: {"model": ErrorEnvelope} for status in statuses}


def not_implemented() -> AppError:
    """M1-01 stubs return this until the owning slice implements the route."""
    return AppError(501, "NOT_IMPLEMENTED", "This endpoint is not implemented yet")


# --- M2 documents (docs/milestones/M2/plan.md 6.3; Owner-written in M2-01) ----------------------


class DocumentOwnerDepartment(BaseModel):
    id: uuid.UUID
    name: str


class DocumentListItem(BaseModel):
    id: uuid.UUID
    title: str
    filename: str
    owner_department: DocumentOwnerDepartment
    page_count: int


class DocumentListResponse(BaseModel):
    """Cursor page (Q3). ``next_cursor`` is opaque; there is no total count."""

    items: list[DocumentListItem]
    next_cursor: str | None = None
    has_more: bool


class DocumentMetadata(DocumentListItem):
    """Metadata of one visible document; shares the list item shape."""
